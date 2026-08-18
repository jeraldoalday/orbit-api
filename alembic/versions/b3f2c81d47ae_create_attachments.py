"""create attachments

Revision ID: b3f2c81d47ae
Revises: e4d8b3c17f60
Create Date: 2026-08-18 18:22:04.113905

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "b3f2c81d47ae"
down_revision: Union[str, None] = "e4d8b3c17f60"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "attachments",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("uploaded_by_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        # BigInteger because a 32-bit column caps a single file at 2 GiB, and
        # widening a populated column later needs a table rewrite.
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("storage_key", sa.String(length=512), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["uploaded_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key", name="uq_attachments_storage_key"),
    )
    op.create_index("ix_attachments_task_id", "attachments", ["task_id"], unique=False)
    op.create_index(
        "ix_attachments_task_created", "attachments", ["task_id", "created_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_attachments_task_created", table_name="attachments")
    op.drop_index("ix_attachments_task_id", table_name="attachments")
    op.drop_table("attachments")
