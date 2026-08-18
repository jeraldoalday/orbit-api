import uuid
from datetime import datetime
from typing import Literal, Optional

from sqlalchemy import asc, case, desc, select
from sqlalchemy.orm import Session

from app.models.notification import NotificationType
from app.models.project import Project
from app.models.task import Task, TaskPriority, TaskStatus
from app.models.task_activity import TaskActivityType
from app.models.task_label import TaskLabel
from app.models.user import User
from app.models.webhook import WebhookEvent
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.membership_service import get_membership
from app.services.notification_service import create_notification
from app.services.task_activity_service import record_activity
from app.services.webhook_events import emit_task_event

TaskSortField = Literal["created_at", "title", "status", "priority", "due_date"]

# Priorities sort by urgency rank rather than the enum's stored name, since
# alphabetical order ("HIGH" < "LOW" < "MEDIUM" < "URGENT") doesn't match it.
_PRIORITY_RANK = {
    TaskPriority.LOW: 0,
    TaskPriority.MEDIUM: 1,
    TaskPriority.HIGH: 2,
    TaskPriority.URGENT: 3,
}
_PRIORITY_SORT_EXPRESSION = case(
    *[(Task.priority == priority, rank) for priority, rank in _PRIORITY_RANK.items()]
)

_SORT_COLUMNS: dict[str, object] = {
    "created_at": Task.created_at,
    "title": Task.title,
    "status": Task.status,
    "priority": _PRIORITY_SORT_EXPRESSION,
    "due_date": Task.due_date,
}


class AssigneeNotMemberError(Exception):
    pass


def _check_assignee_is_member(db: Session, project: Project, assignee_id: uuid.UUID) -> None:
    if get_membership(db, project.organization_id, assignee_id) is None:
        raise AssigneeNotMemberError("Assignee is not a member of this organization")


def _notify_assignee(
    db: Session, project: Project, task: Task, actor: User, assignee_id: uuid.UUID
) -> None:
    create_notification(
        db,
        user_id=assignee_id,
        organization_id=project.organization_id,
        notification_type=NotificationType.TASK_ASSIGNED,
        actor=actor,
        task_id=task.id,
        data={"task_title": task.title, "project_id": str(project.id)},
        commit=False,
    )


def create_task(db: Session, project: Project, task_in: TaskCreate, actor: User) -> Task:
    if task_in.assignee_id is not None:
        _check_assignee_is_member(db, project, task_in.assignee_id)

    task = Task(
        project_id=project.id,
        title=task_in.title,
        description=task_in.description,
        assignee_id=task_in.assignee_id,
        priority=task_in.priority,
        due_date=task_in.due_date,
    )
    db.add(task)
    db.flush()
    record_activity(db, task.id, actor, TaskActivityType.CREATED, commit=False)
    if task.assignee_id is not None:
        _notify_assignee(db, project, task, actor, task.assignee_id)
    emit_task_event(db, project, task, WebhookEvent.TASK_CREATED, actor)
    db.commit()
    db.refresh(task)
    return task


def get_task(
    db: Session, project_id: uuid.UUID, task_id: uuid.UUID, *, include_deleted: bool = False
) -> Optional[Task]:
    stmt = select(Task).where(Task.id == task_id, Task.project_id == project_id)
    if not include_deleted:
        stmt = stmt.where(Task.deleted_at.is_(None))
    return db.execute(stmt).scalar_one_or_none()


def list_tasks(
    db: Session,
    project_id: uuid.UUID,
    *,
    status: Optional[TaskStatus] = None,
    assignee_id: Optional[uuid.UUID] = None,
    priority: Optional[TaskPriority] = None,
    due_before: Optional[datetime] = None,
    due_after: Optional[datetime] = None,
    label_id: Optional[uuid.UUID] = None,
    sort_by: TaskSortField = "created_at",
    order: Literal["asc", "desc"] = "asc",
    include_deleted: bool = False,
    limit: int = 50,
    offset: int = 0,
) -> list[Task]:
    stmt = select(Task).where(Task.project_id == project_id)

    if not include_deleted:
        stmt = stmt.where(Task.deleted_at.is_(None))
    if status is not None:
        stmt = stmt.where(Task.status == status)
    if assignee_id is not None:
        stmt = stmt.where(Task.assignee_id == assignee_id)
    if priority is not None:
        stmt = stmt.where(Task.priority == priority)
    if due_before is not None:
        stmt = stmt.where(Task.due_date <= due_before)
    if due_after is not None:
        stmt = stmt.where(Task.due_date >= due_after)
    if label_id is not None:
        stmt = stmt.join(TaskLabel, TaskLabel.task_id == Task.id).where(
            TaskLabel.label_id == label_id
        )

    sort_column = _SORT_COLUMNS[sort_by]
    direction = asc if order == "asc" else desc
    stmt = stmt.order_by(direction(sort_column), Task.id)

    stmt = stmt.limit(limit).offset(offset)

    return list(db.execute(stmt).scalars().all())


