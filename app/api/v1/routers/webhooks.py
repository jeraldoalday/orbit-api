import uuid
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.deps import get_current_active_user, get_organization_or_404, require_org_role
from app.core.config import get_settings
from app.core.webhook_url import InvalidWebhookUrlError
from app.db.session import get_db
from app.models.membership import Membership, MembershipRole
from app.models.organization import Organization
from app.models.user import User
from app.models.webhook import DeliveryStatus, WebhookDelivery, WebhookSubscription
from app.schemas.webhook import (
    WebhookDeliveryRead,
    WebhookDeliveryWithPayload,
    WebhookSubscriptionCreate,
    WebhookSubscriptionRead,
    WebhookSubscriptionUpdate,
    WebhookSubscriptionWithSecret,
)
from app.services.webhook_delivery_service import (
    get_delivery,
    list_deliveries,
    requeue_delivery,
)
from app.services.webhook_service import (
    SubscriptionLimitError,
    create_subscription,
    delete_subscription,
    get_subscription,
    list_subscriptions,
    rotate_secret,
    update_subscription,
)

settings = get_settings()

# Webhooks are an org-wide integration point: a subscription can observe every
# project in the org, including restricted ones, so managing them is limited to
# org admins rather than anyone who can edit a project.
router = APIRouter(
    prefix="/organizations/{org_id}/webhooks",
    tags=["webhooks"],
    dependencies=[Depends(require_org_role(MembershipRole.ADMIN))],
)


def get_subscription_or_404(
    subscription_id: uuid.UUID,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
) -> WebhookSubscription:
    subscription = get_subscription(db, organization.id, subscription_id)
    if subscription is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Webhook subscription not found"
        )
    return subscription


@router.post("", response_model=WebhookSubscriptionWithSecret, status_code=status.HTTP_201_CREATED)
def create(
    subscription_in: WebhookSubscriptionCreate,
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    current_user: User = Depends(get_current_active_user),
) -> WebhookSubscriptionWithSecret:
    try:
        return create_subscription(
            db,
            organization,
            subscription_in,
            actor=current_user,
            require_https=settings.is_production,
            resolve_dns=settings.webhook_validate_dns,
            max_per_org=settings.webhook_max_per_org,
        )
    except InvalidWebhookUrlError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc
    except SubscriptionLimitError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc


@router.get("", response_model=list[WebhookSubscriptionRead])
def list_for_org(
    db: Session = Depends(get_db),
    organization: Organization = Depends(get_organization_or_404),
    limit: int = Query(default=settings.list_default_limit, ge=1, le=settings.list_max_limit),
    offset: int = Query(default=0, ge=0),
) -> list[WebhookSubscriptionRead]:
    return list_subscriptions(db, organization.id, limit=limit, offset=offset)


@router.get("/{subscription_id}", response_model=WebhookSubscriptionRead)
def get(
    subscription: WebhookSubscription = Depends(get_subscription_or_404),
) -> WebhookSubscriptionRead:
    return subscription


@router.patch("/{subscription_id}", response_model=WebhookSubscriptionRead)
def update(
    subscription_in: WebhookSubscriptionUpdate,
    db: Session = Depends(get_db),
    subscription: WebhookSubscription = Depends(get_subscription_or_404),
    current_user: User = Depends(get_current_active_user),
) -> WebhookSubscriptionRead:
    try:
        return update_subscription(
            db,
            subscription,
            subscription_in,
            actor=current_user,
            require_https=settings.is_production,
            resolve_dns=settings.webhook_validate_dns,
        )
    except InvalidWebhookUrlError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
        ) from exc


@router.post("/{subscription_id}/rotate_secret", response_model=WebhookSubscriptionWithSecret)
def rotate(
    db: Session = Depends(get_db),
    subscription: WebhookSubscription = Depends(get_subscription_or_404),
    _membership: Membership = Depends(require_org_role(MembershipRole.OWNER)),
    current_user: User = Depends(get_current_active_user),
) -> WebhookSubscriptionWithSecret:
    return rotate_secret(db, subscription, current_user)


@router.delete("/{subscription_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete(
    db: Session = Depends(get_db),
    subscription: WebhookSubscription = Depends(get_subscription_or_404),
    current_user: User = Depends(get_current_active_user),
) -> None:
    delete_subscription(db, subscription, current_user)


def _get_delivery_or_404(
    delivery_id: uuid.UUID,
    db: Session = Depends(get_db),
    subscription: WebhookSubscription = Depends(get_subscription_or_404),
) -> WebhookDelivery:
    delivery = get_delivery(db, subscription.id, delivery_id)
    if delivery is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Delivery not found")
    return delivery


@router.get("/{subscription_id}/deliveries", response_model=list[WebhookDeliveryRead])
def list_subscription_deliveries(
    db: Session = Depends(get_db),
    subscription: WebhookSubscription = Depends(get_subscription_or_404),
    delivery_status: Optional[DeliveryStatus] = Query(default=None, alias="status"),
    limit: int = Query(default=settings.list_default_limit, ge=1, le=settings.list_max_limit),
    offset: int = Query(default=0, ge=0),
) -> list[WebhookDeliveryRead]:
    return list_deliveries(
        db, subscription.id, status=delivery_status, limit=limit, offset=offset
    )


@router.get(
    "/{subscription_id}/deliveries/{delivery_id}", response_model=WebhookDeliveryWithPayload
)
def get_subscription_delivery(
    delivery: WebhookDelivery = Depends(_get_delivery_or_404),
) -> WebhookDeliveryWithPayload:
    # The single-delivery view includes the payload so an operator debugging a
    # failing endpoint can see exactly what was sent.
    return delivery


@router.post(
    "/{subscription_id}/deliveries/{delivery_id}/retry", response_model=WebhookDeliveryRead
)
def retry_subscription_delivery(
    db: Session = Depends(get_db),
    delivery: WebhookDelivery = Depends(_get_delivery_or_404),
) -> WebhookDeliveryRead:
    return requeue_delivery(db, delivery)
