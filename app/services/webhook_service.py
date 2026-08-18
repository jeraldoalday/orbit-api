import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.webhook_signing import generate_secret
from app.core.webhook_url import validate_webhook_url
from app.models.audit_log import AuditAction, AuditResource
from app.models.organization import Organization
from app.models.user import User
from app.models.webhook import WebhookEvent, WebhookSubscription
from app.schemas.webhook import WebhookSubscriptionCreate, WebhookSubscriptionUpdate
from app.services.audit_service import record_audit


class SubscriptionLimitError(Exception):
    """Raised when an organization already has as many subscriptions as it may."""


def _audit(
    db: Session,
    subscription: WebhookSubscription,
    action: AuditAction,
    actor: Optional[User],
    data: Optional[dict] = None,
) -> None:
    record_audit(
        db,
        organization_id=subscription.organization_id,
        action=action,
        resource_type=AuditResource.WEBHOOK,
        actor=actor,
        resource_id=subscription.id,
        data=data,
    )


def count_subscriptions(db: Session, organization_id: uuid.UUID) -> int:
    stmt = (
        select(func.count())
        .select_from(WebhookSubscription)
        .where(WebhookSubscription.organization_id == organization_id)
    )
    return db.execute(stmt).scalar_one()


def create_subscription(
    db: Session,
    organization: Organization,
    subscription_in: WebhookSubscriptionCreate,
    *,
    actor: Optional[User] = None,
    require_https: bool = False,
    resolve_dns: bool = True,
    max_per_org: int = 10,
) -> WebhookSubscription:
    if count_subscriptions(db, organization.id) >= max_per_org:
        raise SubscriptionLimitError(
            f"An organization may have at most {max_per_org} webhook subscriptions"
        )

    url = validate_webhook_url(
        subscription_in.url, require_https=require_https, resolve=resolve_dns
    )

    subscription = WebhookSubscription(
        organization_id=organization.id,
        url=url,
        description=subscription_in.description,
        events=[event.value for event in subscription_in.events],
        secret=generate_secret(),
        is_active=True,
    )
    db.add(subscription)
    db.flush()
    _audit(db, subscription, AuditAction.WEBHOOK_CREATED, actor, {"url": subscription.url})
    db.commit()
    db.refresh(subscription)
    return subscription


def get_subscription(
    db: Session, organization_id: uuid.UUID, subscription_id: uuid.UUID
) -> Optional[WebhookSubscription]:
    stmt = select(WebhookSubscription).where(
        WebhookSubscription.id == subscription_id,
        WebhookSubscription.organization_id == organization_id,
    )
    return db.execute(stmt).scalar_one_or_none()


def list_subscriptions(
    db: Session, organization_id: uuid.UUID, *, limit: int = 50, offset: int = 0
) -> list[WebhookSubscription]:
    stmt = (
        select(WebhookSubscription)
        .where(WebhookSubscription.organization_id == organization_id)
        .order_by(WebhookSubscription.created_at, WebhookSubscription.id)
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def list_subscribers(
    db: Session, organization_id: uuid.UUID, event: WebhookEvent
) -> list[WebhookSubscription]:
    """Active subscriptions in an org that want ``event``.

    The events array is filtered in Python rather than in SQL: JSON containment
    is spelled differently on every backend, the list per org is small, and
    this keeps the same behaviour under SQLite in tests and Postgres in
    production.
    """
    stmt = select(WebhookSubscription).where(
        WebhookSubscription.organization_id == organization_id,
        WebhookSubscription.is_active.is_(True),
    )
    return [
        subscription
        for subscription in db.execute(stmt).scalars().all()
        if subscription.subscribes_to(event)
    ]


def update_subscription(
    db: Session,
    subscription: WebhookSubscription,
    subscription_in: WebhookSubscriptionUpdate,
    *,
    actor: Optional[User] = None,
    require_https: bool = False,
    resolve_dns: bool = True,
) -> WebhookSubscription:
    fields_set = subscription_in.model_fields_set

    if subscription_in.url is not None:
        subscription.url = validate_webhook_url(
            subscription_in.url, require_https=require_https, resolve=resolve_dns
        )
    if subscription_in.events is not None:
        subscription.events = [event.value for event in subscription_in.events]
    if "description" in fields_set:
        subscription.description = subscription_in.description
    if subscription_in.is_active is not None:
        subscription.is_active = subscription_in.is_active

    _audit(
        db,
        subscription,
        AuditAction.WEBHOOK_UPDATED,
        actor,
        {"fields": sorted(fields_set)},
    )
    db.commit()
    db.refresh(subscription)
    return subscription


def rotate_secret(
    db: Session, subscription: WebhookSubscription, actor: Optional[User] = None
) -> WebhookSubscription:
    """Issue a new secret, invalidating the old one immediately.

    There is deliberately no overlap window: a leaked secret has to stop
    working the moment it's rotated, and a receiver that verifies signatures
    can be updated with the new value before rotating.
    """
    subscription.secret = generate_secret()
    # The new secret is deliberately not in the audit entry: an audit trail
    # that records credentials is a second place to steal them from.
    _audit(db, subscription, AuditAction.WEBHOOK_SECRET_ROTATED, actor)
    db.commit()
    db.refresh(subscription)
    return subscription


def delete_subscription(
    db: Session, subscription: WebhookSubscription, actor: Optional[User] = None
) -> None:
    _audit(db, subscription, AuditAction.WEBHOOK_DELETED, actor, {"url": subscription.url})
    db.delete(subscription)
    db.commit()
