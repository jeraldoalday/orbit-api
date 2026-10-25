"""Aggregate counts over tasks, for project and organization dashboards.

Everything here is a GROUP BY or a COUNT in the database rather than a list
comprehension over loaded rows. A dashboard is exactly the request that would
otherwise pull every task in an organization into memory to count four
statuses, and it is the request most likely to be polled.
"""

import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.orm import Session, aliased

from app.core.progress import completion_rate
from app.models.membership import Membership
from app.models.milestone import Milestone
from app.models.project import Project
from app.models.task import Task, TaskPriority, TaskStatus
from app.models.task_dependency import TaskDependency
from app.models.user import User
from app.schemas.stats import (
    AssigneeStats,
    MilestoneStats,
    OrganizationStats,
    ProjectStats,
    ProjectSummary,
    TaskStats,
)
from app.services.project_member_service import visible_project_condition

# "Due soon" is the near edge of the same warning a due date exists for. A
# week is the horizon a weekly planning rhythm actually acts on.
DUE_SOON_DAYS = 7


def _now(now: Optional[datetime] = None) -> datetime:
    return now or datetime.now(timezone.utc)


def _live_tasks() -> ColumnElement:
    return Task.deleted_at.is_(None)


def _open_blocker_exists() -> ColumnElement:
    """EXISTS over a task's unfinished blockers, correlated to `Task`."""
    blocker = aliased(Task)
    return (
        select(TaskDependency.id)
        .join(blocker, blocker.id == TaskDependency.depends_on_id)
        .where(
            TaskDependency.task_id == Task.id,
            blocker.deleted_at.is_(None),
            blocker.status != TaskStatus.DONE,
        )
        .exists()
    )


def _grouped(
    db: Session, scope: list[ColumnElement], column: ColumnElement, joins_project: bool
) -> dict:
    stmt = select(column, func.count()).where(*scope).group_by(column)
    if joins_project:
        stmt = stmt.select_from(Task).join(Project, Project.id == Task.project_id)
    return {row[0]: row[1] for row in db.execute(stmt).all()}


def task_stats(
    db: Session,
    scope: list[ColumnElement],
    *,
    joins_project: bool = False,
    now: Optional[datetime] = None,
) -> TaskStats:
    """Counts over whatever set of tasks `scope` selects.

    The same shape serves one project and a whole organization; only the
    predicates in `scope` differ, so the two callers can't disagree about what
    "overdue" means.
    """
    moment = _now(now)
    soon = moment + timedelta(days=DUE_SOON_DAYS)

    def count(*extra: ColumnElement) -> int:
        stmt = select(func.count()).select_from(Task)
        if joins_project:
            stmt = stmt.join(Project, Project.id == Task.project_id)
        return db.execute(stmt.where(*scope, *extra)).scalar_one()

    by_status_raw = _grouped(db, scope, Task.status, joins_project)
    by_priority_raw = _grouped(db, scope, Task.priority, joins_project)

    total = sum(by_status_raw.values())
    done = by_status_raw.get(TaskStatus.DONE, 0)

    return TaskStats(
        total=total,
        # Every member of the enum is present, at zero if unused: a dashboard
        # that has to guess whether a missing key means zero or means the
        # column changed is worse than one extra integer on the wire.
        by_status={status.value: by_status_raw.get(status, 0) for status in TaskStatus},
        by_priority={priority.value: by_priority_raw.get(priority, 0) for priority in TaskPriority},
        done=done,
        completion_rate=completion_rate(done, total),
        overdue=count(
            Task.status != TaskStatus.DONE,
            Task.due_date.is_not(None),
            Task.due_date < moment,
        ),
        due_soon=count(
            Task.status != TaskStatus.DONE,
            Task.due_date.is_not(None),
            Task.due_date >= moment,
            Task.due_date <= soon,
        ),
        unassigned=count(Task.assignee_id.is_(None)),
        blocked=count(Task.status != TaskStatus.DONE, _open_blocker_exists()),
    )


