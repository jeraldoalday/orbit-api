"""add soft delete to projects and tasks

Revision ID: d5f04b7c2e19
Revises: c7a91e40db58
Create Date: 2026-08-18 20:11:52.664218

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d5f04b7c2e19"
down_revision: Union[str, None] = "c7a91e40db58"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Every read of these tables now filters on deleted_at IS NULL, so the column
# is indexed rather than left to a sequential scan. Existing rows are live, and
# NULL is exactly that, so no backfill is needed.
def upgrade() -> None:
    op.add_column("projects", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_projects_deleted_at", "projects", ["deleted_at"], unique=False)

    op.add_column("tasks", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_tasks_deleted_at", "tasks", ["deleted_at"], unique=False)

    # The task list is always scoped to one project and now always excludes
    # deleted rows, so the pair is worth covering together.
    op.create_index(
        "ix_tasks_project_id_deleted_at", "tasks", ["project_id", "deleted_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_project_id_deleted_at", table_name="tasks")
    op.drop_index("ix_tasks_deleted_at", table_name="tasks")
    op.drop_column("tasks", "deleted_at")

    op.drop_index("ix_projects_deleted_at", table_name="projects")
    op.drop_column("projects", "deleted_at")
