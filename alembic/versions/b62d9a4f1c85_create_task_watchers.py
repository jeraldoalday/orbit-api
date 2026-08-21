"""create task watchers

Revision ID: b62d9a4f1c85
Revises: a1c74e2b9f30
Create Date: 2026-08-22 10:41:52.904118

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b62d9a4f1c85"
down_revision: Union[str, None] = "a1c74e2b9f30"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Postgres has no "remove a value from an enum", so the downgrade rebuilds the
# type without TASK_UPDATED. Rows carrying the value have to go first, or the
# cast that rewrites the column fails on them.
_OLD_NOTIFICATION_TYPES = ("TASK_ASSIGNED", "TASK_COMMENTED", "MENTIONED")


def upgrade() -> None:
    op.create_table(
        "task_watchers",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", "user_id", name="uq_task_watcher_task_user"),
    )
    op.create_index("ix_task_watchers_task_id", "task_watchers", ["task_id"])
    op.create_index("ix_task_watchers_user_id", "task_watchers", ["user_id"])

    # ADD VALUE can't run inside a transaction block on older Postgres, and
    # Alembic wraps migrations in one, so the value is added with COMMIT
    # around it rather than through op.execute alone.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'TASK_UPDATED'")


def downgrade() -> None:
    values = ", ".join(f"'{value}'" for value in _OLD_NOTIFICATION_TYPES)
    op.execute("DELETE FROM notifications WHERE notification_type = 'TASK_UPDATED'")
    op.execute(f"CREATE TYPE notification_type_old AS ENUM ({values})")
    op.execute(
        "ALTER TABLE notifications ALTER COLUMN notification_type "
        "TYPE notification_type_old USING notification_type::text::notification_type_old"
    )
    op.execute("DROP TYPE notification_type")
    op.execute("ALTER TYPE notification_type_old RENAME TO notification_type")

    op.drop_index("ix_task_watchers_user_id", table_name="task_watchers")
    op.drop_index("ix_task_watchers_task_id", table_name="task_watchers")
    op.drop_table("task_watchers")
