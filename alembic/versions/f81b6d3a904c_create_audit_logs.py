"""create audit logs

Revision ID: f81b6d3a904c
Revises: d5f04b7c2e19
Create Date: 2026-08-18 21:02:19.437110

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "f81b6d3a904c"
down_revision: Union[str, None] = "d5f04b7c2e19"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

audit_action = sa.Enum(
    "PROJECT_CREATED",
    "PROJECT_UPDATED",
    "PROJECT_DELETED",
    "PROJECT_RESTORED",
    "PROJECT_PURGED",
    "TASK_DELETED",
    "TASK_RESTORED",
    "TASK_PURGED",
    "MEMBER_ADDED",
    "MEMBER_ROLE_CHANGED",
    "MEMBER_REMOVED",
    "WEBHOOK_CREATED",
    "WEBHOOK_UPDATED",
    "WEBHOOK_DELETED",
    "WEBHOOK_SECRET_ROTATED",
    name="audit_action",
)
audit_resource = sa.Enum("PROJECT", "TASK", "MEMBERSHIP", "WEBHOOK", name="audit_resource")


def upgrade() -> None:
    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("organization_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_email", sa.String(length=255), nullable=True),
        sa.Column("action", audit_action, nullable=False),
        sa.Column("resource_type", audit_resource, nullable=False),
        # No foreign key on resource_id, deliberately: the entry has to outlive
        # the row it describes, which is the whole point of a purge record.
        sa.Column("resource_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["organization_id"], ["organizations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_audit_logs_organization_id", "audit_logs", ["organization_id"], unique=False
    )
    op.create_index("ix_audit_logs_actor_id", "audit_logs", ["actor_id"], unique=False)
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"], unique=False)
    op.create_index(
        "ix_audit_logs_org_created", "audit_logs", ["organization_id", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_audit_logs_org_created", table_name="audit_logs")
    op.drop_index("ix_audit_logs_action", table_name="audit_logs")
    op.drop_index("ix_audit_logs_actor_id", table_name="audit_logs")
    op.drop_index("ix_audit_logs_organization_id", table_name="audit_logs")
    op.drop_table("audit_logs")

    audit_resource.drop(op.get_bind(), checkfirst=True)
    audit_action.drop(op.get_bind(), checkfirst=True)
