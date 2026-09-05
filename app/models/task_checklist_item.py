import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.task import Task


class TaskChecklistItem(UUIDPKMixin, TimestampMixin, Base):
    """One tickable step inside a task.

    Splitting a task into subtasks would give every step its own assignee,
    status, comments and notifications — most of which nobody wants for "write
    the migration". A checklist is the cheap half of that: ordered lines that
    are done or not, carried by the task rather than competing with it.
    """

    __tablename__ = "task_checklist_items"
    __table_args__ = (
        # The only query this table serves: one task's list, in order.
        Index("ix_task_checklist_items_task_position", "task_id", "position"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    content: Mapped[str] = mapped_column(String(200), nullable=False)
    is_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Dense 0-based rank rather than a float or a linked list: the list is
    # short and always rewritten whole by a reorder, so the simplest thing that
    # sorts is the right one.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    task: Mapped["Task"] = relationship()

    def __repr__(self) -> str:
        return f"<TaskChecklistItem id={self.id} position={self.position} done={self.is_done}>"
