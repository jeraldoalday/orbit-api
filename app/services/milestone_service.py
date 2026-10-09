"""Milestones: dated goals a project's tasks are grouped under.

Progress is counted in the database, in one grouped query for a whole list
rather than one query per milestone — a project page renders every milestone
at once, and that is exactly the request that turns into N+1 otherwise.
"""

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.core.progress import completion_rate
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.schemas.milestone import (
    MilestoneCreate,
    MilestoneDetail,
    MilestoneProgress,
    MilestoneRead,
    MilestoneUpdate,
)


class MilestoneHasOpenTasksError(Exception):
    """Raised when a milestone is completed with unfinished work under it."""

    def __init__(self, open_tasks: int) -> None:
        self.open_tasks = open_tasks
        super().__init__(f"{open_tasks} task(s) under this milestone are still open")


class MilestoneAlreadyCompletedError(Exception):
    pass


class MilestoneNotCompletedError(Exception):
    pass


def _empty_progress() -> MilestoneProgress:
    return MilestoneProgress(total=0, done=0, open=0, completion_rate=0.0)


def _progress(total: int, done: int) -> MilestoneProgress:
    return MilestoneProgress(
        total=total,
        done=done,
        open=total - done,
        completion_rate=completion_rate(done, total),
    )


def get_milestone(
    db: Session, project_id: uuid.UUID, milestone_id: uuid.UUID
) -> Optional[Milestone]:
    stmt = select(Milestone).where(Milestone.id == milestone_id, Milestone.project_id == project_id)
    return db.execute(stmt).scalar_one_or_none()


def _progress_by_milestone(
    db: Session, milestone_ids: list[uuid.UUID]
) -> dict[uuid.UUID, MilestoneProgress]:
    """Live task counts for several milestones at once."""
    if not milestone_ids:
        return {}

    done_count = func.sum(case((Task.status == TaskStatus.DONE, 1), else_=0))
    stmt = (
        select(Task.milestone_id, func.count(), done_count)
        .where(Task.milestone_id.in_(milestone_ids), Task.deleted_at.is_(None))
        .group_by(Task.milestone_id)
    )
    return {row[0]: _progress(row[1], int(row[2] or 0)) for row in db.execute(stmt).all()}


def open_task_count(db: Session, milestone_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(Task)
        .where(
            Task.milestone_id == milestone_id,
            Task.deleted_at.is_(None),
            Task.status != TaskStatus.DONE,
        )
    )
    return db.execute(stmt).scalar_one()


def list_milestones(
    db: Session, project_id: uuid.UUID, *, include_completed: bool = True
) -> list[MilestoneDetail]:
    """A project's milestones, soonest due first, each with its progress.

    Undated milestones sort last rather than first: a date is a commitment and
    the ones carrying it are what a plan is read for.
    """
    stmt = select(Milestone).where(Milestone.project_id == project_id)
    if not include_completed:
        stmt = stmt.where(Milestone.completed_at.is_(None))
    stmt = stmt.order_by(
        Milestone.due_date.is_(None), Milestone.due_date, Milestone.name, Milestone.id
    )
    milestones = list(db.execute(stmt).scalars().all())

    progress = _progress_by_milestone(db, [milestone.id for milestone in milestones])
    return [
        _detail(milestone, progress.get(milestone.id, _empty_progress()))
        for milestone in milestones
    ]


def _detail(milestone: Milestone, progress: MilestoneProgress) -> MilestoneDetail:
    return MilestoneDetail(
        **MilestoneRead.model_validate(milestone).model_dump(), progress=progress
    )


def milestone_detail(db: Session, milestone: Milestone) -> MilestoneDetail:
    progress = _progress_by_milestone(db, [milestone.id])
    return _detail(milestone, progress.get(milestone.id, _empty_progress()))


def create_milestone(db: Session, project: Project, milestone_in: MilestoneCreate) -> Milestone:
    milestone = Milestone(
        project_id=project.id,
        name=milestone_in.name,
        description=milestone_in.description,
        due_date=milestone_in.due_date,
    )
    db.add(milestone)
    db.commit()
    db.refresh(milestone)
    return milestone


def update_milestone(db: Session, milestone: Milestone, changes: MilestoneUpdate) -> Milestone:
    # `name` has no null meaning, so an explicit null is a no-op rather than an
    # attempt to blank a NOT NULL column (the same convention `update_project`
    # and `update_task` follow). `description` and `due_date` are nullable, so
    # they're checked against what was actually sent instead.
    fields_set = changes.model_fields_set

    if changes.name is not None:
        milestone.name = changes.name
    if "description" in fields_set:
        milestone.description = changes.description
    if "due_date" in fields_set:
        milestone.due_date = changes.due_date

    db.commit()
    db.refresh(milestone)
    return milestone


def complete_milestone(db: Session, milestone: Milestone, *, force: bool = False) -> Milestone:
    """Close a milestone, refusing by default while work under it is open.

    The same gate the dependency graph puts on a task: a plan that can be
    marked shipped with six open tasks under it is a plan nobody trusts. It is
    a refusal rather than a rule, though — `force` exists because deciding to
    cut scope is a real answer, and the alternative is closing the tasks with
    a lie about them being done.
    """
    if milestone.completed_at is not None:
        raise MilestoneAlreadyCompletedError("Milestone is already completed")

    if not force:
        still_open = open_task_count(db, milestone.id)
        if still_open:
            raise MilestoneHasOpenTasksError(still_open)

    milestone.completed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(milestone)
    return milestone


def reopen_milestone(db: Session, milestone: Milestone) -> Milestone:
    if milestone.completed_at is None:
        raise MilestoneNotCompletedError("Milestone is not completed")

    milestone.completed_at = None
    db.commit()
    db.refresh(milestone)
    return milestone


def delete_milestone(db: Session, milestone: Milestone) -> None:
    """Delete the grouping, never the work.

    Tasks under it are detached rather than removed — the database's ON DELETE
    SET NULL says the same thing — because a milestone is a view of the work
    and deleting a view must not delete what it was looking at.
    """
    db.execute(
        Task.__table__.update().where(Task.milestone_id == milestone.id).values(milestone_id=None)
    )
    db.delete(milestone)
    db.commit()
