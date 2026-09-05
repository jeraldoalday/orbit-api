import uuid
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import (
    get_current_active_user,
    get_project_or_404,
    get_task_or_404,
    require_org_member,
    require_project_role,
)
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole, role_at_least
from app.models.project import Project
from app.models.project_member import ProjectRole, project_role_at_least
from app.models.task import Task
from app.models.time_entry import TimeEntry
from app.models.user import User
from app.schemas.time_entry import (
    ProjectTimeReport,
    TaskTimeSummary,
    TimeEntryCreate,
    TimeEntryRead,
    TimeEntryUpdate,
)
from app.services.time_entry_service import (
    FutureTimeEntryError,
    delete_entry,
    get_entry,
    log_time,
    project_report,
    task_summary,
    update_entry,
)

router = APIRouter(
    prefix="/organizations/{org_id}/projects/{project_id}/tasks/{task_id}/time",
    tags=["time-tracking"],
)

# The project-wide report hangs off the project, not a task, so it needs its
# own prefix rather than a route on the one above.
report_router = APIRouter(
    prefix="/organizations/{org_id}/projects/{project_id}/time", tags=["time-tracking"]
)


def _entry_or_404(db: Session, task: Task, entry_id: uuid.UUID) -> TimeEntry:
    entry = get_entry(db, task.id, entry_id)
    if entry is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Time entry not found")
    return entry


def _require_own_entry_or_manager(
    entry: TimeEntry, current_user: User, role: ProjectRole, membership: Membership
) -> None:
    """Only the author edits their own hours; a manager can correct anyone's.

    Somebody else's timesheet is not an ordinary editor's business, so this is
    narrower than the editor rights that logging time needs — but a project
    manager or org admin has to be able to fix an entry whose author is on
    leave, or gone.
    """
    if entry.user_id == current_user.id:
        return
    if project_role_at_least(role, ProjectRole.MANAGER) or role_at_least(
        membership.role, MembershipRole.ADMIN
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Only the author or a project manager can change this time entry",
    )


@router.get("", response_model=TaskTimeSummary)
def summary(
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
) -> TaskTimeSummary:
    """What this task has cost so far, against its estimate."""
    return task_summary(db, task)


@router.post("", response_model=TimeEntryRead, status_code=status.HTTP_201_CREATED)
def log(
    entry_in: TimeEntryCreate,
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.EDITOR)),
    current_user: User = Depends(get_current_active_user),
) -> TimeEntryRead:
    """Log work against this task, on a day defaulting to today."""
    try:
        return log_time(
            db,
            task,
            current_user,
            entry_in.minutes,
            spent_on=entry_in.spent_on,
            note=entry_in.note,
        )
    except FutureTimeEntryError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.patch("/{entry_id}", response_model=TimeEntryRead)
def update(
    entry_id: uuid.UUID,
    changes: TimeEntryUpdate,
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    role: ProjectRole = Depends(require_project_role(ProjectRole.EDITOR)),
    membership: Membership = Depends(require_org_member),
    current_user: User = Depends(get_current_active_user),
) -> TimeEntryRead:
    entry = _entry_or_404(db, task, entry_id)
    _require_own_entry_or_manager(entry, current_user, role, membership)
    try:
        return update_entry(db, entry, changes)
    except FutureTimeEntryError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.delete("/{entry_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove(
    entry_id: uuid.UUID,
    db: Session = Depends(get_db),
    task: Task = Depends(get_task_or_404),
    role: ProjectRole = Depends(require_project_role(ProjectRole.EDITOR)),
    membership: Membership = Depends(require_org_member),
    current_user: User = Depends(get_current_active_user),
) -> None:
    entry = _entry_or_404(db, task, entry_id)
    _require_own_entry_or_manager(entry, current_user, role, membership)
    delete_entry(db, entry)


@report_router.get("", response_model=ProjectTimeReport)
def report(
    db: Session = Depends(get_db),
    project: Project = Depends(get_project_or_404),
    _role: ProjectRole = Depends(require_project_role(ProjectRole.VIEWER)),
    spent_from: Optional[date] = Query(default=None),
    spent_to: Optional[date] = Query(default=None),
) -> ProjectTimeReport:
    """Minutes logged in this project, by person and by task."""
    if spent_from is not None and spent_to is not None and spent_from > spent_to:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="spent_from must not be after spent_to",
        )
    return project_report(db, project.id, spent_from=spent_from, spent_to=spent_to)
