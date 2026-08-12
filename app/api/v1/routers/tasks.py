from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_active_user,
    get_project_or_404,
    get_task_or_404,
    require_org_member,
    require_org_role,
)
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole
from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.schemas.task import TaskCreate, TaskRead, TaskUpdate
from app.services.task_service import (
    AssigneeNotMemberError,
    create_task,
    delete_task,
    list_tasks,
    update_task,
)

router = APIRouter(prefix="/organizations/{org_id}/projects/{project_id}/tasks", tags=["tasks"])


@router.post("", response_model=TaskRead, status_code=status.HTTP_201_CREATED)
def create(
    task_in: TaskCreate,
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    _membership: Membership = Depends(require_org_member),
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
    _membership: Membership = Depends(require_org_member),
) -> list[TaskRead]:
    return list_tasks(db, project.id)


@router.get("/{task_id}", response_model=TaskRead)
def get(
    task: Task = Depends(get_task_or_404),
    _membership: Membership = Depends(require_org_member),
) -> TaskRead:
    return task


@router.patch("/{task_id}", response_model=TaskRead)
def update(
    task_in: TaskUpdate,
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    task: Task = Depends(get_task_or_404),
    _membership: Membership = Depends(require_org_member),
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
    task: Task = Depends(get_task_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.ADMIN)),
) -> None:
    delete_task(db, task)
