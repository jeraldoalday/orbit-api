import uuid
from typing import Optional

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, joinedload

from app.models.membership import Membership, MembershipRole, role_at_least
from app.models.organization import Organization
from app.models.project import Project
from app.models.project_member import ProjectMember
from app.services.auth_service import get_user_by_email


class UserNotFoundError(Exception):
    pass


class AlreadyMemberError(Exception):
    pass


class LastOwnerError(Exception):
    pass


class InsufficientRoleError(Exception):
    pass


def get_membership(db: Session, org_id: uuid.UUID, user_id: uuid.UUID) -> Optional[Membership]:
    stmt = select(Membership).where(
        Membership.organization_id == org_id, Membership.user_id == user_id
    )
    return db.execute(stmt).scalar_one_or_none()


def get_membership_by_id(
    db: Session, org_id: uuid.UUID, membership_id: uuid.UUID
) -> Optional[Membership]:
    stmt = select(Membership).where(
        Membership.organization_id == org_id, Membership.id == membership_id
    )
    return db.execute(stmt).scalar_one_or_none()


def list_memberships(
    db: Session, org_id: uuid.UUID, *, limit: int = 50, offset: int = 0
) -> list[Membership]:
    stmt = (
        select(Membership)
        .options(joinedload(Membership.user))
        .where(Membership.organization_id == org_id)
        .order_by(Membership.created_at, Membership.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def count_owners(db: Session, org_id: uuid.UUID) -> int:
    stmt = select(func.count()).where(
        Membership.organization_id == org_id, Membership.role == MembershipRole.OWNER
    )
    return db.execute(stmt).scalar_one()


def add_member(
    db: Session,
    organization: Organization,
    email: str,
    role: MembershipRole,
    acting_role: MembershipRole,
) -> Membership:
    if not role_at_least(acting_role, role):
        raise InsufficientRoleError(
            f"Cannot add a member with a role higher than your own ({acting_role.value})"
        )

    user = get_user_by_email(db, email)
    if user is None:
        raise UserNotFoundError(f"No user is registered with email {email}")

    if get_membership(db, organization.id, user.id) is not None:
        raise AlreadyMemberError(f"{email} is already a member of this organization")

    membership = Membership(organization_id=organization.id, user_id=user.id, role=role)
    db.add(membership)
    db.commit()
    db.refresh(membership)
    return membership


def update_member_role(
    db: Session, membership: Membership, new_role: MembershipRole, acting_role: MembershipRole
) -> Membership:
    if not role_at_least(acting_role, new_role):
        raise InsufficientRoleError(
            f"Cannot grant a role higher than your own ({acting_role.value})"
        )

    if (
        membership.role == MembershipRole.OWNER
        and new_role != MembershipRole.OWNER
        and count_owners(db, membership.organization_id) <= 1
    ):
        raise LastOwnerError("Cannot demote the last remaining owner")

    membership.role = new_role
    db.commit()
    db.refresh(membership)
    return membership


def remove_member(db: Session, membership: Membership) -> None:
    if (
        membership.role == MembershipRole.OWNER
        and count_owners(db, membership.organization_id) <= 1
    ):
        raise LastOwnerError("Cannot remove the last remaining owner")

    # Project roles are scoped to a project, not to the org membership, so
    # nothing in the schema removes them when someone leaves. Left behind, they
    # silently reinstate the old project access the moment the user is re-added
    # to the organization. Clear them in the same transaction as the removal.
    org_project_ids = select(Project.id).where(
        Project.organization_id == membership.organization_id
    )
    db.execute(
        delete(ProjectMember).where(
            ProjectMember.user_id == membership.user_id,
            ProjectMember.project_id.in_(org_project_ids),
        )
    )

    db.delete(membership)
    db.commit()
