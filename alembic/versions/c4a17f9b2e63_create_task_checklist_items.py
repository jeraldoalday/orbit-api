"""create task checklist items

Revision ID: c4a17f9b2e63
Revises: b62d9a4f1c85
Create Date: 2026-09-05 09:12:31.442017

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "c4a17f9b2e63"
down_revision: Union[str, None] = "b62d9a4f1c85"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_checklist_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content", sa.String(length=200), nullable=False),
        sa.Column("is_done", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_task_checklist_items_task_id", "task_checklist_items", ["task_id"])
    # The list is only ever read as "one task's items, in order".
    op.create_index(
        "ix_task_checklist_items_task_position", "task_checklist_items", ["task_id", "position"]
    )


def downgrade() -> None:
    op.drop_index("ix_task_checklist_items_task_position", table_name="task_checklist_items")
    op.drop_index("ix_task_checklist_items_task_id", table_name="task_checklist_items")
    op.drop_table("task_checklist_items")
