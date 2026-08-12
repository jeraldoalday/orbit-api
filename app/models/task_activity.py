import enum
import uuid
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import JSON, Enum, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.task import Task
    from app.models.user import User


class TaskActivityType(str, enum.Enum):
    CREATED = "created"
    UPDATED = "updated"


class TaskActivity(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "task_activities"

    task_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("tasks.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    activity_type: Mapped[TaskActivityType] = mapped_column(
        Enum(TaskActivityType, name="task_activity_type"), nullable=False
    )
    data: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    task: Mapped["Task"] = relationship()
    actor: Mapped[Optional["User"]] = relationship()

    def __repr__(self) -> str:
        return f"<TaskActivity id={self.id} task_id={self.task_id} type={self.activity_type}>"
