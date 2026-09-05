import uuid
from datetime import date
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Date, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.task import Task
    from app.models.user import User


class TimeEntry(UUIDPKMixin, TimestampMixin, Base):
    """Work someone did on a task, in minutes, on a given day.

    ``spent_on`` is a date the author chooses and ``created_at`` is when the
    row was written; they are routinely different, because time is logged on
    Friday for a Wednesday. Reports read the first — the second only says when
    somebody got around to the paperwork.

    Minutes rather than a start/stop pair: a running timer is a different
    feature with its own failure mode (the one left running overnight), and
    every report here wants a duration anyway.
    """

    __tablename__ = "time_entries"
    __table_args__ = (
        # Both reports this table serves are "a range of days, grouped":
        # per task and per person.
        Index("ix_time_entries_task_spent_on", "task_id", "spent_on"),
    )

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # SET NULL, like a comment's author: the hours were worked whether or not
    # the person who logged them still has an account.
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    spent_on: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    note: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)

    task: Mapped["Task"] = relationship()
    user: Mapped[Optional["User"]] = relationship()

    def __repr__(self) -> str:
        return f"<TimeEntry id={self.id} task={self.task_id} minutes={self.minutes}>"
