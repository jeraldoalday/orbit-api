import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.models.project import ProjectVisibility
from app.schemas.fields import NameStr


class ProjectCreate(BaseModel):
    name: NameStr
    description: Optional[str] = None
    visibility: ProjectVisibility = ProjectVisibility.OPEN


class ProjectUpdate(BaseModel):
    name: Optional[NameStr] = None
    description: Optional[str] = None
    visibility: Optional[ProjectVisibility] = None


class ProjectRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    description: Optional[str]
    visibility: ProjectVisibility
    # Always present, and null for a live project — a client rendering the
    # recycle bin needs to know when something was deleted.
    deleted_at: Optional[datetime] = None
