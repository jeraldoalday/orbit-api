import uuid
from typing import Optional

from fastapi import APIRouter, Body, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_active_user,
    get_project_or_404,
    get_task_or_404,
    require_project_role,
)
from app.db.session import get_db
from app.models.project import Project
from app.models.project_member import ProjectRole, project_role_at_least
from app.models.task import Task
from app.models.user import User
from app.schemas.task_watcher import TaskWatcherRead, WatcherCreate
from app.services.task_watcher_service import (
    AlreadyWatchingError,
    NotWatchingError,
    WatcherCannotSeeProjectError,
    WatcherNotFoundError,
    add_watcher,
    add_watcher_by_email,
    list_watchers,
    remove_watcher,
)

router = APIRouter(
    prefix="/organizations/{org_id}/projects/{project_id}/tasks/{task_id}/watchers",
    tags=["task-watchers"],
)


@router.get("", response_model=list[TaskWatcherRead])
def list_all(
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
) -> list[TaskWatcherRead]:
    return list_watchers(db, task.id)


@router.post("", response_model=TaskWatcherRead, status_code=status.HTTP_201_CREATED)
def watch(
    watcher_in: Optional[WatcherCreate] = Body(default=None),
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    task: Task = Depends(get_task_or_404),
    role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
    current_user: User = Depends(get_current_active_user),
) -> TaskWatcherRead:
    """Watch a task. With no body, the caller watches it themselves.

    Watching something you can already read costs nobody anything, so a plain
    viewer may do it — a read-only reviewer is exactly who wants this. Signing
    *somebody else* up is an edit to the task's audience, so that needs editor
    rights.
    """
    if watcher_in is None:
        try:
            return add_watcher(db, project, task, current_user)
        except AlreadyWatchingError as exc:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    is_self = watcher_in.email.strip().lower() == current_user.email.lower()
    if not is_self and not project_role_at_least(role, ProjectRole.EDITOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a project editor can add someone else as a watcher",
        )

    try:
        return add_watcher_by_email(db, project, task, watcher_in.email)
    except WatcherNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except WatcherCannotSeeProjectError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except AlreadyWatchingError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def unwatch(
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Stop watching."""
    try:
        remove_watcher(db, task, current_user.id)
    except NotWatchingError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(
    user_id: uuid.UUID,
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
    current_user: User = Depends(get_current_active_user),
) -> None:
    """Remove a watcher: anyone may remove themselves, editors may remove others."""
    if user_id != current_user.id and not project_role_at_least(role, ProjectRole.EDITOR):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a project editor can remove someone else's watch",
        )

    try:
        remove_watcher(db, task, user_id)
    except NotWatchingError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
