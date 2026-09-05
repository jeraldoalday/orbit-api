"""create milestones

Revision ID: d92e5c3a71f8
Revises: c4a17f9b2e63
Create Date: 2026-09-05 10:04:18.771903

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "d92e5c3a71f8"
down_revision: Union[str, None] = "c4a17f9b2e63"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "milestones",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_milestones_project_id", "milestones", ["project_id"])
    op.create_index("ix_milestones_due_date", "milestones", ["due_date"])

    op.add_column("tasks", sa.Column("milestone_id", postgresql.UUID(as_uuid=True), nullable=True))
    op.create_index("ix_tasks_milestone_id", "tasks", ["milestone_id"])
    # SET NULL: deleting a milestone unfiles its tasks rather than deleting
    # them, which is what makes the grouping safe to throw away.
    op.create_foreign_key(
        "fk_tasks_milestone_id_milestones",
        "tasks",
        "milestones",
        ["milestone_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_tasks_milestone_id_milestones", "tasks", type_="foreignkey")
    op.drop_index("ix_tasks_milestone_id", table_name="tasks")
    op.drop_column("tasks", "milestone_id")

    op.drop_index("ix_milestones_due_date", table_name="milestones")
    op.drop_index("ix_milestones_project_id", table_name="milestones")
    op.drop_table("milestones")
