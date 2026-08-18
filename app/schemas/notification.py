import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from app.models.notification import NotificationType
from app.schemas.user import UserRead


class NotificationRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    task_id: Optional[uuid.UUID]
    notification_type: NotificationType
    actor: Optional[UserRead]
    data: Optional[dict[str, Any]]
    read_at: Optional[datetime]
    is_read: bool
    created_at: datetime


class UnreadCount(BaseModel):
    unread: int


class MarkAllReadResult(BaseModel):
    marked: int
