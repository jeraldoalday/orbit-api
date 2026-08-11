from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_organization_or_404, require_org_role
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.user import User
from app.schemas.organization import OrganizationCreate, OrganizationRead, OrganizationUpdate
from app.services.organization_service import (
    create_organization,
    delete_organization,
    list_organizations_for_user,
    update_organization,
)

router = APIRouter(prefix="/organizations", tags=["organizations"])


@router.post("", response_model=OrganizationRead, status_code=status.HTTP_201_CREATED)
def create(
    org_in: OrganizationCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> OrganizationRead:
    return create_organization(db, current_user, org_in)


@router.get("", response_model=list[OrganizationRead])
def list_mine(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> list[OrganizationRead]:
    return list_organizations_for_user(db, current_user.id)


@router.get("/{org_id}", response_model=OrganizationRead)
def get(
    organization: Organization = Depends(get_organization_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.MEMBER)),
) -> OrganizationRead:
    return organization


@router.patch("/{org_id}", response_model=OrganizationRead)
def update(
    org_in: OrganizationUpdate,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.ADMIN)),
) -> OrganizationRead:
    return update_organization(db, organization, org_in)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.OWNER)),
) -> None:
    delete_organization(db, organization)
