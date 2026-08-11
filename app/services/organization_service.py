import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.slug import generate_unique_org_slug
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.user import User
from app.schemas.organization import OrganizationCreate, OrganizationUpdate


def create_organization(db: Session, owner: User, org_in: OrganizationCreate) -> Organization:
    organization = Organization(
        name=org_in.name,
        slug=generate_unique_org_slug(db, org_in.name),
    )
    db.add(organization)
    db.flush()

    owner_membership = Membership(
        organization_id=organization.id,
        user_id=owner.id,
        role=MembershipRole.OWNER,
    )
    db.add(owner_membership)
    db.commit()
    db.refresh(organization)
    return organization


def get_organization(db: Session, org_id: uuid.UUID) -> Optional[Organization]:
    return db.get(Organization, org_id)


def list_organizations_for_user(db: Session, user_id: uuid.UUID) -> list[Organization]:
    stmt = (
        select(Organization)
        .join(Membership, Membership.organization_id == Organization.id)
        .where(Membership.user_id == user_id)
        .order_by(Organization.name)
    )
    return list(db.execute(stmt).scalars().all())


def update_organization(
    db: Session, organization: Organization, org_in: OrganizationUpdate
) -> Organization:
    if org_in.name is not None:
        organization.name = org_in.name
    db.commit()
    db.refresh(organization)
    return organization


def delete_organization(db: Session, organization: Organization) -> None:
    db.delete(organization)
    db.commit()
