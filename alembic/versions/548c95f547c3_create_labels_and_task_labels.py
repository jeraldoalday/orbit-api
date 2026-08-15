"""create labels and task labels

Revision ID: 548c95f547c3
Revises: a325d59a1759
Create Date: 2026-08-15 20:23:08.480170

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "548c95f547c3"
down_revision: Union[str, None] = "a325d59a1759"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "labels",
        sa.Column("organization_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("color", sa.String(length=7), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_labels_organization_id_organizations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_labels")),
        sa.UniqueConstraint("organization_id", "name", name="uq_label_org_name"),
    )
    op.create_index(op.f("ix_labels_organization_id"), "labels", ["organization_id"], unique=False)

    op.create_table(
        "task_labels",
        sa.Column("task_id", sa.UUID(), nullable=False),
        sa.Column("label_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["label_id"],
            ["labels.id"],
            name=op.f("fk_task_labels_label_id_labels"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["task_id"], ["tasks.id"], name=op.f("fk_task_labels_task_id_tasks"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("task_id", "label_id", name=op.f("pk_task_labels")),
    )
    op.create_index(op.f("ix_task_labels_label_id"), "task_labels", ["label_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_task_labels_label_id"), table_name="task_labels")
    op.drop_table("task_labels")

    op.drop_index(op.f("ix_labels_organization_id"), table_name="labels")
    op.drop_table("labels")
