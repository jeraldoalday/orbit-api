import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.user import UserRead


class TaskCommentCreate(BaseModel):
    body: str = Field(min_length=1, max_length=5000)


class TaskCommentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    author: Optional[UserRead]
    body: str
    created_at: datetime
