"""create project members and project visibility

Revision ID: b71c9a4e5d02
Revises: 548c95f547c3
Create Date: 2026-08-18 09:12:44.108225

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b71c9a4e5d02"
down_revision: Union[str, None] = "548c95f547c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


project_visibility = sa.Enum("OPEN", "RESTRICTED", name="project_visibility")
project_role = sa.Enum("VIEWER", "EDITOR", "MANAGER", name="project_role")


def upgrade() -> None:
    bind = op.get_bind()
    project_visibility.create(bind, checkfirst=True)
    project_role.create(bind, checkfirst=True)

    # Existing projects predate the concept, and every org member could already
    # reach them, so OPEN is the only backfill that preserves current access.
    op.add_column(
        "projects",
        sa.Column("visibility", project_visibility, nullable=False, server_default="OPEN"),
    )
    op.alter_column("projects", "visibility", server_default=None)

    op.create_table(
        "project_members",
        sa.Column("project_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("role", project_role, nullable=False),
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
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_members_project_id_projects"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_project_members_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_members")),
        sa.UniqueConstraint("project_id", "user_id", name="uq_project_member_project_user"),
    )
    op.create_index(
        op.f("ix_project_members_project_id"), "project_members", ["project_id"], unique=False
    )
    op.create_index(
        op.f("ix_project_members_user_id"), "project_members", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_project_members_user_id"), table_name="project_members")
    op.drop_index(op.f("ix_project_members_project_id"), table_name="project_members")
    op.drop_table("project_members")

    op.drop_column("projects", "visibility")

    bind = op.get_bind()
    project_role.drop(bind, checkfirst=True)
    project_visibility.drop(bind, checkfirst=True)
