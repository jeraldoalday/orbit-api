"""create time entries

Revision ID: e17b4d8f60a2
Revises: d92e5c3a71f8
Create Date: 2026-09-05 11:20:07.318645

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "e17b4d8f60a2"
down_revision: Union[str, None] = "d92e5c3a71f8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("estimate_minutes", sa.Integer(), nullable=True))

    op.create_table(
        "time_entries",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("minutes", sa.Integer(), nullable=False),
        sa.Column("spent_on", sa.Date(), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        # SET NULL: the hours were worked whether or not the person who logged
        # them still has an account.
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_time_entries_task_id", "time_entries", ["task_id"])
    op.create_index("ix_time_entries_user_id", "time_entries", ["user_id"])
    op.create_index("ix_time_entries_spent_on", "time_entries", ["spent_on"])
    # Every report is "a range of days, grouped".
    op.create_index("ix_time_entries_task_spent_on", "time_entries", ["task_id", "spent_on"])


def downgrade() -> None:
    op.drop_index("ix_time_entries_task_spent_on", table_name="time_entries")
    op.drop_index("ix_time_entries_spent_on", table_name="time_entries")
    op.drop_index("ix_time_entries_user_id", table_name="time_entries")
    op.drop_index("ix_time_entries_task_id", table_name="time_entries")
    op.drop_table("time_entries")

    op.drop_column("tasks", "estimate_minutes")
