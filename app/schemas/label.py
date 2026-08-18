import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.fields import LabelNameStr


class LabelCreate(BaseModel):
    name: LabelNameStr
    color: str = Field(default="#6b7280", pattern=r"^#[0-9a-fA-F]{6}$")


class LabelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    color: str
