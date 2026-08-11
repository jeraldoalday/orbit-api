import uuid

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.membership import MembershipRole
from app.schemas.user import UserRead


class MembershipCreate(BaseModel):
    email: EmailStr
    role: MembershipRole = MembershipRole.MEMBER


class MembershipRoleUpdate(BaseModel):
    role: MembershipRole


class MembershipRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    role: MembershipRole
    user: UserRead
