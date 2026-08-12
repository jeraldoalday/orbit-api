import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.task_comment import TaskComment
from app.models.user import User


def create_comment(db: Session, task_id: uuid.UUID, author: User, body: str) -> TaskComment:
    comment = TaskComment(task_id=task_id, author_id=author.id, body=body)
    db.add(comment)
    db.commit()
    db.refresh(comment)
    return comment


def get_comment(db: Session, task_id: uuid.UUID, comment_id: uuid.UUID) -> Optional[TaskComment]:
    stmt = select(TaskComment).where(
        TaskComment.id == comment_id, TaskComment.task_id == task_id
    )
    return db.execute(stmt).scalar_one_or_none()


def list_comments(db: Session, task_id: uuid.UUID) -> list[TaskComment]:
    stmt = (
        select(TaskComment)
        .options(joinedload(TaskComment.author))
        .where(TaskComment.task_id == task_id)
        .order_by(TaskComment.created_at)
    )
    return list(db.execute(stmt).scalars().all())


def delete_comment(db: Session, comment: TaskComment) -> None:
    db.delete(comment)
    db.commit()
