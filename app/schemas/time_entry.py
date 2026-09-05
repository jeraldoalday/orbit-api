import uuid
from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.user import UserRead

# A single entry is one person's day at most. Anything larger is a typo — the
# extra zero on "600 minutes" — and a typo that lands in a report is worse
# than one that is refused.
MAX_ENTRY_MINUTES = 24 * 60


class TimeEntryCreate(BaseModel):
    minutes: int = Field(ge=1, le=MAX_ENTRY_MINUTES)
    # Defaults to today where it is applied, so a client that just wants to
    # log "an hour, now" sends one field.
    spent_on: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=200)


class TimeEntryUpdate(BaseModel):
    minutes: Optional[int] = Field(default=None, ge=1, le=MAX_ENTRY_MINUTES)
    spent_on: Optional[date] = None
    note: Optional[str] = Field(default=None, max_length=200)


class TimeEntryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    task_id: uuid.UUID
    user: Optional[UserRead]
    minutes: int
    spent_on: date
    note: Optional[str]
    created_at: datetime


class TaskTimeSummary(BaseModel):
    """What a task has cost so far, against what it was expected to."""

    task_id: uuid.UUID
    logged_minutes: int
    estimate_minutes: Optional[int]
    # None when there is no estimate to be remaining against, and floored at
    # zero once the estimate is passed: "-120 minutes remaining" is a way of
    # saying "over", and `over_estimate` says it better.
    remaining_minutes: Optional[int]
    over_estimate: bool
    entries: list[TimeEntryRead]


class TimeTotal(BaseModel):
    """Minutes logged by one person, or against one task."""

    id: Optional[uuid.UUID]
    label: Optional[str]
    minutes: int


class ProjectTimeReport(BaseModel):
    project_id: uuid.UUID
    # Echoed back so a report can be read without the request beside it.
    spent_from: Optional[date]
    spent_to: Optional[date]
    logged_minutes: int
    # Summed over live tasks that carry one, so the comparison with
    # logged_minutes is between the same set of tasks.
    estimated_minutes: int
    by_user: list[TimeTotal]
    by_task: list[TimeTotal]
