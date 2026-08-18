import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.notification import NotificationType
from app.models.project import Project
from app.models.task import Task
from app.models.task_comment import TaskComment
from app.models.user import User
from app.services.auth_service import get_user_by_email
from app.services.membership_service import get_membership
from app.services.notification_service import create_notification, extract_mentions


def _notify_comment(
    db: Session, project: Project, task: Task, author: User, comment: TaskComment
) -> None:
    """Fan a new comment out to the people it concerns.

    A mention is the stronger signal, so anyone named in the body gets a
    MENTIONED notification and is then skipped for the generic assignee ping —
    one comment should never produce two rows for the same person.
    """
    payload = {
        "task_title": task.title,
        "project_id": str(project.id),
        "comment_id": str(comment.id),
    }
    notified: set[uuid.UUID] = set()

    for email in extract_mentions(comment.body):
        mentioned = get_user_by_email(db, email)
        if mentioned is None or mentioned.id in notified:
            continue
        # Only org members can see the task, so mentioning an outsider is a no-op.
        if get_membership(db, project.organization_id, mentioned.id) is None:
            continue
        create_notification(
            db,
            user_id=mentioned.id,
            organization_id=project.organization_id,
            notification_type=NotificationType.MENTIONED,
            actor=author,
            task_id=task.id,
            data=payload,
            commit=False,
        )
        notified.add(mentioned.id)

    if task.assignee_id is not None and task.assignee_id not in notified:
        create_notification(
            db,
            user_id=task.assignee_id,
            organization_id=project.organization_id,
            notification_type=NotificationType.TASK_COMMENTED,
            actor=author,
            task_id=task.id,
            data=payload,
            commit=False,
        )


def create_comment(
    db: Session, project: Project, task: Task, author: User, body: str
) -> TaskComment:
    comment = TaskComment(task_id=task.id, author_id=author.id, body=body)
    db.add(comment)
    db.flush()
    _notify_comment(db, project, task, author, comment)
    db.commit()
    db.refresh(comment)
    return comment


def get_comment(db: Session, task_id: uuid.UUID, comment_id: uuid.UUID) -> Optional[TaskComment]:
    stmt = select(TaskComment).where(TaskComment.id == comment_id, TaskComment.task_id == task_id)
    return db.execute(stmt).scalar_one_or_none()


def list_comments(db: Session, task_id: uuid.UUID) -> list[TaskComment]:
    stmt = (
        select(TaskComment)
        .options(joinedload(TaskComment.author))
        .where(TaskComment.task_id == task_id)
        .order_by(TaskComment.created_at, TaskComment.id)
    )
    return list(db.execute(stmt).scalars().all())


def delete_comment(db: Session, comment: TaskComment) -> None:
    db.delete(comment)
    db.commit()
