import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import BigInteger, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.task import Task
    from app.models.user import User


class Attachment(UUIDPKMixin, TimestampMixin, Base):
    """Metadata for one file uploaded against a task.

    The bytes live in object storage under ``storage_key``; this row is the
    only thing that knows a key belongs to a task. Deleting the row without
    deleting the object would leak storage forever, so both always happen
    together in :mod:`app.services.attachment_service`.
    """

    __tablename__ = "attachments"
    __table_args__ = (
        # The attachment list is always "this task's files, oldest first".
        Index("ix_attachments_task_created", "task_id", "created_at"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    uploaded_by_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_type: Mapped[str] = mapped_column(
        String(100), nullable=False, default="application/octet-stream"
    )
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Unique so two rows can never point at the same object: one being deleted
    # would otherwise pull the bytes out from under the other.
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False, unique=True)

    task: Mapped["Task"] = relationship(back_populates="attachments")
    uploaded_by: Mapped[Optional["User"]] = relationship()

    def __repr__(self) -> str:
        return f"<Attachment id={self.id} task_id={self.task_id} filename={self.filename!r}>"
