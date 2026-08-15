from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_label_or_404,
    get_organization_or_404,
    require_org_member,
    require_org_role,
)
from app.db.session import get_db
from app.models.label import Label
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.schemas.label import LabelCreate, LabelRead
from app.services.label_service import DuplicateLabelError, create_label, delete_label, list_labels

router = APIRouter(prefix="/organizations/{org_id}/labels", tags=["labels"])


@router.post("", response_model=LabelRead, status_code=status.HTTP_201_CREATED)
def create(
    label_in: LabelCreate,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    _membership: Membership = Depends(require_org_member),
) -> LabelRead:
    try:
        return create_label(db, organization, label_in.name, label_in.color)
    except DuplicateLabelError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("", response_model=list[LabelRead])
def list_mine(
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    _membership: Membership = Depends(require_org_member),
) -> list[LabelRead]:
    return list_labels(db, organization.id)


@router.delete("/{label_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    db: Session = Depends(get_db),
    label: Label = Depends(get_label_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.ADMIN)),
) -> None:
    delete_label(db, label)
