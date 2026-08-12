import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_organization_or_404, require_org_role
from app.db.session import get_db
from app.models.invitation import Invitation
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.user import User
from app.schemas.invitation import (
    InvitationAccept,
    InvitationCreate,
    InvitationCreateResponse,
    InvitationRead,
)
from app.schemas.membership import MembershipRead
from app.services.invitation_service import (
    AlreadyMemberError,
    DuplicateInvitationError,
    EmailMismatchError,
    ExpiredInvitationError,
    InvalidInvitationError,
    accept_invitation,
    create_invitation,
    get_invitation_by_id,
    get_invitation_by_token,
    list_invitations,
    revoke_invitation,
)

router = APIRouter(prefix="/organizations/{org_id}/invitations", tags=["invitations"])
accept_router = APIRouter(prefix="/invitations", tags=["invitations"])


def _get_invitation_or_404(
    db: Session, organization: Organization, invitation_id: uuid.UUID
) -> Invitation:
    invitation = get_invitation_by_id(db, organization.id, invitation_id)
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")
    return invitation


@router.post("", response_model=InvitationCreateResponse, status_code=status.HTTP_201_CREATED)
def create(
    invitation_in: InvitationCreate,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    membership: Membership = Depends(require_org_role(MembershipRole.ADMIN)),
) -> InvitationCreateResponse:
    try:
        return create_invitation(
            db, organization, invitation_in.email, invitation_in.role, membership.user
        )
    except AlreadyMemberError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except DuplicateInvitationError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("", response_model=list[InvitationRead])
def list_mine(
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.ADMIN)),
) -> list[InvitationRead]:
    return list_invitations(db, organization.id)


@router.delete("/{invitation_id}", status_code=status.HTTP_204_NO_CONTENT)
def revoke(
    invitation_id: uuid.UUID,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.ADMIN)),
) -> None:
    invitation = _get_invitation_or_404(db, organization, invitation_id)
    revoke_invitation(db, invitation)


@accept_router.post("/accept", response_model=MembershipRead)
def accept(
    body: InvitationAccept,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> MembershipRead:
    invitation = get_invitation_by_token(db, body.token)
    if invitation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Invitation not found")

    try:
        return accept_invitation(db, invitation, current_user)
    except (InvalidInvitationError, ExpiredInvitationError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except EmailMismatchError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except AlreadyMemberError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
