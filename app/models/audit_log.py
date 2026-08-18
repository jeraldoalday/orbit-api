import enum
import uuid
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import JSON, Enum, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.organization import Organization
    from app.models.user import User


class AuditAction(str, enum.Enum):
    """The actions worth answering "who did this, and when?" about.

    Reads are deliberately absent: logging every GET would bury the handful of
    entries anyone actually goes looking for. What's here is the set that
    changes who can see what, or that destroys something.
    """

    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    PROJECT_DELETED = "project.deleted"
    PROJECT_RESTORED = "project.restored"
    PROJECT_PURGED = "project.purged"

    TASK_DELETED = "task.deleted"
    TASK_RESTORED = "task.restored"
    TASK_PURGED = "task.purged"

    MEMBER_ADDED = "member.added"
    MEMBER_ROLE_CHANGED = "member.role_changed"
    MEMBER_REMOVED = "member.removed"

    WEBHOOK_CREATED = "webhook.created"
    WEBHOOK_UPDATED = "webhook.updated"
    WEBHOOK_DELETED = "webhook.deleted"
    WEBHOOK_SECRET_ROTATED = "webhook.secret_rotated"


class AuditResource(str, enum.Enum):
    PROJECT = "project"
    TASK = "task"
    MEMBERSHIP = "membership"
    WEBHOOK = "webhook"


class AuditLog(UUIDPKMixin, TimestampMixin, Base):
    """An append-only record of one consequential action in an organization.

    Rows are never updated or deleted through the API: an audit trail that the
    people it describes can edit answers nothing. ``resource_id`` is a plain
    UUID with no foreign key, deliberately — the entry has to outlive the row
    it describes, which is the whole point for a purge.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        # The only query anyone runs: one org's trail, newest first.
        Index("ix_audit_logs_org_created", "organization_id", "created_at"),
    )

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    actor_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Denormalized so the trail still names who acted after the account is
    # deleted and actor_id has been nulled out.
    actor_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    action: Mapped[AuditAction] = mapped_column(
        Enum(AuditAction, name="audit_action"), nullable=False, index=True
    )
    resource_type: Mapped[AuditResource] = mapped_column(
        Enum(AuditResource, name="audit_resource"), nullable=False
    )
    resource_id: Mapped[Optional[uuid.UUID]] = mapped_column(UUID(as_uuid=True), nullable=True)
    data: Mapped[Optional[dict[str, Any]]] = mapped_column(JSON, nullable=True)

    organization: Mapped["Organization"] = relationship()
    actor: Mapped[Optional["User"]] = relationship()

    def __repr__(self) -> str:
        return f"<AuditLog id={self.id} action={self.action} resource={self.resource_id}>"
