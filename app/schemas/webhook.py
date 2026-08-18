import uuid
from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models.webhook import DeliveryStatus, WebhookEvent
from app.schemas.fields import MAX_NAME_LENGTH, NonBlankStr


class WebhookSubscriptionCreate(BaseModel):
    url: str = Field(min_length=1, max_length=2048)
    events: list[WebhookEvent] = Field(min_length=1)
    description: Optional[NonBlankStr] = Field(default=None, max_length=MAX_NAME_LENGTH)

    @field_validator("events")
    @classmethod
    def _deduplicate(cls, events: list[WebhookEvent]) -> list[WebhookEvent]:
        """Subscribing to the same event twice would deliver it twice."""
        return list(dict.fromkeys(events))


class WebhookSubscriptionUpdate(BaseModel):
    url: Optional[str] = Field(default=None, min_length=1, max_length=2048)
    events: Optional[list[WebhookEvent]] = Field(default=None, min_length=1)
    description: Optional[NonBlankStr] = Field(default=None, max_length=MAX_NAME_LENGTH)
    is_active: Optional[bool] = None

    @field_validator("events")
    @classmethod
    def _deduplicate(cls, events: Optional[list[WebhookEvent]]) -> Optional[list[WebhookEvent]]:
        return None if events is None else list(dict.fromkeys(events))


class WebhookSubscriptionRead(BaseModel):
    """The safe view: everything except the secret."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    url: str
    description: Optional[str]
    events: list[str]
    is_active: bool
    created_at: datetime
    updated_at: datetime


class WebhookSubscriptionWithSecret(WebhookSubscriptionRead):
    """Returned only at creation and rotation — the secret is never re-readable."""

    secret: str


class WebhookDeliveryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    subscription_id: uuid.UUID
    event_type: WebhookEvent
    status: DeliveryStatus
    attempts: int
    response_status: Optional[int]
    error: Optional[str]
    next_attempt_at: Optional[datetime]
    delivered_at: Optional[datetime]
    created_at: datetime


class WebhookDeliveryWithPayload(WebhookDeliveryRead):
    payload: dict[str, Any]


class WebhookDispatchResult(BaseModel):
    """What one worker pass did."""

    attempted: int
    succeeded: int
    failed: int
    retrying: int
