import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_organization_or_404, require_org_member, require_org_role
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole, role_at_least
from app.models.organization import Organization
from app.schemas.membership import MembershipCreate, MembershipRead, MembershipRoleUpdate
from app.services.membership_service import (
    AlreadyMemberError,
    InsufficientRoleError,
    LastOwnerError,
    UserNotFoundError,
    add_member,
    get_membership_by_id,
    list_memberships,
    remove_member,
    update_member_role,
)

router = APIRouter(prefix="/organizations/{org_id}/members", tags=["memberships"])


def _get_target_membership_or_404(
    db: Session, organization: Organization, membership_id: uuid.UUID
) -> Membership:
    membership = get_membership_by_id(db, organization.id, membership_id)
    if membership is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Membership not found")
    return membership


@router.get("", response_model=list[MembershipRead])
def list_members(
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    _membership: Membership = Depends(require_org_member),
) -> list[MembershipRead]:
    return list_memberships(db, organization.id)


@router.post("", response_model=MembershipRead, status_code=status.HTTP_201_CREATED)
def add(
    member_in: MembershipCreate,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    caller_membership: Membership = Depends(require_org_role(MembershipRole.ADMIN)),
) -> MembershipRead:
    try:
        return add_member(
            db, organization, member_in.email, member_in.role, caller_membership.role
        )
    except UserNotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except AlreadyMemberError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InsufficientRoleError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.patch("/{membership_id}", response_model=MembershipRead)
def update_role(
    membership_id: uuid.UUID,
    role_in: MembershipRoleUpdate,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    caller_membership: Membership = Depends(require_org_role(MembershipRole.ADMIN)),
) -> MembershipRead:
    target = _get_target_membership_or_404(db, organization, membership_id)
    try:
        return update_member_role(db, target, role_in.role, caller_membership.role)
    except LastOwnerError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except InsufficientRoleError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc


@router.delete("/{membership_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(
    membership_id: uuid.UUID,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    caller_membership: Membership = Depends(require_org_member),
) -> None:
    target = _get_target_membership_or_404(db, organization, membership_id)

    is_self = target.id == caller_membership.id
    is_admin = role_at_least(caller_membership.role, MembershipRole.ADMIN)
    if not is_self and not is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions for this organization",
        )

    try:
        remove_member(db, target)
    except LastOwnerError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
