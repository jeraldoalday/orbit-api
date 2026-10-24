import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.fields import BodyStr
from app.schemas.user import UserRead


class TaskCommentCreate(BaseModel):
    body: BodyStr


class TaskCommentUpdate(BaseModel):
    body: BodyStr


class TaskCommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    author: Optional[UserRead]
    body: str
    created_at: datetime
    # Moves only when the body is edited; there is no separate "edited" flag,
    # so a client compares the two to show one.
    updated_at: datetime
