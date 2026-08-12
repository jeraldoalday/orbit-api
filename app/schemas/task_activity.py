import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from app.models.task_activity import TaskActivityType


class TaskActivityRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    actor_id: Optional[uuid.UUID]
    activity_type: TaskActivityType
    data: Optional[dict[str, Any]]
    created_at: datetime
