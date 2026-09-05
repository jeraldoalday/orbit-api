import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict

from app.schemas.fields import NameStr


class ChecklistItemCreate(BaseModel):
    content: NameStr


class ChecklistItemUpdate(BaseModel):
    """Either half may move on its own: renaming a step is not ticking it."""

    content: Optional[NameStr] = None
    is_done: Optional[bool] = None


class ChecklistReorder(BaseModel):
    """The task's items, in the order they should end up.

    The whole list, not a move instruction: a client that has just dragged a
    row already knows the resulting order, and sending it whole means the
    server never has to reconcile two clients' idea of "position 3".
    """

    item_ids: list[uuid.UUID]


class ChecklistItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    content: str
    is_done: bool
    position: int
    created_at: datetime


class ChecklistRead(BaseModel):
    """The list plus the progress a client would otherwise recompute."""

    items: list[ChecklistItemRead]
    total: int
    done: int
    # Fraction ticked, 0.0 for an empty checklist rather than null, and rounded
    # the same way the task statistics round their completion rate.
    completion_rate: float
