import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user
from app.core.config import get_settings
from app.db.session import get_db
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import MarkAllReadResult, NotificationRead, UnreadCount
from app.services.notification_service import (
    count_unread,
    delete_notification,
    get_notification,
    list_notifications,
    mark_all_read,
    mark_read,
    mark_unread,
)

settings = get_settings()

router = APIRouter(prefix="/notifications", tags=["notifications"])


def _get_notification_or_404(
    notification_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
) -> Notification:
    notification = get_notification(db, current_user.id, notification_id)
    if notification is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
    return notification


@router.get("", response_model=list[NotificationRead])
def list_mine(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    unread_only: bool = False,
    organization_id: Optional[uuid.UUID] = None,
    limit: int = Query(default=settings.list_default_limit, ge=1, le=settings.list_max_limit),
    offset: int = Query(default=0, ge=0),
) -> list[NotificationRead]:
    return list_notifications(
        db,
        current_user.id,
        unread_only=unread_only,
        organization_id=organization_id,
        limit=limit,
        offset=offset,
    )


@router.get("/unread_count", response_model=UnreadCount)
def unread_count(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    organization_id: Optional[uuid.UUID] = None,
) -> UnreadCount:
    """The unread badge, over the same scope the list takes."""
    return UnreadCount(unread=count_unread(db, current_user.id, organization_id=organization_id))


@router.post("/read_all", response_model=MarkAllReadResult)
def read_all(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_active_user),
    organization_id: Optional[uuid.UUID] = None,
) -> MarkAllReadResult:
    """Mark everything read, optionally only within one organization."""
    return MarkAllReadResult(
        marked=mark_all_read(db, current_user.id, organization_id=organization_id)
    )


@router.post("/{notification_id}/read", response_model=NotificationRead)
def read(
    db: Session = Depends(get_db),
    notification: Notification = Depends(_get_notification_or_404),
) -> NotificationRead:
    return mark_read(db, notification)


@router.post("/{notification_id}/unread", response_model=NotificationRead)
def unread(
    db: Session = Depends(get_db),
    notification: Notification = Depends(_get_notification_or_404),
) -> NotificationRead:
    return mark_unread(db, notification)


@router.delete("/{notification_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    db: Session = Depends(get_db),
    notification: Notification = Depends(_get_notification_or_404),
) -> None:
    delete_notification(db, notification)
