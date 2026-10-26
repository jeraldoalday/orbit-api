"""add comment.deleted webhook event

Revision ID: b4a1f9c2d3e7
Revises: 8f35ba8263a4
Create Date: 2026-10-26 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4a1f9c2d3e7"
down_revision: Union[str, None] = "8f35ba8263a4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ADD VALUE can't run inside a transaction block on older Postgres, and
    # Alembic wraps migrations in one, so the value is added with COMMIT
    # around it rather than through op.execute alone.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE webhook_event ADD VALUE IF NOT EXISTS 'COMMENT_DELETED'")


def downgrade() -> None:
    # Postgres has no "remove a value from an enum" either; downgrading would
    # require rebuilding the type the way the task_watchers migration does for
    # notification_type, which isn't worth it for a value no row should ever
    # be using by the time anyone downgrades past it.
    pass
