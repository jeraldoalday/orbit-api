"""Watching a task, and the fan-out that follows from it.

Assignment notifies exactly one person; a mention notifies the people named.
Watching covers everyone else with a stake in a task — the reviewer, whoever
filed it, a lead tracking a release — without handing any of them the work.
"""

import uuid
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.models.notification import NotificationType
from app.models.project import Project
from app.models.task import Task
from app.models.task_watcher import TaskWatcher
from app.models.user import User
from app.services.auth_service import get_user_by_email
from app.services.notification_service import create_notification
from app.services.project_member_service import can_see_project


class AlreadyWatchingError(Exception):
    pass


class NotWatchingError(Exception):
    pass


class WatcherNotFoundError(Exception):
    pass


class WatcherCannotSeeProjectError(Exception):
    pass


def get_watcher(db: Session, task_id: uuid.UUID, user_id: uuid.UUID) -> Optional[TaskWatcher]:
    stmt = select(TaskWatcher).where(TaskWatcher.task_id == task_id, TaskWatcher.user_id == user_id)
    return db.execute(stmt).scalar_one_or_none()


def list_watchers(db: Session, task_id: uuid.UUID) -> list[TaskWatcher]:
    stmt = (
        select(TaskWatcher)
        .options(joinedload(TaskWatcher.user))
        .where(TaskWatcher.task_id == task_id)
        .order_by(TaskWatcher.created_at, TaskWatcher.id)
    )
    return list(db.execute(stmt).scalars().all())


def watcher_ids(db: Session, task_id: uuid.UUID) -> list[uuid.UUID]:
    stmt = select(TaskWatcher.user_id).where(TaskWatcher.task_id == task_id)
    return list(db.execute(stmt).scalars().all())


def add_watcher(db: Session, project: Project, task: Task, user: User) -> TaskWatcher:
    """Start watching, for yourself or on someone else's behalf."""
    if not can_see_project(db, project, user.id):
        # A watcher who can't open the task would receive notifications about
        # a project the API otherwise refuses to admit exists.
        raise WatcherCannotSeeProjectError("That user does not have access to this project")

    if get_watcher(db, task.id, user.id) is not None:
        raise AlreadyWatchingError("Already watching this task")

    watcher = TaskWatcher(task_id=task.id, user_id=user.id)
    db.add(watcher)
    db.commit()
    db.refresh(watcher)
    return watcher


def add_watcher_by_email(db: Session, project: Project, task: Task, email: str) -> TaskWatcher:
    user = get_user_by_email(db, email.strip().lower())
    if user is None:
        raise WatcherNotFoundError(f"No user is registered with email {email}")
    return add_watcher(db, project, task, user)


def remove_watcher(db: Session, task: Task, user_id: uuid.UUID) -> None:
    watcher = get_watcher(db, task.id, user_id)
    if watcher is None:
        raise NotWatchingError("Not watching this task")
    db.delete(watcher)
    db.commit()


def notify_watchers(
    db: Session,
    project: Project,
    task: Task,
    actor: Optional[User],
    notification_type: NotificationType,
    data: dict[str, Any],
    *,
    skip: Optional[set[uuid.UUID]] = None,
    commit: bool = False,
) -> int:
    """Notify everyone watching ``task``, minus ``skip`` and the actor.

    ``skip`` carries the people this change already notified some other way —
    the assignee, anyone mentioned — so one event never produces two rows for
    the same person. The actor drops out inside create_notification, which
    already refuses to tell someone what they just did.
    """
    excluded = skip or set()
    notified = 0

    for user_id in watcher_ids(db, task.id):
        if user_id in excluded:
            continue
        notification = create_notification(
            db,
            user_id=user_id,
            organization_id=project.organization_id,
            notification_type=notification_type,
            actor=actor,
            task_id=task.id,
            data=data,
            commit=False,
        )
        if notification is not None:
            notified += 1

    if commit:
        db.commit()
    return notified
