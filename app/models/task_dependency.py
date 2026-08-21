import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.task import Task


class TaskDependency(UUIDPKMixin, TimestampMixin, Base):
    """One directed "must finish first" edge between two tasks.

    ``task_id`` is the *blocked* task and ``depends_on_id`` the blocker, so a
    row reads left-to-right as "task depends on other". Both columns are
    indexed because the graph is walked in both directions: a task's own
    blockers, and everything waiting on it.

    Edges stay inside a single project. Crossing project boundaries would let a
    task be blocked by one the caller can't even see, which turns a 404 into a
    permanently unexplainable 409.
    """

    __tablename__ = "task_dependencies"
    __table_args__ = (
        # Adding the same edge twice is a no-op, not a second edge; the
        # constraint makes that true even when two requests race.
        UniqueConstraint("task_id", "depends_on_id", name="uq_task_dependency_task_depends_on"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    depends_on_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    task: Mapped["Task"] = relationship(foreign_keys=[task_id])
    depends_on: Mapped["Task"] = relationship(foreign_keys=[depends_on_id])

    def __repr__(self) -> str:
        return f"<TaskDependency task={self.task_id} depends_on={self.depends_on_id}>"
