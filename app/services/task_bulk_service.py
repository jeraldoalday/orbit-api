"""Applying one edit to many tasks.

Every task still goes through `update_task`, one at a time, rather than a
single UPDATE statement. A bulk edit that skipped the service would also skip
the timeline entry, the assignment notification, the webhook and the blocker
gate — and a task edited in bulk would quietly have a different history from
the same task edited on its own.

One consequence worth knowing: the batch is applied in the order it is given,
so closing a dependency chain in one call works if the blockers come first and
leaves the rest reported as blocked if they don't. Reordering the batch behind
the caller's back would be worse — a per-task report you can't line up against
what you sent is not much of a report.
"""

import uuid
from typing import Optional

from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.task import Task
from app.models.user import User
from app.schemas.task import TaskUpdate
from app.schemas.task_bulk import BulkTaskFailure, BulkTaskResult
from app.services.task_service import (
    AssigneeNotMemberError,
    MilestoneNotInProjectError,
    TaskBlockedError,
    check_assignee_access,
    check_milestone,
    get_task,
    soft_delete_task,
    update_task,
)

TASK_NOT_FOUND = "Task not found"


def _unique(task_ids: list[uuid.UUID]) -> list[uuid.UUID]:
    """Drop repeats but keep the caller's order, so the report reads back."""
    seen: dict[uuid.UUID, None] = {}
    for task_id in task_ids:
        seen.setdefault(task_id, None)
    return list(seen)


def _snapshot(task: Task) -> tuple:
    """The fields a bulk edit can move, for telling a real change from a no-op."""
    return (task.status, task.priority, task.assignee_id, task.milestone_id, task.due_date)


def bulk_update_tasks(
    db: Session,
    project: Project,
    task_ids: list[uuid.UUID],
    changes: dict,
    actor: Optional[User] = None,
) -> BulkTaskResult:
    task_in = TaskUpdate(**changes)

    # A bad assignee is wrong for the request, not for one task in it, so it
    # fails the call outright instead of producing an identical failure row
    # for every task in the batch.
    if task_in.assignee_id is not None:
        check_assignee_access(db, project, task_in.assignee_id)
    # Same reasoning for the milestone: a foreign one is wrong for the whole
    # request, not for one task in it.
    if task_in.milestone_id is not None:
        check_milestone(db, project, task_in.milestone_id)

    updated: list[uuid.UUID] = []
    unchanged: list[uuid.UUID] = []
    failed: list[BulkTaskFailure] = []

    for task_id in _unique(task_ids):
        task = get_task(db, project.id, task_id)
        if task is None:
            failed.append(BulkTaskFailure(task_id=task_id, reason=TASK_NOT_FOUND))
            continue

        before = _snapshot(task)
        try:
            update_task(db, project, task, task_in, actor)
        except (TaskBlockedError, AssigneeNotMemberError, MilestoneNotInProjectError) as exc:
            # One task refusing the edit says nothing about the next one, so
            # the loop carries on and the caller is told which fell out.
            failed.append(BulkTaskFailure(task_id=task_id, reason=str(exc)))
            continue

        (updated if _snapshot(task) != before else unchanged).append(task_id)

    return BulkTaskResult(updated=updated, unchanged=unchanged, failed=failed)


def bulk_delete_tasks(
    db: Session,
    project: Project,
    task_ids: list[uuid.UUID],
    actor: Optional[User] = None,
) -> BulkTaskResult:
    """Soft-delete many tasks, reporting the ones that were already gone."""
    updated: list[uuid.UUID] = []
    failed: list[BulkTaskFailure] = []

    for task_id in _unique(task_ids):
        task = get_task(db, project.id, task_id)
        if task is None:
            # Already deleted reads as not found here, exactly as it does on
            # the single-task route: a second delete is not a new event.
            failed.append(BulkTaskFailure(task_id=task_id, reason=TASK_NOT_FOUND))
            continue
        soft_delete_task(db, project, task, actor)
        updated.append(task_id)

    return BulkTaskResult(updated=updated, unchanged=[], failed=failed)
