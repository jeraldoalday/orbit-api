import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_task_or_404, require_project_role
from app.core.config import get_settings
from app.db.session import get_db
from app.models.project_member import ProjectRole
from app.models.task import Task
from app.schemas.task_checklist import (
    ChecklistItemCreate,
    ChecklistItemRead,
    ChecklistItemUpdate,
    ChecklistRead,
    ChecklistReorder,
)
from app.services.task_checklist_service import (
    ChecklistLimitError,
    ChecklistOrderMismatchError,
    add_item,
    checklist,
    delete_item,
    get_item,
    reorder_items,
    update_item,
)

settings = get_settings()

router = APIRouter(
    prefix="/organizations/{org_id}/projects/{project_id}/tasks/{task_id}/checklist",
    tags=["task-checklist"],
)


def _item_or_404(db: Session, task: Task, item_id: uuid.UUID):
    item = get_item(db, task.id, item_id)
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Checklist item not found"
        )
    return item


@router.get("", response_model=ChecklistRead)
def get_checklist(
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
) -> ChecklistRead:
    """The task's steps in order, with how many of them are done."""
    return checklist(db, task.id)


@router.post("", response_model=ChecklistItemRead, status_code=status.HTTP_201_CREATED)
def add(
    item_in: ChecklistItemCreate,
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.EDITOR)),
) -> ChecklistItemRead:
    """Append a step to the end of the checklist."""
    try:
        return add_item(db, task, item_in.content, max_items=settings.checklist_max_items)
    except ChecklistLimitError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.patch("/{item_id}", response_model=ChecklistItemRead)
def update(
    item_id: uuid.UUID,
    changes: ChecklistItemUpdate,
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.EDITOR)),
) -> ChecklistItemRead:
    """Tick, untick or rename one step."""
    return update_item(db, _item_or_404(db, task, item_id), changes)


@router.post("/reorder", response_model=ChecklistRead)
def reorder(
    ordering: ChecklistReorder,
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.EDITOR)),
) -> ChecklistRead:
    """Rewrite the order of the whole checklist."""
    try:
        reorder_items(db, task.id, ordering.item_ids)
    except ChecklistOrderMismatchError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    return checklist(db, task.id)


@router.delete("/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(
    item_id: uuid.UUID,
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.EDITOR)),
) -> None:
    delete_item(db, _item_or_404(db, task, item_id))
