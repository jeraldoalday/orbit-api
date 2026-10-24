import uuid
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.fields import LabelNameStr

_COLOR_PATTERN = r"^#[0-9a-fA-F]{6}$"


class LabelCreate(BaseModel):
    name: LabelNameStr
    color: str = Field(default="#6b7280", pattern=_COLOR_PATTERN)


class LabelUpdate(BaseModel):
    name: Optional[LabelNameStr] = None
    color: Optional[str] = Field(default=None, pattern=_COLOR_PATTERN)


class LabelRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    name: str
    color: str
