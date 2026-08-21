import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.user import UserRead


class AttachmentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    uploaded_by: Optional[UserRead]
    created_at: datetime


class AttachmentQuota(BaseModel):
    """What a client needs to validate an upload before attempting it.

    Both budgets are reported, because either can be the one that stops the
    next upload: a task can be well under its file count and still out of
    bytes.
    """

    max_bytes: int
    max_per_task: int
    used: int
    remaining: int
    max_total_bytes: int
    used_bytes: int
    remaining_bytes: int
