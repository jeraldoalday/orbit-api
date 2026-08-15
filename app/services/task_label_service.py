import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.label import Label
from app.models.task import Task
from app.models.task_label import TaskLabel


class AlreadyAttachedError(Exception):
    pass


class LabelNotAttachedError(Exception):
    pass


def _get_link(db: Session, task_id: uuid.UUID, label_id: uuid.UUID) -> Optional[TaskLabel]:
    stmt = select(TaskLabel).where(TaskLabel.task_id == task_id, TaskLabel.label_id == label_id)
    return db.execute(stmt).scalar_one_or_none()


def attach_label(db: Session, task: Task, label: Label) -> TaskLabel:
    if _get_link(db, task.id, label.id) is not None:
        raise AlreadyAttachedError(f"Label {label.name!r} is already attached to this task")

    link = TaskLabel(task_id=task.id, label_id=label.id)
    db.add(link)
    db.commit()
    return link


def detach_label(db: Session, task: Task, label: Label) -> None:
    link = _get_link(db, task.id, label.id)
    if link is None:
        raise LabelNotAttachedError(f"Label {label.name!r} is not attached to this task")

    db.delete(link)
    db.commit()


def list_labels_for_task(db: Session, task_id: uuid.UUID) -> list[Label]:
    stmt = (
        select(Label)
        .join(TaskLabel, TaskLabel.label_id == Label.id)
        .where(TaskLabel.task_id == task_id)
        .order_by(Label.name, Label.id)
    )
    return list(db.execute(stmt).scalars().all())