def _assignee_breakdown(
    db: Session, scope: list[ColumnElement], joins_project: bool
) -> list[AssigneeStats]:
    done_count = func.sum(case((Task.status == TaskStatus.DONE, 1), else_=0))
    stmt = (
        select(Task.assignee_id, User.email, func.count(), done_count).select_from(Task)
        # Outer, so the unassigned bucket survives as a null-id row rather than
        # disappearing from a breakdown that is supposed to add up to the total.
        .outerjoin(User, User.id == Task.assignee_id)
    )
    if joins_project:
        stmt = stmt.join(Project, Project.id == Task.project_id)
    stmt = (
        stmt.where(*scope)
        .group_by(Task.assignee_id, User.email)
        .order_by(func.count().desc(), User.email)
    )
    return [
        AssigneeStats(
            assignee_id=row[0],
            email=row[1],
            total=row[2],
            done=int(row[3] or 0),
        )
        for row in db.execute(stmt).all()
    ]


def _milestone_breakdown(db: Session, project_id: uuid.UUID) -> list[MilestoneStats]:
    """A project's live task counts, grouped by the milestone they're filed under.

    Milestones are scoped to one project, so this has no organization-wide
    counterpart the way `_assignee_breakdown` does - a milestone id would mean
    nothing without the project beside it.
    """
    done_count = func.sum(case((Task.status == TaskStatus.DONE, 1), else_=0))
    stmt = (
        select(Task.milestone_id, Milestone.name, func.count(), done_count)
        .select_from(Task)
        # Outer, so the unfiled bucket survives as a null-id row rather than
        # disappearing from a breakdown that is supposed to add up to the total.
        .outerjoin(Milestone, Milestone.id == Task.milestone_id)
        .where(Task.project_id == project_id, _live_tasks())
        .group_by(Task.milestone_id, Milestone.name)
        .order_by(func.count().desc(), Milestone.name)
    )
    return [
        MilestoneStats(
            milestone_id=row[0],
            name=row[1],
            total=row[2],
            done=int(row[3] or 0),
        )
        for row in db.execute(stmt).all()
    ]


def project_stats(db: Session, project: Project, *, now: Optional[datetime] = None) -> ProjectStats:
    scope = [Task.project_id == project.id, _live_tasks()]
    return ProjectStats(
        project_id=project.id,
        name=project.name,
        tasks=task_stats(db, scope, now=now),
        by_assignee=_assignee_breakdown(db, scope, joins_project=False),
        by_milestone=_milestone_breakdown(db, project.id),
    )


def organization_stats(
    db: Session,
    org_id: uuid.UUID,
    membership: Membership,
    *,
    now: Optional[datetime] = None,
) -> OrganizationStats:
    """Org-wide totals, over the projects this caller can actually see.

    A member excluded from a restricted project must not learn its size from
    the org total, so the same visibility condition that filters the project
    list filters what is counted here.
    """
    project_scope: list[ColumnElement] = [
        Project.organization_id == org_id,
        Project.deleted_at.is_(None),
    ]
    visible = visible_project_condition(membership)
    if visible is not None:
        project_scope.append(visible)

    task_scope = project_scope + [_live_tasks()]

    project_count = db.execute(
        select(func.count()).select_from(Project).where(*project_scope)
    ).scalar_one()

    done_count = func.sum(case((Task.status == TaskStatus.DONE, 1), else_=0))
    per_project_stmt = (
        select(Project.id, Project.name, func.count(Task.id), done_count)
        .select_from(Project)
        .outerjoin(Task, (Task.project_id == Project.id) & Task.deleted_at.is_(None))
        .where(*project_scope)
        .group_by(Project.id, Project.name)
        .order_by(func.count(Task.id).desc(), Project.name)
    )

    return OrganizationStats(
        organization_id=org_id,
        projects=project_count,
        tasks=task_stats(db, task_scope, joins_project=True, now=now),
        by_assignee=_assignee_breakdown(db, task_scope, joins_project=True),
        per_project=[
            ProjectSummary(project_id=row[0], name=row[1], total=row[2], done=int(row[3] or 0))
            for row in db.execute(per_project_stmt).all()
        ],
    )
