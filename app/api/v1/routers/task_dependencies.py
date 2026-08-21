import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_active_user,
    get_project_or_404,
    get_task_or_404,
    require_project_role,
)
from app.db.session import get_db
from app.models.project import Project
from app.models.project_member import ProjectRole
from app.models.task import Task
from app.models.user import User
from app.schemas.task_dependency import TaskDependencyCreate, TaskDependencyGraph
from app.services.task_dependency_service import (
    CrossProjectDependencyError,
    DependencyCycleError,
    DependencyNotFoundError,
    DuplicateDependencyError,
    SelfDependencyError,
    add_dependency,
    list_blockers,
    list_dependents,
    open_blockers,
    remove_dependency,
)
from app.services.task_service import get_task

router = APIRouter(
    prefix="/organizations/{org_id}/projects/{project_id}/tasks/{task_id}/dependencies",
    tags=["task-dependencies"],
)


def _graph(db: Session, task: Task) -> TaskDependencyGraph:
    blocked_by = list_blockers(db, task.id)
    still_open = open_blockers(db, task.id)
    return TaskDependencyGraph(
        blocked_by=blocked_by,
        blocks=list_dependents(db, task.id),
        open_blockers=still_open,
        is_blocked=bool(still_open),
    )


@router.get("", response_model=TaskDependencyGraph)
def get_graph(
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
) -> TaskDependencyGraph:
    """What this task waits on, and what waits on it."""
    return _graph(db, task)


@router.post("", response_model=TaskDependencyGraph, status_code=status.HTTP_201_CREATED)
def add(
    dependency_in: TaskDependencyCreate,
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.EDITOR)),
    current_user: User = Depends(get_current_active_user),
) -> TaskDependencyGraph:
    """Declare that this task cannot be completed until another one is."""
    blocker = get_task(db, project.id, dependency_in.depends_on_id)
    if blocker is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dependency task not found"
        )

    try:
        add_dependency(db, project, task, blocker, current_user)
    except (SelfDependencyError, CrossProjectDependencyError) as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except (DuplicateDependencyError, DependencyCycleError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return _graph(db, task)


@router.delete("/{depends_on_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(
    depends_on_id: uuid.UUID,
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.EDITOR)),
    current_user: User = Depends(get_current_active_user),
) -> None:
    blocker = get_task(db, project.id, depends_on_id, include_deleted=True)
    if blocker is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Dependency task not found"
        )

    try:
        remove_dependency(db, task, blocker, current_user)
    except DependencyNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
