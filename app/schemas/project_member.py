import uuid

from pydantic import BaseModel, ConfigDict, EmailStr

from app.models.project_member import ProjectRole
from app.schemas.user import UserRead


class ProjectMemberCreate(BaseModel):
    email: EmailStr
    role: ProjectRole = ProjectRole.EDITOR


class ProjectMemberRoleUpdate(BaseModel):
    role: ProjectRole


class ProjectMemberRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    role: ProjectRole
    user: UserRead
