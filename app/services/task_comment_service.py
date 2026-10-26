import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.notification import NotificationType
from app.models.project import Project
from app.models.task import Task
from app.models.task_comment import TaskComment
from app.models.user import User
from app.models.webhook import WebhookEvent
from app.services.auth_service import get_user_by_email
from app.services.notification_service import create_notification, extract_mentions
from app.services.project_member_service import can_see_project
from app.services.task_watcher_service import notify_watchers
from app.services.webhook_events import emit_comment_event


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
        # Mentioning someone who can't reach the project is a no-op: the
        # notification carries the task title and project id, so sending it to
        # a non-member — or to an org member excluded from a restricted
        # project — hands them exactly what the restriction withholds.
        if not can_see_project(db, project, mentioned.id):
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
        notified.add(task.assignee_id)

    # Watchers last, minus everyone already covered above: one comment must
    # never leave two rows in the same inbox.
    notify_watchers(
        db,
        project,
        task,
        author,
        NotificationType.TASK_COMMENTED,
        payload,
        skip=notified,
        commit=False,
    )


def create_comment(
    db: Session, project: Project, task: Task, author: User, body: str
) -> TaskComment:
    comment = TaskComment(task_id=task.id, author_id=author.id, body=body)
    db.add(comment)
    db.flush()
    _notify_comment(db, project, task, author, comment)
    emit_comment_event(db, project, task, comment, author)
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


def update_comment(db: Session, comment: TaskComment, body: str) -> TaskComment:
    """Edit a comment's body in place.

    Unlike a task field, a comment has no change to log on the timeline and
    nothing new to notify about — editing a typo shouldn't re-fire the mention
    and watcher fan-out a new comment gets. `updated_at` moves on its own via
    the model's `onupdate`, which is what tells a reader the comment was
    edited at all.
    """
    comment.body = body
    db.commit()
    db.refresh(comment)
    return comment


def delete_comment(
    db: Session, project: Project, task: Task, comment: TaskComment, actor: User
) -> None:
    """Delete a comment and tell subscribers it's gone.

    The event is queued before the row is: the payload has to be captured
    while the comment still exists, the same reason task deletion's event
    carries the task's final state rather than nothing at all.
    """
    emit_comment_event(db, project, task, comment, actor, event=WebhookEvent.COMMENT_DELETED)
    db.delete(comment)
    db.commit()
