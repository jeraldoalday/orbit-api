import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.fields import NameStr


class OrganizationCreate(BaseModel):
    name: NameStr


class OrganizationUpdate(BaseModel):
    name: Optional[NameStr] = None


class OrganizationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
