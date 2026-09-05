import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.project import Project


class Milestone(UUIDPKMixin, TimestampMixin, Base):
    """A dated goal inside a project that tasks are grouped under.

    Labels already answer "what kind of work is this?" across a whole
    organization. A milestone answers a different question — "what is left
    before the 12th?" — so it is scoped to one project, carries a due date of
    its own, and a task belongs to at most one of them.

    Completion is a timestamp rather than a boolean for the same reason read
    state is on a notification: "shipped on the 9th" is worth keeping, and
    reopening is then a single-column update.
    """

    __tablename__ = "milestones"

    project_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    due_date: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    project: Mapped["Project"] = relationship()

    @property
    def is_completed(self) -> bool:
        return self.completed_at is not None

    def __repr__(self) -> str:
        return f"<Milestone id={self.id} name={self.name!r} completed={self.is_completed}>"
