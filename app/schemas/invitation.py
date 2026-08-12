import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

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


class InvitationCreateResponse(InvitationRead):
    token: str


class InvitationAccept(BaseModel):
    token: str