def list_deleted_tasks(
    db: Session, project_id: uuid.UUID, *, limit: int = 50, offset: int = 0
) -> list[Task]:
    """Soft-deleted tasks in a project, most recently deleted first."""
    stmt = (
        select(Task)
        .where(Task.project_id == project_id, Task.deleted_at.is_not(None))
        .order_by(Task.deleted_at.desc(), Task.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def update_task(
    db: Session, project: Project, task: Task, task_in: TaskUpdate, actor: User
) -> Task:
    fields_set = task_in.model_fields_set
    changes: dict[str, dict[str, object]] = {}

    if task_in.title is not None and task_in.title != task.title:
        changes["title"] = {"from": task.title, "to": task_in.title}
        task.title = task_in.title
    if "description" in fields_set and task_in.description != task.description:
        changes["description"] = {"from": task.description, "to": task_in.description}
        task.description = task_in.description
    if task_in.status is not None and task_in.status != task.status:
        changes["status"] = {"from": task.status.value, "to": task_in.status.value}
        task.status = task_in.status
    if task_in.priority is not None and task_in.priority != task.priority:
        changes["priority"] = {"from": task.priority.value, "to": task_in.priority.value}
        task.priority = task_in.priority
    if "due_date" in fields_set and task_in.due_date != task.due_date:
        changes["due_date"] = {
            "from": task.due_date.isoformat() if task.due_date else None,
            "to": task_in.due_date.isoformat() if task_in.due_date else None,
        }
        task.due_date = task_in.due_date
    if "assignee_id" in fields_set and task_in.assignee_id != task.assignee_id:
        if task_in.assignee_id is not None:
            _check_assignee_is_member(db, project, task_in.assignee_id)
        changes["assignee_id"] = {
            "from": str(task.assignee_id) if task.assignee_id else None,
            "to": str(task_in.assignee_id) if task_in.assignee_id else None,
        }
        task.assignee_id = task_in.assignee_id
        if task_in.assignee_id is not None:
            _notify_assignee(db, project, task, actor, task_in.assignee_id)

    if changes:
        record_activity(db, task.id, actor, TaskActivityType.UPDATED, changes, commit=False)
        # Only a real change is worth a delivery: a PATCH that sets a field to
        # the value it already had shouldn't wake up every subscriber.
        emit_task_event(
            db, project, task, WebhookEvent.TASK_UPDATED, actor, extra={"changes": changes}
        )
        if "assignee_id" in changes:
            # A reassignment is the one update most integrations act on, so it
            # gets its own event rather than being buried in a changes diff.
            emit_task_event(db, project, task, WebhookEvent.TASK_ASSIGNED, actor)

    db.commit()
    db.refresh(task)

    return task


def soft_delete_task(
    db: Session, project: Project, task: Task, actor: Optional[User] = None
) -> Task:
    task.mark_deleted()
    emit_task_event(db, project, task, WebhookEvent.TASK_DELETED, actor)
    db.commit()
    db.refresh(task)
    return task


def restore_task(db: Session, project: Project, task: Task, actor: Optional[User] = None) -> Task:
    task.mark_restored()
    # A restore is a change to the task the same way a status flip is, so it
    # goes out as task.updated rather than needing an event of its own.
    emit_task_event(
        db, project, task, WebhookEvent.TASK_UPDATED, actor, extra={"changes": {"restored": True}}
    )
    db.commit()
    db.refresh(task)
    return task


def purge_task(db: Session, task: Task) -> None:
    """Delete for real, taking the task's comments, activity and files with it."""
    db.delete(task)
    db.commit()
