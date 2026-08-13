import uuid
from typing import Literal, Optional

from sqlalchemy import asc, desc, select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.models.task_activity import TaskActivityType
from app.models.user import User
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.membership_service import get_membership
from app.services.task_activity_service import record_activity

TaskSortField = Literal["created_at", "title", "status"]

_SORT_COLUMNS: dict[str, object] = {
    "created_at": Task.created_at,
    "title": Task.title,
    "status": Task.status,
}


class AssigneeNotMemberError(Exception):
    pass


def _check_assignee_is_member(db: Session, project: Project, assignee_id: uuid.UUID) -> None:
    if get_membership(db, project.organization_id, assignee_id) is None:
        raise AssigneeNotMemberError("Assignee is not a member of this organization")


def create_task(db: Session, project: Project, task_in: TaskCreate, actor: User) -> Task:
    if task_in.assignee_id is not None:
        _check_assignee_is_member(db, project, task_in.assignee_id)

    task = Task(
        project_id=project.id,
        title=task_in.title,
        description=task_in.description,
        assignee_id=task_in.assignee_id,
    )
    db.add(task)
    db.flush()
    record_activity(db, task.id, actor, TaskActivityType.CREATED, commit=False)
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, project_id: uuid.UUID, task_id: uuid.UUID) -> Optional[Task]:
    stmt = select(Task).where(Task.id == task_id, Task.project_id == project_id)
    return db.execute(stmt).scalar_one_or_none()


def list_tasks(
    db: Session,
    project_id: uuid.UUID,
    *,
    status: Optional[TaskStatus] = None,
    assignee_id: Optional[uuid.UUID] = None,
    sort_by: TaskSortField = "created_at",
    order: Literal["asc", "desc"] = "asc",
    limit: int = 50,
    offset: int = 0,
) -> list[Task]:
    stmt = select(Task).where(Task.project_id == project_id)

    if status is not None:
        stmt = stmt.where(Task.status == status)
    if assignee_id is not None:
        stmt = stmt.where(Task.assignee_id == assignee_id)

    sort_column = _SORT_COLUMNS[sort_by]
    direction = asc if order == "asc" else desc
    stmt = stmt.order_by(direction(sort_column), Task.id)

    stmt = stmt.limit(limit).offset(offset)

    return list(db.execute(stmt).scalars().all())


def update_task(
    db: Session, project: Project, task: Task, task_in: TaskUpdate, actor: User
) -> Task:
    fields_set = task_in.model_fields_set
    changes: dict[str, dict[str, object]] = {}

    if task_in.title is not None and task_in.title != task.title:
        changes["title"] = {"from": task.title, "to": task_in.title}
        task.title = task_in.title
    if task_in.description is not None and task_in.description != task.description:
        changes["description"] = {"from": task.description, "to": task_in.description}
        task.description = task_in.description
    if task_in.status is not None and task_in.status != task.status:
        changes["status"] = {"from": task.status.value, "to": task_in.status.value}
        task.status = task_in.status
    if "assignee_id" in fields_set and task_in.assignee_id != task.assignee_id:
        if task_in.assignee_id is not None:
            _check_assignee_is_member(db, project, task_in.assignee_id)
        changes["assignee_id"] = {
            "from": str(task.assignee_id) if task.assignee_id else None,
            "to": str(task_in.assignee_id) if task_in.assignee_id else None,
        }
        task.assignee_id = task_in.assignee_id

    if changes:
        record_activity(db, task.id, actor, TaskActivityType.UPDATED, changes, commit=False)

    db.commit()
    db.refresh(task)

    return task


def delete_task(db: Session, task: Task) -> None:
    db.delete(task)
    db.commit()
