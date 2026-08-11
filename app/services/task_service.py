import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.task import Task
from app.schemas.task import TaskCreate, TaskUpdate
from app.services.membership_service import get_membership


class AssigneeNotMemberError(Exception):
    pass


def _check_assignee_is_member(db: Session, project: Project, assignee_id: uuid.UUID) -> None:
    if get_membership(db, project.organization_id, assignee_id) is None:
        raise AssigneeNotMemberError("Assignee is not a member of this organization")


def create_task(db: Session, project: Project, task_in: TaskCreate) -> Task:
    if task_in.assignee_id is not None:
        _check_assignee_is_member(db, project, task_in.assignee_id)

    task = Task(
        project_id=project.id,
        title=task_in.title,
        description=task_in.description,
        assignee_id=task_in.assignee_id,
    )
    db.add(task)
    db.commit()
    db.refresh(task)
    return task


def get_task(db: Session, project_id: uuid.UUID, task_id: uuid.UUID) -> Optional[Task]:
    stmt = select(Task).where(Task.id == task_id, Task.project_id == project_id)
    return db.execute(stmt).scalar_one_or_none()


def list_tasks(db: Session, project_id: uuid.UUID) -> list[Task]:
    stmt = select(Task).where(Task.project_id == project_id).order_by(Task.created_at)
    return list(db.execute(stmt).scalars().all())


def update_task(db: Session, project: Project, task: Task, task_in: TaskUpdate) -> Task:
    fields_set = task_in.model_fields_set

    if task_in.title is not None:
        task.title = task_in.title
    if task_in.description is not None:
        task.description = task_in.description
    if task_in.status is not None:
        task.status = task_in.status
    if "assignee_id" in fields_set:
        if task_in.assignee_id is not None:
            _check_assignee_is_member(db, project, task_in.assignee_id)
        task.assignee_id = task_in.assignee_id

    db.commit()
    db.refresh(task)
    return task


def delete_task(db: Session, task: Task) -> None:
    db.delete(task)
    db.commit()
