"""add task priority and due date

Revision ID: a325d59a1759
Revises: fa666d3d9ae1
Create Date: 2026-08-15 20:15:08.159232

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "a325d59a1759"
down_revision: Union[str, None] = "fa666d3d9ae1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    task_priority = sa.Enum("LOW", "MEDIUM", "HIGH", "URGENT", name="task_priority")
    task_priority.create(op.get_bind(), checkfirst=True)

    op.add_column(
        "tasks",
        sa.Column("priority", task_priority, nullable=False, server_default="MEDIUM"),
    )
    op.alter_column("tasks", "priority", server_default=None)
    op.create_index(op.f("ix_tasks_priority"), "tasks", ["priority"], unique=False)

    op.add_column("tasks", sa.Column("due_date", sa.DateTime(timezone=True), nullable=True))
    op.create_index(op.f("ix_tasks_due_date"), "tasks", ["due_date"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_tasks_due_date"), table_name="tasks")
    op.drop_column("tasks", "due_date")

    op.drop_index(op.f("ix_tasks_priority"), table_name="tasks")
    op.drop_column("tasks", "priority")

    sa.Enum(name="task_priority").drop(op.get_bind(), checkfirst=True)
