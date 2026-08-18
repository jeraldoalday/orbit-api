"""Delivery worker behaviour: signing, retries, backoff and target re-checks."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.core.webhook_signing import (
    DELIVERY_HEADER,
    EVENT_HEADER,
    SIGNATURE_HEADER,
    verify_signature,
)
from app.core.webhook_transport import TransportError, TransportResponse, WebhookTransport
from app.models.organization import Organization
from app.models.webhook import DeliveryStatus, WebhookEvent, WebhookSubscription
from app.services.webhook_delivery_service import (
    attempt_delivery,
    backoff_delay,
    build_envelope,
    dispatch_pending,
    due_deliveries,
    enqueue_event,
    requeue_delivery,
    serialize_payload,
)

SECRET = "a" * 64


def _as_utc(value: datetime) -> datetime:
    """SQLite hands back naive datetimes; Postgres keeps the offset.

    Both store UTC, so normalizing here lets the assertions read the same way
    under the test engine and the real one.
    """
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


class RecordingTransport(WebhookTransport):
    """A transport that records requests and returns a scripted outcome."""

    def __init__(self, status_code=200, error=None):
        self.status_code = status_code
        self.error = error
        self.requests = []

    def post(self, url, body, headers, *, timeout):
        self.requests.append({"url": url, "body": body, "headers": headers, "timeout": timeout})
        if self.error is not None:
            raise TransportError(self.error)
        return TransportResponse(status_code=self.status_code)


@pytest.fixture()
def org(db) -> Organization:
    organization = Organization(name="Acme Inc", slug="acme-inc")
    db.add(organization)
    db.commit()
    db.refresh(organization)
    return organization


@pytest.fixture()
def subscription(db, org) -> WebhookSubscription:
    record = WebhookSubscription(
        organization_id=org.id,
        url="https://hooks.example.com/orbit",
        events=[WebhookEvent.TASK_CREATED.value, WebhookEvent.TASK_UPDATED.value],
        secret=SECRET,
        is_active=True,
    )
    db.add(record)
    db.commit()
    db.refresh(record)
    return record


def _enqueue(db, org, event=WebhookEvent.TASK_CREATED, data=None):
    return enqueue_event(db, org.id, event, data or {"task_id": "abc"})


def _dispatch(db, transport, **kwargs):
    kwargs.setdefault("verify_target", False)
    return dispatch_pending(db, transport, **kwargs)


# --- enqueueing -------------------------------------------------------------


def test_enqueue_creates_one_delivery_per_subscriber(db, org, subscription):
    deliveries = _enqueue(db, org)

    assert len(deliveries) == 1
    assert deliveries[0].subscription_id == subscription.id
    assert deliveries[0].status == DeliveryStatus.PENDING
    assert deliveries[0].attempts == 0


def test_enqueue_skips_events_the_subscription_did_not_ask_for(db, org, subscription):
    assert _enqueue(db, org, event=WebhookEvent.COMMENT_CREATED) == []


def test_enqueue_skips_an_inactive_subscription(db, org, subscription):
    subscription.is_active = False
    db.commit()

    assert _enqueue(db, org) == []


def test_enqueue_skips_another_organizations_subscription(db, org, subscription):
    other = Organization(name="Other Inc", slug="other-inc")
    db.add(other)
    db.commit()

    assert enqueue_event(db, other.id, WebhookEvent.TASK_CREATED, {}) == []


def test_the_envelope_carries_the_event_and_the_data():
    organization_id = uuid.uuid4()

    envelope = build_envelope(WebhookEvent.TASK_CREATED, organization_id, {"task_id": "x"})

    assert envelope["event"] == "task.created"
    assert envelope["organization_id"] == str(organization_id)
    assert envelope["data"] == {"task_id": "x"}
    assert "occurred_at" in envelope


def test_serialization_is_deterministic():
    payload = {"b": 1, "a": {"d": 2, "c": 3}}

    assert serialize_payload(payload) == serialize_payload(dict(reversed(list(payload.items()))))
    assert serialize_payload(payload) == b'{"a":{"c":3,"d":2},"b":1}'


# --- delivery ---------------------------------------------------------------


def test_a_successful_delivery_is_marked_delivered(db, org, subscription):
    delivery = _enqueue(db, org)[0]
    transport = RecordingTransport(status_code=204)

    summary = _dispatch(db, transport)

    db.refresh(delivery)
    assert summary.succeeded == 1
    assert delivery.status == DeliveryStatus.SUCCEEDED
    assert delivery.response_status == 204
    assert delivery.attempts == 1
    assert delivery.delivered_at is not None
    assert delivery.error is None


def test_the_delivered_body_is_signed_with_the_subscription_secret(db, org, subscription):
    _enqueue(db, org)
    transport = RecordingTransport()

    _dispatch(db, transport)

    request = transport.requests[0]
    assert request["url"] == subscription.url
    assert verify_signature(SECRET, request["body"], request["headers"][SIGNATURE_HEADER])


def test_the_signature_does_not_verify_under_a_different_secret(db, org, subscription):
    _enqueue(db, org)
    transport = RecordingTransport()

    _dispatch(db, transport)

    request = transport.requests[0]
    assert not verify_signature("b" * 64, request["body"], request["headers"][SIGNATURE_HEADER])


def test_delivery_headers_identify_the_event_and_the_attempt(db, org, subscription):
    delivery = _enqueue(db, org)[0]
    delivery_id = str(delivery.id)
    transport = RecordingTransport()

    _dispatch(db, transport)

    headers = transport.requests[0]["headers"]
    assert headers[EVENT_HEADER] == "task.created"
    assert headers[DELIVERY_HEADER] == delivery_id
    assert headers["Content-Type"] == "application/json"


def test_a_5xx_response_schedules_a_retry(db, org, subscription):
    delivery = _enqueue(db, org)[0]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    summary = _dispatch(db, RecordingTransport(status_code=503), now=now, backoff_base_seconds=60)

    db.refresh(delivery)
    assert summary.retrying == 1
    assert delivery.status == DeliveryStatus.PENDING
    assert delivery.response_status == 503
    assert _as_utc(delivery.next_attempt_at) == now + timedelta(seconds=60)
    assert "503" in delivery.error


def test_a_transport_error_schedules_a_retry(db, org, subscription):
    delivery = _enqueue(db, org)[0]

    _dispatch(db, RecordingTransport(error="ConnectTimeout: too slow"))

    db.refresh(delivery)
    assert delivery.status == DeliveryStatus.PENDING
    assert delivery.response_status is None
    assert "ConnectTimeout" in delivery.error


def test_retries_back_off_exponentially():
    assert backoff_delay(1, 60) == timedelta(seconds=60)
    assert backoff_delay(2, 60) == timedelta(seconds=120)
    assert backoff_delay(3, 60) == timedelta(seconds=240)
    assert backoff_delay(4, 60) == timedelta(seconds=480)


def test_the_backoff_exponent_is_capped():
    assert backoff_delay(100, 1) == backoff_delay(11, 1)


def test_a_delivery_fails_permanently_once_attempts_are_exhausted(db, org, subscription):
    delivery = _enqueue(db, org)[0]
    transport = RecordingTransport(status_code=500)

    for _ in range(3):
        attempt_delivery(db, transport, delivery, max_attempts=3, verify_target=False)

    db.refresh(delivery)
    assert delivery.status == DeliveryStatus.FAILED
    assert delivery.attempts == 3
    assert delivery.next_attempt_at is None


def test_a_delivery_is_not_retried_before_its_next_attempt_is_due(db, org, subscription):
    _enqueue(db, org)
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _dispatch(db, RecordingTransport(status_code=500), now=now)

    transport = RecordingTransport()
    summary = _dispatch(db, transport, now=now + timedelta(seconds=30))

    assert summary.attempted == 0
    assert transport.requests == []


def test_a_due_delivery_is_retried(db, org, subscription):
    delivery = _enqueue(db, org)[0]
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _dispatch(db, RecordingTransport(status_code=500), now=now)

    summary = _dispatch(db, RecordingTransport(status_code=200), now=now + timedelta(seconds=90))

    db.refresh(delivery)
    assert summary.succeeded == 1
    assert delivery.status == DeliveryStatus.SUCCEEDED
    assert delivery.attempts == 2


def test_a_delivery_for_a_deactivated_subscription_fails_immediately(db, org, subscription):
    delivery = _enqueue(db, org)[0]
    subscription.is_active = False
    db.commit()

    transport = RecordingTransport()
    summary = _dispatch(db, transport)

    db.refresh(delivery)
    assert summary.failed == 1
    assert delivery.status == DeliveryStatus.FAILED
    assert transport.requests == []


def test_a_target_that_now_resolves_internally_is_not_posted_to(db, org, subscription, monkeypatch):
    """The address is re-checked at delivery time, not only at subscribe time."""
    delivery = _enqueue(db, org)[0]
    monkeypatch.setattr(
        "app.services.webhook_delivery_service.resolve_primary_address", lambda url: "10.0.0.9"
    )
    transport = RecordingTransport()

    dispatch_pending(db, transport, verify_target=True)

    db.refresh(delivery)
    assert transport.requests == []
    assert "private or reserved" in delivery.error


def test_dispatch_respects_the_batch_limit(db, org, subscription):
    for index in range(5):
        _enqueue(db, org, data={"n": index})
    db.commit()

    summary = _dispatch(db, RecordingTransport(), limit=2)

    assert summary.attempted == 2


def test_due_deliveries_returns_the_oldest_first(db, org, subscription):
    first = _enqueue(db, org, data={"n": 1})[0]
    second = _enqueue(db, org, data={"n": 2})[0]
    db.commit()

    due = due_deliveries(db)

    assert [item.id for item in due] == [first.id, second.id]


def test_requeue_resets_a_failed_delivery(db, org, subscription):
    delivery = _enqueue(db, org)[0]
    for _ in range(2):
        attempt_delivery(db, RecordingTransport(status_code=500), delivery, max_attempts=2,
                         verify_target=False)
    assert delivery.status == DeliveryStatus.FAILED

    requeue_delivery(db, delivery)

    assert delivery.status == DeliveryStatus.PENDING
    assert delivery.attempts == 0
    assert delivery.error is None
    assert delivery.next_attempt_at is None
