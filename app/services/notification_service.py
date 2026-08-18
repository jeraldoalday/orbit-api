import re
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, joinedload

from app.models.notification import Notification, NotificationType
from app.models.user import User

# Mentions are written as "@someone@example.com" — the address is the only
# handle a user has in this system, so the leading "@" is the sole marker.
_MENTION_PATTERN = re.compile(r"@([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,})")


def extract_mentions(body: str) -> list[str]:
    """Unique lowercased email addresses mentioned in a comment, in order."""
    seen: dict[str, None] = {}
    for match in _MENTION_PATTERN.findall(body or ""):
        seen.setdefault(match.lower(), None)
    return list(seen)


def create_notification(
    db: Session,
    *,
    user_id: uuid.UUID,
    organization_id: uuid.UUID,
    notification_type: NotificationType,
    actor: Optional[User] = None,
    task_id: Optional[uuid.UUID] = None,
    data: Optional[dict[str, Any]] = None,
    commit: bool = True,
) -> Optional[Notification]:
    """Record a notification, skipping the no-op case of notifying yourself."""
    if actor is not None and actor.id == user_id:
        return None

    notification = Notification(
        user_id=user_id,
        organization_id=organization_id,
        actor_id=actor.id if actor is not None else None,
        task_id=task_id,
        notification_type=notification_type,
        data=data,
    )
    db.add(notification)
    if commit:
        db.commit()
        db.refresh(notification)
    return notification


def list_notifications(
    db: Session,
    user_id: uuid.UUID,
    *,
    unread_only: bool = False,
    organization_id: Optional[uuid.UUID] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Notification]:
    stmt = (
        select(Notification)
        .options(joinedload(Notification.actor))
        .where(Notification.user_id == user_id)
    )

    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    if organization_id is not None:
        stmt = stmt.where(Notification.organization_id == organization_id)

    # Newest first: an inbox reads top-down, unlike the task timeline.
    stmt = (
        stmt.order_by(Notification.created_at.desc(), Notification.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def get_notification(
    db: Session, user_id: uuid.UUID, notification_id: uuid.UUID
) -> Optional[Notification]:
    stmt = select(Notification).where(
        Notification.id == notification_id, Notification.user_id == user_id
    )
    return db.execute(stmt).scalar_one_or_none()


def count_unread(db: Session, user_id: uuid.UUID) -> int:
    stmt = select(func.count()).where(
        Notification.user_id == user_id, Notification.read_at.is_(None)
    )
    return db.execute(stmt).scalar_one()


def mark_read(db: Session, notification: Notification) -> Notification:
    # Marking an already-read notification is idempotent: keep the first
    # timestamp so "read 3 days ago" doesn't reset on every refresh.
    if notification.read_at is None:
        notification.read_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(notification)
    return notification


def mark_unread(db: Session, notification: Notification) -> Notification:
    if notification.read_at is not None:
        notification.read_at = None
        db.commit()
        db.refresh(notification)
    return notification


def mark_all_read(db: Session, user_id: uuid.UUID) -> int:
    stmt = (
        update(Notification)
        .where(Notification.user_id == user_id, Notification.read_at.is_(None))
        .values(read_at=datetime.now(timezone.utc))
    )
    result = db.execute(stmt)
    db.commit()
    return result.rowcount or 0


def delete_notification(db: Session, notification: Notification) -> None:
    db.delete(notification)
    db.commit()
