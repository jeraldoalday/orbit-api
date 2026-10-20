import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, EmailStr, model_validator

from app.models.invitation import InvitationStatus
from app.models.membership import MembershipRole


class InvitationCreate(BaseModel):
    email: EmailStr
    role: MembershipRole = MembershipRole.MEMBER


class InvitationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    email: EmailStr
    role: MembershipRole
    status: InvitationStatus
    expires_at: datetime
    created_at: datetime

    @model_validator(mode="after")
    def _expire_pending(self) -> "InvitationRead":
        """Report a lapsed invitation as expired rather than repeating the
        stored "pending" it never moves off on its own.

        `accept_invitation` already refuses a pending invitation past its
        `expires_at`; without this, a caller listing invitations has no way
        to tell such a row apart from one that can still be accepted.
        """
        if self.status != InvitationStatus.PENDING:
            return self

        expires_at = self.expires_at
        if expires_at.tzinfo is None:
            # SQLite (used in tests) drops the timezone on the way back out.
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if expires_at <= datetime.now(timezone.utc):
            self.status = InvitationStatus.EXPIRED
        return self


class InvitationCreateResponse(InvitationRead):
    token: str


class InvitationAccept(BaseModel):
    token: str
