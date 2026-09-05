"""Exporting a project's tasks as CSV.

Rows are generated one at a time and written into a reusable in-memory buffer
rather than assembled into one string: an export is the request most likely to
be large, and the point of streaming it is that the whole file never exists at
once. The related counts — labels, logged minutes — are fetched up front in
one query each, because doing them per row is the N+1 that would make a five
thousand row export slower than the report it replaces.
"""

import csv
import io
import uuid
from collections.abc import Iterator
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.slug import slugify
from app.models.label import Label
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.task import TaskPriority, TaskStatus
from app.models.task_label import TaskLabel
from app.models.time_entry import TimeEntry
from app.models.user import User
from app.services.task_service import list_tasks

CSV_COLUMNS = [
    "id",
    "title",
    "description",
    "status",
    "priority",
    "assignee_email",
    "milestone",
    "labels",
    "due_date",
    "estimate_minutes",
    "logged_minutes",
    "created_at",
]

# A spreadsheet treats a cell starting with one of these as a formula, so a
# task titled "=1+1" — or something considerably less friendly — becomes code
# the moment somebody opens the file. Prefixing with an apostrophe is the
# standard defusal and keeps the text readable.
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _defuse(value: str) -> str:
    if value and value[0] in _FORMULA_PREFIXES:
        return f"'{value}"
    return value


def _cell(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return _defuse(str(value))


def export_filename(project: Project) -> str:
    """A filename that says which project it came from, safe for a header."""
    return f"{slugify(project.name)}-tasks.csv"


def _labels_by_task(db: Session, task_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[str]]:
    if not task_ids:
        return {}
    stmt = (
        select(TaskLabel.task_id, Label.name)
        .join(Label, Label.id == TaskLabel.label_id)
        .where(TaskLabel.task_id.in_(task_ids))
        .order_by(Label.name)
    )
    grouped: dict[uuid.UUID, list[str]] = {}
    for task_id, name in db.execute(stmt).all():
        grouped.setdefault(task_id, []).append(name)
    return grouped


def _minutes_by_task(db: Session, task_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not task_ids:
        return {}
    stmt = (
        select(TimeEntry.task_id, func.sum(TimeEntry.minutes))
        .where(TimeEntry.task_id.in_(task_ids))
        .group_by(TimeEntry.task_id)
    )
    return {row[0]: int(row[1] or 0) for row in db.execute(stmt).all()}


def _names_by_id(db: Session, model, column, ids: set) -> dict:
    if not ids:
        return {}
    stmt = select(model.id, column).where(model.id.in_(ids))
    return {row[0]: row[1] for row in db.execute(stmt).all()}


def task_rows(
    db: Session,
    project: Project,
    *,
    status: Optional[TaskStatus] = None,
    assignee_id: Optional[uuid.UUID] = None,
    priority: Optional[TaskPriority] = None,
    milestone_id: Optional[uuid.UUID] = None,
    label_id: Optional[uuid.UUID] = None,
    limit: int = 5000,
) -> list[list[str]]:
    """The export's data rows, in the order the task list would show them.

    Deliberately the same filters the task list takes: an export that can't
    reproduce what is on screen sends people back to copying rows by hand.
    """
    tasks = list_tasks(
        db,
        project.id,
        status=status,
        assignee_id=assignee_id,
        priority=priority,
        milestone_id=milestone_id,
        label_id=label_id,
        sort_by="created_at",
        order="asc",
        limit=limit,
    )

    task_ids = [task.id for task in tasks]
    labels = _labels_by_task(db, task_ids)
    minutes = _minutes_by_task(db, task_ids)
    assignees = _names_by_id(
        db, User, User.email, {task.assignee_id for task in tasks if task.assignee_id}
    )
    milestones = _names_by_id(
        db, Milestone, Milestone.name, {task.milestone_id for task in tasks if task.milestone_id}
    )

    return [
        [
            _cell(task.id),
            _cell(task.title),
            _cell(task.description),
            _cell(task.status.value),
            _cell(task.priority.value),
            _cell(assignees.get(task.assignee_id)),
            _cell(milestones.get(task.milestone_id)),
            _cell(", ".join(labels.get(task.id, []))),
            _cell(task.due_date),
            _cell(task.estimate_minutes),
            _cell(minutes.get(task.id, 0)),
            _cell(task.created_at),
        ]
        for task in tasks
    ]


def stream_csv(rows: list[list[str]]) -> Iterator[str]:
    """Yield the header and then one chunk per row.

    `csv.writer` handles the quoting a hand-rolled join gets wrong the first
    time a description contains a comma, a quote or a newline.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)

    def flush() -> str:
        value = buffer.getvalue()
        buffer.seek(0)
        buffer.truncate(0)
        return value

    writer.writerow(CSV_COLUMNS)
    yield flush()

    for row in rows:
        writer.writerow(row)
        yield flush()
