import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.task import Task


class Label(UUIDPKMixin, TimestampMixin, Base):
    __tablename__ = "labels"
    __table_args__ = (
        UniqueConstraint("organization_id", "name", name="uq_label_org_name"),
        # The service layer checks for a case-insensitive duplicate before
        # inserting, but two requests racing each other can both pass that
        # check before either commits. `uq_label_org_name` above only catches
        # an exact-case repeat, so without this the race lets "Bug" and "bug"
        # both land. This index is the backstop the service's IntegrityError
        # handler relies on to make that rejection actually hold under a race.
        Index(
            "uq_label_org_name_ci",
            "organization_id",
            text("lower(name)"),
            unique=True,
        ),
    )

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
