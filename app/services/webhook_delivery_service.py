"""Enqueueing and delivering webhook events.

Deliveries are written to the database by the request that caused them and
posted out of band. Calling a third-party endpoint inline would make the
latency — and the success — of updating a task depend on someone else's
server being up, so the request only ever writes a row.
"""

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.core.webhook_signing import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    build_signature_header,
)
from app.core.webhook_transport import TransportError, WebhookTransport
from app.core.webhook_url import address_is_deliverable, resolve_primary_address
from app.models.webhook import DeliveryStatus, WebhookDelivery, WebhookEvent, WebhookSubscription
from app.services.webhook_service import list_subscribers

MAX_ERROR_LENGTH = 500


@dataclass(frozen=True)
class DispatchSummary:
    """What one worker pass did."""

    attempted: int = 0
    succeeded: int = 0
    failed: int = 0
    retrying: int = 0


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_envelope(
    event: WebhookEvent, organization_id: uuid.UUID, data: dict[str, Any]
) -> dict[str, Any]:
    """The stable outer shape every delivery carries.

    Receivers switch on ``event`` and read ``data``; keeping the envelope
    separate means a new event type never changes the parsing code.
    """
    return {
        "event": event.value,
        "organization_id": str(organization_id),
        "occurred_at": _utcnow().isoformat(),
        "data": data,
    }


def serialize_payload(payload: dict[str, Any]) -> bytes:
    """Serialize deterministically — the signature is over these exact bytes.

    Sorted keys and no incidental whitespace mean a body re-serialized on a
    retry is byte-identical to the one signed on the first attempt.
    """
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def enqueue_event(
    db: Session,
    organization_id: uuid.UUID,
    event: WebhookEvent,
    data: dict[str, Any],
    *,
    commit: bool = True,
) -> list[WebhookDelivery]:
    """Queue one delivery per subscription that wants ``event``.

    ``commit=False`` lets the caller fold this into the transaction that
    produced the event, so a task update and its webhook row land together or
    not at all.
    """
    subscribers = list_subscribers(db, organization_id, event)
    if not subscribers:
        return []

    payload = build_envelope(event, organization_id, data)
    deliveries = [
        WebhookDelivery(
            subscription_id=subscription.id,
            event_type=event,
            payload=payload,
            status=DeliveryStatus.PENDING,
            attempts=0,
            next_attempt_at=None,
        )
        for subscription in subscribers
    ]
    db.add_all(deliveries)
    if commit:
        db.commit()
    else:
        db.flush()
    return deliveries


def due_deliveries(
    db: Session, *, limit: int = 50, now: Optional[datetime] = None
) -> list[WebhookDelivery]:
    """Pending deliveries whose next attempt is due, oldest first."""
    moment = now or _utcnow()
    stmt = (
        select(WebhookDelivery)
        .options(joinedload(WebhookDelivery.subscription))
        .where(
            WebhookDelivery.status == DeliveryStatus.PENDING,
            (WebhookDelivery.next_attempt_at.is_(None))
            | (WebhookDelivery.next_attempt_at <= moment),
        )
        .order_by(WebhookDelivery.created_at, WebhookDelivery.id)
        .limit(limit)
    )
    return list(db.execute(stmt).scalars().all())


def backoff_delay(attempts: int, base_seconds: int) -> timedelta:
    """Exponential backoff: base, 2x, 4x, 8x ... after each failed attempt."""
    exponent = max(attempts - 1, 0)
    # Cap the exponent so a long-lived row can't overflow into an absurd date.
    return timedelta(seconds=base_seconds * (2 ** min(exponent, 10)))


def build_headers(subscription: WebhookSubscription, delivery: WebhookDelivery, body: bytes):
    return {
        "Content-Type": "application/json",
        "User-Agent": "Orbit-Webhooks/1.0",
        EVENT_HEADER: delivery.event_type.value,
        DELIVERY_HEADER: str(delivery.id),
        SIGNATURE_HEADER: build_signature_header(subscription.secret, body),
    }


def _record_success(delivery: WebhookDelivery, status_code: int, now: datetime) -> None:
    delivery.status = DeliveryStatus.SUCCEEDED
    delivery.response_status = status_code
    delivery.error = None
    delivery.delivered_at = now
    delivery.next_attempt_at = None


def _record_failure(
    delivery: WebhookDelivery,
    *,
    error: str,
    status_code: Optional[int],
    now: datetime,
    max_attempts: int,
    backoff_base_seconds: int,
) -> bool:
    """Mark one failed attempt. Returns True if the delivery will be retried."""
    delivery.response_status = status_code
    delivery.error = error[:MAX_ERROR_LENGTH]

    if delivery.attempts >= max_attempts:
        delivery.status = DeliveryStatus.FAILED
        delivery.next_attempt_at = None
        return False

    delivery.status = DeliveryStatus.PENDING
    delivery.next_attempt_at = now + backoff_delay(delivery.attempts, backoff_base_seconds)
    return True


