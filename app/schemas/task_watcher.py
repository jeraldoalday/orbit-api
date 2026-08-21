import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr

from app.schemas.user import UserRead


class WatcherCreate(BaseModel):
    """Whom to add. Omitted means the caller themselves, which is the case a
    "Watch" button sends and the only one a plain viewer is allowed."""

    email: EmailStr


class TaskWatcherRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    user: UserRead
    created_at: datetime
