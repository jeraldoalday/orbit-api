import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.models.task import TaskPriority, TaskStatus
from app.schemas.fields import NameStr

# A thousand hours on one task. Past this the number is a typo, and an
# estimate nobody can hit is worse than no estimate at all.
MAX_ESTIMATE_MINUTES = 1000 * 60


class TaskCreate(BaseModel):
    title: NameStr
    description: Optional[str] = None
    assignee_id: Optional[uuid.UUID] = None
    milestone_id: Optional[uuid.UUID] = None
    priority: TaskPriority = TaskPriority.MEDIUM
    due_date: Optional[datetime] = None
    estimate_minutes: Optional[int] = Field(default=None, ge=1, le=MAX_ESTIMATE_MINUTES)


class TaskUpdate(BaseModel):
    title: Optional[NameStr] = None
    description: Optional[str] = None
    status: Optional[TaskStatus] = None
    assignee_id: Optional[uuid.UUID] = None
    # Explicit null detaches the task from its milestone; omitting the field
    # leaves it where it is, as everywhere else in this PATCH.
    milestone_id: Optional[uuid.UUID] = None
    priority: Optional[TaskPriority] = None
    due_date: Optional[datetime] = None
    estimate_minutes: Optional[int] = Field(default=None, ge=1, le=MAX_ESTIMATE_MINUTES)


class TaskRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    title: str
    description: Optional[str]
    status: TaskStatus
    assignee_id: Optional[uuid.UUID]
    milestone_id: Optional[uuid.UUID] = None
    priority: TaskPriority
    due_date: Optional[datetime]
    estimate_minutes: Optional[int] = None
    deleted_at: Optional[datetime] = None
