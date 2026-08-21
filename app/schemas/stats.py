import uuid
from typing import Optional

from pydantic import BaseModel


class TaskStats(BaseModel):
    """Counts over a set of tasks, whatever selected the set."""

    total: int
    # Keyed by the enum's wire values, with every member present at zero if
    # unused, so a client never has to guess whether a missing key means "none"
    # or "this column changed shape".
    by_status: dict[str, int]
    by_priority: dict[str, int]
    done: int
    # Fraction of the set that is done, 0.0 for an empty set rather than null:
    # an empty project is 0% complete, not unknown.
    completion_rate: float
    overdue: int
    due_soon: int
    unassigned: int
    # Open tasks held by at least one unfinished dependency.
    blocked: int


class AssigneeStats(BaseModel):
    # Null for the unassigned bucket, which is deliberately part of the
    # breakdown rather than missing from it: the rows have to add up to total.
    assignee_id: Optional[uuid.UUID]
    email: Optional[str]
    total: int
    done: int


class ProjectSummary(BaseModel):
    project_id: uuid.UUID
    name: str
    total: int
    done: int


class ProjectStats(BaseModel):
    project_id: uuid.UUID
    name: str
    tasks: TaskStats
    by_assignee: list[AssigneeStats]


class OrganizationStats(BaseModel):
    organization_id: uuid.UUID
    projects: int
    tasks: TaskStats
    by_assignee: list[AssigneeStats]
    per_project: list[ProjectSummary]
