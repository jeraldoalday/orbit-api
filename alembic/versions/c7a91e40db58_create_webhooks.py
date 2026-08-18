"""create webhook subscriptions and deliveries

Revision ID: c7a91e40db58
Revises: b3f2c81d47ae
Create Date: 2026-08-18 19:04:47.208311

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "c7a91e40db58"
down_revision: Union[str, None] = "b3f2c81d47ae"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

webhook_event = sa.Enum(
    "TASK_CREATED",
    "TASK_UPDATED",
    "TASK_DELETED",
    "TASK_ASSIGNED",
    "COMMENT_CREATED",
    name="webhook_event",
)
delivery_status = sa.Enum("PENDING", "SUCCEEDED", "FAILED", name="webhook_delivery_status")


def upgrade() -> None:
    op.create_table(
        "webhook_subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("url", sa.String(length=2048), nullable=False),
        sa.Column("description", sa.String(length=200), nullable=True),
        sa.Column("events", sa.JSON(), nullable=False),
        sa.Column("secret", sa.String(length=128), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_webhook_subscriptions_organization_id",
        "webhook_subscriptions",
        ["organization_id"],
        unique=False,
    )

    op.create_table(
        "webhook_deliveries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("subscription_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_type", webhook_event, nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("status", delivery_status, nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["webhook_subscriptions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_webhook_deliveries_subscription_id",
        "webhook_deliveries",
        ["subscription_id"],
        unique=False,
    )
    op.create_index("ix_webhook_deliveries_status", "webhook_deliveries", ["status"], unique=False)
    # The worker's hot path: pending rows whose next attempt is due.
    op.create_index(
        "ix_webhook_deliveries_status_next_attempt",
        "webhook_deliveries",
        ["status", "next_attempt_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_deliveries_status_next_attempt", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_status", table_name="webhook_deliveries")
    op.drop_index("ix_webhook_deliveries_subscription_id", table_name="webhook_deliveries")
    op.drop_table("webhook_deliveries")

    op.drop_index("ix_webhook_subscriptions_organization_id", table_name="webhook_subscriptions")
    op.drop_table("webhook_subscriptions")

    # Enum types outlive their tables in Postgres and would collide on a
    # re-upgrade, so drop them explicitly.
    delivery_status.drop(op.get_bind(), checkfirst=True)
    webhook_event.drop(op.get_bind(), checkfirst=True)
