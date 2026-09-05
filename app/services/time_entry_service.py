"""Logged work: minutes against a task, and the reports that add them up.

Sums are computed by the database. A project report over a quarter would
otherwise load every entry in it to add five numbers, and that report is the
one somebody runs on the last day of the month for the whole team at once.
"""

import uuid
from datetime import date, datetime, timezone
from typing import Optional

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session, joinedload

from app.models.task import Task
from app.models.time_entry import TimeEntry
from app.models.user import User
from app.schemas.time_entry import (
    ProjectTimeReport,
    TaskTimeSummary,
    TimeEntryRead,
    TimeEntryUpdate,
    TimeTotal,
)


class FutureTimeEntryError(Exception):
    """Raised when work is logged against a day that hasn't happened."""


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _check_spent_on(spent_on: date) -> None:
    # A date in the future is either a typo or a forecast; neither belongs in a
    # record of work that was done. Today is judged in UTC, which can be a few
    # hours behind a caller east of it — logging tomorrow's date is refused for
    # those few hours, which is the safe direction to be wrong in.
    if spent_on > _today():
        raise FutureTimeEntryError("Work cannot be logged against a future date")


def list_entries(db: Session, task_id: uuid.UUID) -> list[TimeEntry]:
    """A task's entries, most recent day first."""
    stmt = (
        select(TimeEntry)
        .options(joinedload(TimeEntry.user))
        .where(TimeEntry.task_id == task_id)
        .order_by(TimeEntry.spent_on.desc(), TimeEntry.created_at.desc(), TimeEntry.id)
    )
    return list(db.execute(stmt).scalars().all())


def get_entry(db: Session, task_id: uuid.UUID, entry_id: uuid.UUID) -> Optional[TimeEntry]:
    stmt = select(TimeEntry).where(TimeEntry.id == entry_id, TimeEntry.task_id == task_id)
    return db.execute(stmt).scalar_one_or_none()


def logged_minutes(db: Session, task_id: uuid.UUID) -> int:
    stmt = select(func.coalesce(func.sum(TimeEntry.minutes), 0)).where(TimeEntry.task_id == task_id)
    return int(db.execute(stmt).scalar_one())


def log_time(
    db: Session,
    task: Task,
    user: User,
    minutes: int,
    *,
    spent_on: Optional[date] = None,
    note: Optional[str] = None,
) -> TimeEntry:
    day = spent_on or _today()
    _check_spent_on(day)

    entry = TimeEntry(task_id=task.id, user_id=user.id, minutes=minutes, spent_on=day, note=note)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def update_entry(db: Session, entry: TimeEntry, changes: TimeEntryUpdate) -> TimeEntry:
    fields = changes.model_dump(exclude_unset=True)
    if fields.get("spent_on") is not None:
        _check_spent_on(fields["spent_on"])

    for field, value in fields.items():
        # `spent_on` and `minutes` have no null meaning, so an explicit null is
        # a no-op rather than a way to blank a required column. `note` does
        # clear, which is why this looks at the value rather than the key.
        if value is None and field != "note":
            continue
        setattr(entry, field, value)

    db.commit()
    db.refresh(entry)
    return entry


def delete_entry(db: Session, entry: TimeEntry) -> None:
    db.delete(entry)
    db.commit()


def task_summary(db: Session, task: Task) -> TaskTimeSummary:
    entries = list_entries(db, task.id)
    logged = sum(entry.minutes for entry in entries)
    estimate = task.estimate_minutes

    return TaskTimeSummary(
        task_id=task.id,
        logged_minutes=logged,
        estimate_minutes=estimate,
        remaining_minutes=max(estimate - logged, 0) if estimate is not None else None,
        over_estimate=estimate is not None and logged > estimate,
        entries=[TimeEntryRead.model_validate(entry) for entry in entries],
    )


def _range_conditions(spent_from: Optional[date], spent_to: Optional[date]) -> list[ColumnElement]:
    conditions: list[ColumnElement] = []
    if spent_from is not None:
        conditions.append(TimeEntry.spent_on >= spent_from)
    if spent_to is not None:
        conditions.append(TimeEntry.spent_on <= spent_to)
    return conditions


def project_report(
    db: Session,
    project_id: uuid.UUID,
    *,
    spent_from: Optional[date] = None,
    spent_to: Optional[date] = None,
) -> ProjectTimeReport:
    """Minutes logged in a project, broken down by person and by task.

    Entries on soft-deleted tasks are left out, so the report describes the
    project as it currently stands rather than as it was before a clean-up.
    """
    scope: list[ColumnElement] = [
        Task.project_id == project_id,
        Task.deleted_at.is_(None),
        *_range_conditions(spent_from, spent_to),
    ]

    by_user_stmt = (
        select(TimeEntry.user_id, User.email, func.sum(TimeEntry.minutes))
        .select_from(TimeEntry)
        .join(Task, Task.id == TimeEntry.task_id)
        # Outer, so entries whose author has since been removed still count
        # towards the total instead of vanishing from the breakdown.
        .outerjoin(User, User.id == TimeEntry.user_id)
        .where(*scope)
        .group_by(TimeEntry.user_id, User.email)
        .order_by(func.sum(TimeEntry.minutes).desc(), User.email)
    )
    by_task_stmt = (
        select(Task.id, Task.title, func.sum(TimeEntry.minutes))
        .select_from(TimeEntry)
        .join(Task, Task.id == TimeEntry.task_id)
        .where(*scope)
        .group_by(Task.id, Task.title)
        .order_by(func.sum(TimeEntry.minutes).desc(), Task.title)
    )
    estimate_stmt = (
        select(func.coalesce(func.sum(Task.estimate_minutes), 0))
        .select_from(Task)
        .where(Task.project_id == project_id, Task.deleted_at.is_(None))
    )

    by_user = [
        TimeTotal(id=row[0], label=row[1], minutes=int(row[2] or 0))
        for row in db.execute(by_user_stmt).all()
    ]
    by_task = [
        TimeTotal(id=row[0], label=row[1], minutes=int(row[2] or 0))
        for row in db.execute(by_task_stmt).all()
    ]

    return ProjectTimeReport(
        project_id=project_id,
        spent_from=spent_from,
        spent_to=spent_to,
        # Summed from the per-task rows rather than with a third aggregate
        # query: two numbers that are supposed to agree should not have two
        # chances to disagree.
        logged_minutes=sum(total.minutes for total in by_task),
        estimated_minutes=int(db.execute(estimate_stmt).scalar_one()),
        by_user=by_user,
        by_task=by_task,
    )
