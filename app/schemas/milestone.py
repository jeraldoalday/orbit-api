import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.fields import NameStr


class MilestoneCreate(BaseModel):
    name: NameStr
    description: Optional[str] = None
    due_date: Optional[datetime] = None


class MilestoneUpdate(BaseModel):
    name: Optional[NameStr] = None
    description: Optional[str] = None
    due_date: Optional[datetime] = None


class MilestoneProgress(BaseModel):
    """How much of a milestone's work is finished.

    Counted from live tasks only: a soft-deleted task has been taken out of
    the project, and leaving it in the denominator would make a milestone
    look permanently unfinishable.
    """

    total: int
    done: int
    open: int
    # 0.0 for a milestone with no tasks yet, matching the task statistics:
    # an empty milestone is 0% done, not unknown.
    completion_rate: float


class MilestoneRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    name: str
    description: Optional[str]
    due_date: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime


class MilestoneDetail(MilestoneRead):
    """A milestone with the counts a board renders beside its name."""

    progress: MilestoneProgress
