import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.project import ProjectVisibility


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: Optional[str] = None
    visibility: ProjectVisibility = ProjectVisibility.OPEN


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)
    description: Optional[str] = None
    visibility: Optional[ProjectVisibility] = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: Optional[str]
    visibility: ProjectVisibility
