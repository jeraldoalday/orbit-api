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
from app.core.storage import ObjectStorage, get_storage
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole
from app.models.project import Project
from app.models.project_member import ProjectRole
from app.models.task import Task, TaskPriority, TaskStatus
from app.models.user import User
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate
from app.schemas.task_bulk import BulkTaskDelete, BulkTaskResult, BulkTaskUpdate
from app.services.task_bulk_service import bulk_delete_tasks, bulk_update_tasks
from app.services.task_service import (
    AssigneeNotMemberError,
    MilestoneNotInProjectError,
    TaskBlockedError,
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
    except (AssigneeNotMemberError, MilestoneNotInProjectError) as exc:
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
    milestone_id: Optional[uuid.UUID] = None,
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
        milestone_id=milestone_id,
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


def _check_batch_size(task_ids: list) -> None:
    if len(task_ids) > settings.bulk_task_max_items:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"At most {settings.bulk_task_max_items} tasks per request",
        )


# Also registered before "/{task_id}", for the same reason "/deleted" is.
@router.post("/bulk", response_model=BulkTaskResult)
def bulk_update(
    payload: BulkTaskUpdate,
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.EDITOR)),
    current_user: User = Depends(get_current_active_user),
) -> BulkTaskResult:
    """Apply one edit to many tasks, reporting on each of them.

    Answers 200 with a per-task breakdown rather than failing the batch: a
    selection routinely contains something that can't take the edit, and one
    such task shouldn't discard the other forty-nine.
    """
    _check_batch_size(payload.task_ids)
    try:
        return bulk_update_tasks(db, project, payload.task_ids, payload.as_changes(), current_user)
    except (AssigneeNotMemberError, MilestoneNotInProjectError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post("/bulk/delete", response_model=BulkTaskResult)
def bulk_delete(
    payload: BulkTaskDelete,
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.ADMIN)),
    current_user: User = Depends(get_current_active_user),
) -> BulkTaskResult:
    """Soft-delete many tasks. Admin-gated, like deleting one."""
    _check_batch_size(payload.task_ids)
    return bulk_delete_tasks(db, project, payload.task_ids, current_user)


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
    except (AssigneeNotMemberError, MilestoneNotInProjectError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except TaskBlockedError as exc:
        # 409, not 422: the request is well-formed and would be accepted the
        # moment the blockers close, which is a state conflict rather than a
        # validation error.
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


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
    project: Project = Depends(get_project_or_404),
    task: Task = Depends(get_deleted_task_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.OWNER)),
    current_user: User = Depends(get_current_active_user),
    storage: ObjectStorage = Depends(get_storage),
) -> None:
    """Irreversibly delete a task with its comments, activity and attachments."""
    if not task.is_deleted:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Delete the task before purging it"
        )
    purge_task(db, storage, project, task, current_user)
