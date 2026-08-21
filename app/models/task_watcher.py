import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.task import Task
    from app.models.user import User


class TaskWatcher(UUIDPKMixin, TimestampMixin, Base):
    """A user who wants to hear about a task they aren't assigned to.

    Assignment already notifies one person. Watching covers everyone else with
    a stake — the reviewer, the person who filed it, the lead tracking a
    release — without handing any of them the task.
    """

    __tablename__ = "task_watchers"
    __table_args__ = (UniqueConstraint("task_id", "user_id", name="uq_task_watcher_task_user"),)

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    task: Mapped["Task"] = relationship()
    user: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        return f"<TaskWatcher task={self.task_id} user={self.user_id}>"
