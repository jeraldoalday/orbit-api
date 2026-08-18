"""add trigram indexes for search

Revision ID: e4d8b3c17f60
Revises: c92f14aa77e1
Create Date: 2026-08-18 12:05:31.774219

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "e4d8b3c17f60"
down_revision: Union[str, None] = "c92f14aa77e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Search matches with LIKE '%term%'. A btree index can't serve a leading
# wildcard, so plain indexes on these columns would be dead weight and every
# query would fall back to a sequential scan. GIN + pg_trgm is the index type
# Postgres can actually use for infix matching.
def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    op.create_index(
        "ix_tasks_title_trgm",
        "tasks",
        [sa.text("lower(title) gin_trgm_ops")],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_tasks_description_trgm",
        "tasks",
        [sa.text("lower(description) gin_trgm_ops")],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_projects_name_trgm",
        "projects",
        [sa.text("lower(name) gin_trgm_ops")],
        postgresql_using="gin",
    )
    op.create_index(
        "ix_projects_description_trgm",
        "projects",
        [sa.text("lower(description) gin_trgm_ops")],
        postgresql_using="gin",
    )

    # Search filters tasks by their project's org before ranking, so the join
    # side benefits from covering (organization_id, id) on projects.
    op.create_index(
        "ix_projects_organization_id_id", "projects", ["organization_id", "id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_projects_organization_id_id", table_name="projects")
    op.drop_index("ix_projects_description_trgm", table_name="projects")
    op.drop_index("ix_projects_name_trgm", table_name="projects")
    op.drop_index("ix_tasks_description_trgm", table_name="tasks")
    op.drop_index("ix_tasks_title_trgm", table_name="tasks")

    # The extension is left in place: other objects may depend on it, and
    # dropping it would be a surprising side effect of reverting one migration.
