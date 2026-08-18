import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import DateTime
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UUIDPKMixin:
    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )


class TimestampMixin:
    # Python-side defaults (rather than server_default=func.now()) so created_at keeps
    # microsecond resolution on every backend; SQLite's CURRENT_TIMESTAMP only has
    # second resolution, which made same-second rows tie on created_at ordering.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )


class SoftDeleteMixin:
    """Marks a row as deleted without removing it.

    A hard DELETE on a project takes its tasks, comments, activities and
    attachments with it, and there is no way back from a misclick. Stamping a
    timestamp instead keeps the history intact and makes restore a one-column
    update; the column is indexed because *every* read of these tables filters
    on it.
    """

    deleted_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def mark_deleted(self) -> None:
        # Re-deleting keeps the original timestamp: "deleted 3 days ago"
        # shouldn't reset because someone pressed delete twice.
        if self.deleted_at is None:
            self.deleted_at = _utcnow()

    def mark_restored(self) -> None:
        self.deleted_at = None
