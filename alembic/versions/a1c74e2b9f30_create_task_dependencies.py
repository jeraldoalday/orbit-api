"""create task dependencies

Revision ID: a1c74e2b9f30
Revises: f81b6d3a904c
Create Date: 2026-08-22 09:12:04.118273

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a1c74e2b9f30"
down_revision: Union[str, None] = "f81b6d3a904c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "task_dependencies",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("depends_on_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["depends_on_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # Re-adding an existing edge is a no-op rather than a duplicate row,
        # and the constraint keeps that true when two requests race.
        sa.UniqueConstraint("task_id", "depends_on_id", name="uq_task_dependency_task_depends_on"),
    )
    # The graph is walked in both directions: a task's blockers, and everything
    # blocked by it, so neither column can rely on the other's index.
    op.create_index("ix_task_dependencies_task_id", "task_dependencies", ["task_id"])
    op.create_index("ix_task_dependencies_depends_on_id", "task_dependencies", ["depends_on_id"])


def downgrade() -> None:
    op.drop_index("ix_task_dependencies_depends_on_id", table_name="task_dependencies")
    op.drop_index("ix_task_dependencies_task_id", table_name="task_dependencies")
    op.drop_table("task_dependencies")
