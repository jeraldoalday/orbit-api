"""A task's checklist: ordered steps that are ticked off, not tracked.

Positions are kept dense and 0-based. Appending reads the current maximum and
adds one; reordering rewrites every row. Both are cheap because a checklist is
bounded — the cap exists so "bounded" is a fact rather than a hope.
"""

import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.task import Task
from app.models.task_checklist_item import TaskChecklistItem
from app.schemas.task_checklist import ChecklistItemUpdate, ChecklistRead


class ChecklistItemNotFoundError(Exception):
    pass


class ChecklistLimitError(Exception):
    """Raised when a task already holds as many checklist items as it may."""


class ChecklistOrderMismatchError(Exception):
    """Raised when a reorder doesn't name exactly the items that exist.

    A partial ordering would leave the rest of the list wherever it happened to
    be, which is how two clients drag the same row and both end up wrong.
    Refusing is the only answer that keeps the list a total order.
    """


def list_items(db: Session, task_id: uuid.UUID) -> list[TaskChecklistItem]:
    stmt = (
        select(TaskChecklistItem).where(TaskChecklistItem.task_id == task_id)
        # `created_at` breaks a tie that only legacy rows can have: positions
        # written by this module are unique within a task.
        .order_by(TaskChecklistItem.position, TaskChecklistItem.created_at, TaskChecklistItem.id)
    )
    return list(db.execute(stmt).scalars().all())


def get_item(db: Session, task_id: uuid.UUID, item_id: uuid.UUID) -> Optional[TaskChecklistItem]:
    stmt = select(TaskChecklistItem).where(
        TaskChecklistItem.id == item_id, TaskChecklistItem.task_id == task_id
    )
    return db.execute(stmt).scalar_one_or_none()


def count_items(db: Session, task_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(TaskChecklistItem)
        .where(TaskChecklistItem.task_id == task_id)
    )
    return db.execute(stmt).scalar_one()


def checklist(db: Session, task_id: uuid.UUID) -> ChecklistRead:
    """The list and its progress, counted from the rows already loaded.

    A second COUNT query would be one round trip to recount a list the caller
    is holding in memory anyway.
    """
    items = list_items(db, task_id)
    done = sum(1 for item in items if item.is_done)
    total = len(items)
    return ChecklistRead(
        items=items,
        total=total,
        done=done,
        completion_rate=round(done / total, 4) if total else 0.0,
    )


def add_item(db: Session, task: Task, content: str, *, max_items: int) -> TaskChecklistItem:
    """Append a step to the end of the list."""
    if count_items(db, task.id) >= max_items:
        raise ChecklistLimitError(f"A task may hold at most {max_items} checklist items")

    highest = db.execute(
        select(func.max(TaskChecklistItem.position)).where(TaskChecklistItem.task_id == task.id)
    ).scalar_one()

    item = TaskChecklistItem(
        task_id=task.id,
        content=content,
        position=0 if highest is None else highest + 1,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def update_item(
    db: Session, item: TaskChecklistItem, changes: ChecklistItemUpdate
) -> TaskChecklistItem:
    """Apply whichever of content and is_done the caller actually sent.

    `exclude_unset` rather than `exclude_none`: a field left out is untouched,
    which is what a PATCH means, and neither field has null as a real value.
    """
    for field, value in changes.model_dump(exclude_unset=True).items():
        setattr(item, field, value)
    db.commit()
    db.refresh(item)
    return item


def delete_item(db: Session, item: TaskChecklistItem) -> None:
    """Remove a step and close the gap it leaves.

    Positions stay dense so an append after a delete can't collide with a row
    that survived, and so the numbers a client sees match the rows it drew.
    """
    task_id = item.task_id
    db.delete(item)
    db.flush()
    _renumber(db, task_id)
    db.commit()


def _renumber(db: Session, task_id: uuid.UUID) -> None:
    for position, item in enumerate(list_items(db, task_id)):
        if item.position != position:
            item.position = position


def reorder_items(
    db: Session, task_id: uuid.UUID, item_ids: list[uuid.UUID]
) -> list[TaskChecklistItem]:
    """Rewrite the list's order to exactly ``item_ids``."""
    items = list_items(db, task_id)
    existing = {item.id: item for item in items}

    if len(set(item_ids)) != len(item_ids) or set(item_ids) != set(existing):
        raise ChecklistOrderMismatchError(
            "A reorder must list every checklist item on the task exactly once"
        )

    for position, item_id in enumerate(item_ids):
        existing[item_id].position = position

    db.commit()
    return list_items(db, task_id)
