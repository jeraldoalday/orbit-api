import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models.invitation import Invitation, InvitationStatus
from app.models.membership import Membership, MembershipRole, role_at_least
from app.models.organization import Organization
from app.models.user import User
from app.services.auth_service import get_user_by_email
from app.services.membership_service import AlreadyMemberError, get_membership

settings = get_settings()


class DuplicateInvitationError(Exception):
    pass


class InvalidInvitationError(Exception):
    pass


class ExpiredInvitationError(Exception):
    pass


class EmailMismatchError(Exception):
    pass


class InsufficientRoleError(Exception):
    pass


def _active_invitation_for_email(
    db: Session, org_id: uuid.UUID, email: str
) -> Optional[Invitation]:
    stmt = select(Invitation).where(
        Invitation.organization_id == org_id,
        Invitation.email == email,
        Invitation.status == InvitationStatus.PENDING,
        Invitation.expires_at > datetime.now(timezone.utc),
    )
    return db.execute(stmt).scalar_one_or_none()


def create_invitation(
    db: Session,
    organization: Organization,
    email: str,
    role: MembershipRole,
    invited_by: User,
    inviter_role: MembershipRole,
) -> Invitation:
    if not role_at_least(inviter_role, role):
        raise InsufficientRoleError(
            f"Cannot invite a member with a role higher than your own ({inviter_role.value})"
        )

    email = email.strip().lower()

    existing_user = get_user_by_email(db, email)
    if existing_user is not None and get_membership(db, organization.id, existing_user.id):
        raise AlreadyMemberError(f"{email} is already a member of this organization")

    if _active_invitation_for_email(db, organization.id, email) is not None:
        raise DuplicateInvitationError(f"An active invitation already exists for {email}")

    invitation = Invitation(
        organization_id=organization.id,
        email=email,
        role=role,
        token=secrets.token_urlsafe(32),
        invited_by_id=invited_by.id,
        expires_at=datetime.now(timezone.utc) + timedelta(days=settings.invite_expire_days),
    )
    db.add(invitation)
    db.commit()
    db.refresh(invitation)
    return invitation


def get_invitation_by_id(
    db: Session, org_id: uuid.UUID, invitation_id: uuid.UUID
) -> Optional[Invitation]:
    stmt = select(Invitation).where(
        Invitation.id == invitation_id, Invitation.organization_id == org_id
    )
    return db.execute(stmt).scalar_one_or_none()


def get_invitation_by_token(db: Session, token: str) -> Optional[Invitation]:
    stmt = select(Invitation).where(Invitation.token == token)
    return db.execute(stmt).scalar_one_or_none()


def list_invitations(db: Session, org_id: uuid.UUID) -> list[Invitation]:
    stmt = (
        select(Invitation)
        .where(Invitation.organization_id == org_id)
        .order_by(Invitation.created_at)
    )
    return list(db.execute(stmt).scalars().all())


def revoke_invitation(db: Session, invitation: Invitation) -> Invitation:
    if invitation.status != InvitationStatus.PENDING:
        raise InvalidInvitationError("Only a pending invitation can be revoked")

    invitation.status = InvitationStatus.REVOKED
    db.commit()
    db.refresh(invitation)
    return invitation


def accept_invitation(db: Session, invitation: Invitation, user: User) -> Membership:
    if invitation.status != InvitationStatus.PENDING:
        raise InvalidInvitationError("This invitation is no longer pending")

    expires_at = invitation.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc):
        raise ExpiredInvitationError("This invitation has expired")

    if invitation.email.lower() != user.email.lower():
        raise EmailMismatchError("This invitation was issued to a different email address")

    if get_membership(db, invitation.organization_id, user.id) is not None:
        raise AlreadyMemberError("You are already a member of this organization")

    membership = Membership(
        organization_id=invitation.organization_id, user_id=user.id, role=invitation.role
    )
    db.add(membership)

    invitation.status = InvitationStatus.ACCEPTED
    invitation.accepted_by_id = user.id

    db.commit()
    db.refresh(membership)
    return membership
