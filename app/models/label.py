import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.task import Task


class Label(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "labels"
    __table_args__ = (UniqueConstraint("organization_id", "name", name="uq_label_org_name"),)

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(50), nullable=False)
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="#6b7280")

    organization: Mapped["Organization"] = relationship()
    tasks: Mapped[list["Task"]] = relationship(
        secondary="task_labels", back_populates="labels", viewonly=True
    )

    def __repr__(self) -> str:
        return f"<Label id={self.id} name={self.name!r}>"
