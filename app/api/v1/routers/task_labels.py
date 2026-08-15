import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_organization_or_404, get_task_or_404, require_org_member
from app.db.session import get_db
from app.models.membership import Membership
from app.models.organization import Organization
from app.models.task import Task
from app.schemas.label import LabelRead
from app.schemas.task_label import TaskLabelAttach
from app.services.label_service import get_label
from app.services.task_label_service import (
    AlreadyAttachedError,
    LabelNotAttachedError,
    attach_label,
    detach_label,
    list_labels_for_task,
)

router = APIRouter(
    prefix="/organizations/{org_id}/projects/{project_id}/tasks/{task_id}/labels",
    tags=["task-labels"],
)


def _get_label_or_404(db: Session, organization: Organization, label_id: uuid.UUID):
    label = get_label(db, organization.id, label_id)
    if label is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Label not found")
    return label


@router.get("", response_model=list[LabelRead])
def list_mine(
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    _membership: Membership = Depends(require_org_member),
) -> list[LabelRead]:
    return list_labels_for_task(db, task.id)


@router.post("", response_model=LabelRead, status_code=status.HTTP_201_CREATED)
def attach(
    body: TaskLabelAttach,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    task: Task = Depends(get_task_or_404),
    _membership: Membership = Depends(require_org_member),
) -> LabelRead:
    label = _get_label_or_404(db, organization, body.label_id)
    try:
        attach_label(db, task, label)
    except AlreadyAttachedError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return label


@router.delete("/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
def detach(
    label_id: uuid.UUID,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    task: Task = Depends(get_task_or_404),
    _membership: Membership = Depends(require_org_member),
) -> None:
    label = _get_label_or_404(db, organization, label_id)
    try:
        detach_label(db, task, label)
    except LabelNotAttachedError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