def attempt_delivery(
    db: Session,
    transport: WebhookTransport,
    delivery: WebhookDelivery,
    *,
    max_attempts: int = 5,
    timeout_seconds: float = 10.0,
    backoff_base_seconds: int = 60,
    verify_target: bool = True,
    now: Optional[datetime] = None,
) -> bool:
    """Post one delivery and record the outcome. Returns whether it succeeded.

    The row is updated in every branch, so a delivery can never be picked up
    twice for the same attempt without its attempt count moving.
    """
    moment = now or _utcnow()
    subscription = delivery.subscription
    delivery.attempts += 1

    if subscription is None or not subscription.is_active:
        # Nothing will ever make this deliverable again; failing it now stops
        # the worker from reconsidering the row on every pass.
        delivery.status = DeliveryStatus.FAILED
        delivery.error = "Subscription is inactive or gone"
        delivery.next_attempt_at = None
        db.commit()
        return False

    body = serialize_payload(delivery.payload)

    try:
        if verify_target:
            # Re-check the address now, not just at subscription time: a name
            # that validated as public can be repointed at an internal host.
            address = resolve_primary_address(subscription.url)
            if not address_is_deliverable(address):
                raise TransportError("Target resolves to a private or reserved address")

        response = transport.post(
            subscription.url,
            body,
            build_headers(subscription, delivery, body),
            timeout=timeout_seconds,
        )
    except TransportError as exc:
        _record_failure(
            delivery,
            error=str(exc),
            status_code=None,
            now=moment,
            max_attempts=max_attempts,
            backoff_base_seconds=backoff_base_seconds,
        )
        db.commit()
        return False

    if 200 <= response.status_code < 300:
        _record_success(delivery, response.status_code, moment)
        db.commit()
        return True

    _record_failure(
        delivery,
        error=f"Endpoint returned HTTP {response.status_code}",
        status_code=response.status_code,
        now=moment,
        max_attempts=max_attempts,
        backoff_base_seconds=backoff_base_seconds,
    )
    db.commit()
    return False


def dispatch_pending(
    db: Session,
    transport: WebhookTransport,
    *,
    limit: int = 50,
    max_attempts: int = 5,
    timeout_seconds: float = 10.0,
    backoff_base_seconds: int = 60,
    verify_target: bool = True,
    now: Optional[datetime] = None,
) -> DispatchSummary:
    """Run one pass over the due deliveries."""
    moment = now or _utcnow()
    pending = due_deliveries(db, limit=limit, now=moment)

    succeeded = failed = retrying = 0
    for delivery in pending:
        if attempt_delivery(
            db,
            transport,
            delivery,
            max_attempts=max_attempts,
            timeout_seconds=timeout_seconds,
            backoff_base_seconds=backoff_base_seconds,
            verify_target=verify_target,
            now=moment,
        ):
            succeeded += 1
        elif delivery.status == DeliveryStatus.FAILED:
            failed += 1
        else:
            retrying += 1

    return DispatchSummary(
        attempted=len(pending), succeeded=succeeded, failed=failed, retrying=retrying
    )


def list_deliveries(
    db: Session,
    subscription_id: uuid.UUID,
    *,
    status: Optional[DeliveryStatus] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[WebhookDelivery]:
    stmt = select(WebhookDelivery).where(WebhookDelivery.subscription_id == subscription_id)
    if status is not None:
        stmt = stmt.where(WebhookDelivery.status == status)
    # Newest first: an operator looking at deliveries wants the recent ones.
    stmt = (
        stmt.order_by(WebhookDelivery.created_at.desc(), WebhookDelivery.id.desc())
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def get_delivery(
    db: Session, subscription_id: uuid.UUID, delivery_id: uuid.UUID
) -> Optional[WebhookDelivery]:
    stmt = select(WebhookDelivery).where(
        WebhookDelivery.id == delivery_id,
        WebhookDelivery.subscription_id == subscription_id,
    )
    return db.execute(stmt).scalar_one_or_none()


def requeue_delivery(db: Session, delivery: WebhookDelivery) -> WebhookDelivery:
    """Put a delivery back in the queue for an immediate attempt.

    The attempt counter is reset too: an operator retrying by hand has usually
    fixed whatever was broken, and keeping the count would let the retry
    exhaust the budget on its first pass.
    """
    delivery.status = DeliveryStatus.PENDING
    delivery.attempts = 0
    delivery.error = None
    delivery.response_status = None
    delivery.next_attempt_at = None
    delivery.delivered_at = None
    db.commit()
    db.refresh(delivery)
    return delivery
