import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.task_activity import TaskActivity, TaskActivityType
from app.models.user import User


def record_activity(
    db: Session,
    task_id: uuid.UUID,
    actor: Optional[User],
    activity_type: TaskActivityType,
    data: Optional[dict[str, Any]] = None,
    commit: bool = True,
) -> TaskActivity:
    activity = TaskActivity(
        task_id=task_id,
        actor_id=actor.id if actor is not None else None,
        activity_type=activity_type,
        data=data,
    )
    db.add(activity)
    if commit:
        db.commit()
        db.refresh(activity)
    return activity


def list_activities(db: Session, task_id: uuid.UUID) -> list[TaskActivity]:
    stmt = (
        select(TaskActivity)
        .where(TaskActivity.task_id == task_id)
        .order_by(TaskActivity.created_at, TaskActivity.id)
    )
    return list(db.execute(stmt).scalars().all())
