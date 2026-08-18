import uuid
from datetime import datetime
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_active_user,
    get_deleted_task_or_404,
    get_project_or_404,
    get_task_or_404,
    require_org_role,
    require_project_role,
)
from app.core.config import get_settings
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole
from app.models.project import Project
from app.models.project_member import ProjectRole
from app.models.task import Task, TaskPriority, TaskStatus
from app.models.user import User
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate
from app.services.task_service import (
    AssigneeNotMemberError,
    create_task,
    list_deleted_tasks,
    list_tasks,
    purge_task,
    restore_task,
    soft_delete_task,
    update_task,
)

settings = get_settings()

router = APIRouter(prefix="/organizations/{org_id}/projects/{project_id}/tasks", tags=["tasks"])


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create(
    task_in: TaskCreate,
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.EDITOR)),
    current_user: User = Depends(get_current_active_user),
) -> TaskRead:
    try:
        return create_task(db, project, task_in, current_user)
    except AssigneeNotMemberError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.get("", response_model=list[TaskRead])
def list_mine(
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
    status_: Optional[TaskStatus] = Query(default=None, alias="status"),
    assignee_id: Optional[uuid.UUID] = None,
    priority: Optional[TaskPriority] = None,
    due_before: Optional[datetime] = None,
    due_after: Optional[datetime] = None,
    label_id: Optional[uuid.UUID] = None,
    sort_by: Literal["created_at", "title", "status", "priority", "due_date"] = "created_at",
    order: Literal["asc", "desc"] = "asc",
    limit: int = Query(
        default=settings.task_list_default_limit, ge=1, le=settings.task_list_max_limit
    ),
    offset: int = Query(default=0, ge=0),
) -> list[TaskRead]:
    return list_tasks(
        db,
        project.id,
        status=status_,
        assignee_id=assignee_id,
        priority=priority,
        due_before=due_before,
        due_after=due_after,
        label_id=label_id,
        sort_by=sort_by,
        order=order,
        limit=limit,
        offset=offset,
    )


# Registered before "/{task_id}" so the literal path wins the match.
@router.get("/deleted", response_model=list[TaskRead])
def list_deleted(
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.ADMIN)),
    limit: int = Query(
        default=settings.task_list_default_limit, ge=1, le=settings.task_list_max_limit
    ),
    offset: int = Query(default=0, ge=0),
) -> list[TaskRead]:
    return list_deleted_tasks(db, project.id, limit=limit, offset=offset)


@router.get("/{task_id}", response_model=TaskRead)
def get(
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
) -> TaskRead:
    return task


@router.patch("/{task_id}", response_model=TaskRead)
def update(
    task_in: TaskUpdate,
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.EDITOR)),
    current_user: User = Depends(get_current_active_user),
) -> TaskRead:
    try:
        return update_task(db, project, task, task_in, current_user)
    except AssigneeNotMemberError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.delete("/{task_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    task: Task = Depends(get_task_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.ADMIN)),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Soft-delete: the task vanishes from every read but stays restorable."""
    soft_delete_task(db, project, task, current_user)


@router.post("/{task_id}/restore", response_model=TaskRead)
def restore(
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    task: Task = Depends(get_deleted_task_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.ADMIN)),
    current_user: User = Depends(get_current_active_user),
) -> TaskRead:
    if not task.is_deleted:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Task is not deleted")
    return restore_task(db, project, task, current_user)


@router.delete("/{task_id}/purge", status_code=status.HTTP_204_NO_CONTENT)
def purge(
    db: Session = Depends(get_db),
    task: Task = Depends(get_deleted_task_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.OWNER)),
) -> None:
    """Irreversibly delete a task with its comments, activity and attachments."""
    if not task.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Delete the task before purging it"
        )
    purge_task(db, task)
