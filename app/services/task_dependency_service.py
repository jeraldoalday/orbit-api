"""The task dependency graph: who blocks whom, and what that forbids.

The graph is a DAG by construction — every edge is checked for a cycle before
it is written — which is what makes "can this task be completed?" answerable
by looking only at a task's direct blockers rather than walking the whole
graph on every status change.
"""

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project
from app.models.task import Task, TaskStatus
from app.models.task_activity import TaskActivityType
from app.models.task_dependency import TaskDependency
from app.models.user import User
from app.services.task_activity_service import record_activity

# Walking an adversarially deep chain shouldn't be able to hold a connection
# open indefinitely. Real dependency chains are a handful of levels; anything
# past this is refused rather than traversed.
MAX_GRAPH_DEPTH = 100


class SelfDependencyError(Exception):
    pass


class CrossProjectDependencyError(Exception):
    pass


class DuplicateDependencyError(Exception):
    pass


class DependencyCycleError(Exception):
    pass


class DependencyNotFoundError(Exception):
    pass


def _edge(db: Session, task_id: uuid.UUID, depends_on_id: uuid.UUID) -> Optional[TaskDependency]:
    stmt = select(TaskDependency).where(
        TaskDependency.task_id == task_id, TaskDependency.depends_on_id == depends_on_id
    )
    return db.execute(stmt).scalar_one_or_none()


def _blocker_ids(db: Session, task_ids: set[uuid.UUID]) -> set[uuid.UUID]:
    """The direct blockers of every task in ``task_ids``, as one query."""
    if not task_ids:
        return set()
    stmt = select(TaskDependency.depends_on_id).where(TaskDependency.task_id.in_(task_ids))
    return set(db.execute(stmt).scalars().all())


def reaches(db: Session, start_id: uuid.UUID, target_id: uuid.UUID) -> bool:
    """True if ``target_id`` is reachable from ``start_id`` along blocker edges.

    Breadth-first and one query per level, rather than one per node: a chain of
    forty tasks costs forty round trips the naive way and a handful this way.
    """
    frontier = {start_id}
    seen: set[uuid.UUID] = set()

    for _ in range(MAX_GRAPH_DEPTH):
        if target_id in frontier:
            return True
        seen |= frontier
        frontier = _blocker_ids(db, frontier) - seen
        if not frontier:
            return False

    # Depth exhausted: refuse to answer rather than answer wrongly. The caller
    # turns this into a rejected edge, which keeps the graph shallow enough
    # that the next traversal terminates.
    raise DependencyCycleError("Dependency chain is too deep to verify")


def list_blockers(db: Session, task_id: uuid.UUID) -> list[Task]:
    """Tasks that must finish before ``task_id`` can, oldest edge first."""
    stmt = (
        select(Task)
        .join(TaskDependency, TaskDependency.depends_on_id == Task.id)
        .where(TaskDependency.task_id == task_id)
        .order_by(TaskDependency.created_at, Task.id)
    )
    return list(db.execute(stmt).scalars().all())


def list_dependents(db: Session, task_id: uuid.UUID) -> list[Task]:
    """Tasks waiting on ``task_id``."""
    stmt = (
        select(Task)
        .join(TaskDependency, TaskDependency.task_id == Task.id)
        .where(TaskDependency.depends_on_id == task_id)
        .order_by(TaskDependency.created_at, Task.id)
    )
    return list(db.execute(stmt).scalars().all())


def open_blockers(db: Session, task_id: uuid.UUID) -> list[Task]:
    """Blockers that aren't done yet.

    A soft-deleted blocker doesn't count: it has been taken out of the project,
    and leaving it able to hold a live task hostage would mean deleting a task
    could permanently freeze another one.
    """
    stmt = (
        select(Task)
        .join(TaskDependency, TaskDependency.depends_on_id == Task.id)
        .where(
            TaskDependency.task_id == task_id,
            Task.deleted_at.is_(None),
            Task.status != TaskStatus.DONE,
        )
        .order_by(TaskDependency.created_at, Task.id)
    )
    return list(db.execute(stmt).scalars().all())


def is_blocked(db: Session, task_id: uuid.UUID) -> bool:
    return bool(open_blockers(db, task_id))


def add_dependency(
    db: Session,
    project: Project,
    task: Task,
    depends_on: Task,
    actor: Optional[User] = None,
) -> TaskDependency:
    """Record that ``task`` cannot finish until ``depends_on`` does."""
    if task.id == depends_on.id:
        raise SelfDependencyError("A task cannot depend on itself")

    if depends_on.project_id != project.id:
        raise CrossProjectDependencyError("A dependency must be a task in the same project")

    if _edge(db, task.id, depends_on.id) is not None:
        raise DuplicateDependencyError("That dependency already exists")

    # The new edge points task -> depends_on. If task is already reachable
    # *from* depends_on, adding it closes a loop and nothing in it could ever
    # be completed.
    if reaches(db, depends_on.id, task.id):
        raise DependencyCycleError("That dependency would create a cycle")

    dependency = TaskDependency(task_id=task.id, depends_on_id=depends_on.id)
    db.add(dependency)
    record_activity(
        db,
        task.id,
        actor,
        TaskActivityType.UPDATED,
        {"blocked_by": {"added": str(depends_on.id), "title": depends_on.title}},
        commit=False,
    )
    db.commit()
    db.refresh(dependency)
    return dependency


def remove_dependency(
    db: Session,
    task: Task,
    depends_on: Task,
    actor: Optional[User] = None,
) -> None:
    dependency = _edge(db, task.id, depends_on.id)
    if dependency is None:
        raise DependencyNotFoundError("That dependency does not exist")

    db.delete(dependency)
    record_activity(
        db,
        task.id,
        actor,
        TaskActivityType.UPDATED,
        {"blocked_by": {"removed": str(depends_on.id), "title": depends_on.title}},
        commit=False,
    )
    db.commit()
