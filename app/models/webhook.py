import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.mixins import TimestampMixin, UUIDPKMixin

if TYPE_CHECKING:
    from app.models.organization import Organization


class WebhookEvent(str, enum.Enum):
    """Events an organization can subscribe to.

    The values are the wire format — they appear in the delivery payload and in
    a subscription's ``events`` array — so they are namespaced and stable, and
    renaming one is a breaking change for every consumer.
    """

    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_DELETED = "task.deleted"
    TASK_ASSIGNED = "task.assigned"
    COMMENT_CREATED = "comment.created"


class DeliveryStatus(str, enum.Enum):
    PENDING = "pending"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class WebhookSubscription(UUIDPKMixin, TimestampMixin, Base):
    """One endpoint an organization wants events posted to."""

    __tablename__ = "webhook_subscriptions"

    organization_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    # A JSON array of WebhookEvent values rather than a join table: the list is
    # short, always read whole, and never queried by element.
    events: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    # The shared secret the HMAC signature is derived from. Returned to the
    # caller exactly once, at creation and on rotation.
    secret: Mapped[str] = mapped_column(String(128), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    organization: Mapped["Organization"] = relationship()

    def subscribes_to(self, event: WebhookEvent) -> bool:
        return self.is_active and event.value in (self.events or [])

    def __repr__(self) -> str:
        return f"<WebhookSubscription id={self.id} url={self.url!r} active={self.is_active}>"


class WebhookDelivery(UUIDPKMixin, TimestampMixin, Base):
    """One attempt-tracked delivery of one event to one subscription.

    Rows are written synchronously with the event that caused them and left
    ``PENDING``; the worker picks them up out of band. Doing the HTTP call
    inline would tie the latency — and the success — of a task update to a
    third-party endpoint being reachable.
    """

    __tablename__ = "webhook_deliveries"
    __table_args__ = (
        # The worker's only query: due pending rows, oldest first.
        Index("ix_webhook_deliveries_status_next_attempt", "status", "next_attempt_at"),
    )

    subscription_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("webhook_subscriptions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    event_type: Mapped[WebhookEvent] = mapped_column(
        Enum(WebhookEvent, name="webhook_event"), nullable=False
    )
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="webhook_delivery_status"),
        nullable=False,
        default=DeliveryStatus.PENDING,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    response_status: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    next_attempt_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    subscription: Mapped["WebhookSubscription"] = relationship()

    def __repr__(self) -> str:
        return (
            f"<WebhookDelivery id={self.id} event={self.event_type} "
            f"status={self.status} attempts={self.attempts}>"
        )
