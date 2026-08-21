import uuid
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.models.task import TaskPriority, TaskStatus

# The fields a bulk edit may set. Kept as an explicit tuple so the "did you ask
# for anything?" check can't drift out of step with the model.
_MUTABLE_FIELDS = ("status", "priority", "assignee_id", "due_date")


class BulkTaskUpdate(BaseModel):
    """One edit applied to many tasks in the same project.

    Title and description are deliberately absent: writing the same title to
    fifty tasks is never what anyone meant, and an endpoint that allows it
    turns a mis-click into fifty rows to clean up.
    """

    task_ids: list[uuid.UUID] = Field(min_length=1)
    status: Optional[TaskStatus] = None
    priority: Optional[TaskPriority] = None
    assignee_id: Optional[uuid.UUID] = None
    due_date: Optional[datetime] = None

    @model_validator(mode="after")
    def _requires_a_change(self) -> "BulkTaskUpdate":
        fields_set = self.model_fields_set
        if not any(field in fields_set for field in _MUTABLE_FIELDS):
            raise ValueError("Specify at least one field to change")
        return self

    def as_changes(self) -> dict:
        """The requested edit, with omitted fields left out.

        `assignee_id` and `due_date` are nullable, so an explicit null has to
        stay distinguishable from an absent key — the first clears the field,
        the second leaves it alone.
        """
        return {
            field: getattr(self, field)
            for field in _MUTABLE_FIELDS
            if field in self.model_fields_set
        }


class BulkTaskDelete(BaseModel):
    task_ids: list[uuid.UUID] = Field(min_length=1)


class BulkTaskFailure(BaseModel):
    task_id: uuid.UUID
    reason: str


class BulkTaskResult(BaseModel):
    """What happened to each task, rather than one verdict for the batch.

    A bulk edit over a selection routinely includes something that can't take
    it — a task another user just deleted, one held by an open blocker. Failing
    the whole request would make the endpoint useless exactly when it is most
    useful, so each task is reported on individually.
    """

    updated: list[uuid.UUID]
    # Reached and allowed, but the edit was already its value: worth telling
    # apart from `updated` so a caller can see nothing actually moved.
    unchanged: list[uuid.UUID]
    failed: list[BulkTaskFailure]

    @property
    def total(self) -> int:
        return len(self.updated) + len(self.unchanged) + len(self.failed)
