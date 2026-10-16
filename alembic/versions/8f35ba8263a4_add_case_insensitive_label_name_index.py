"""add case-insensitive label name index

Revision ID: 8f35ba8263a4
Revises: e17b4d8f60a2
Create Date: 2026-10-16 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "8f35ba8263a4"
down_revision: Union[str, None] = "e17b4d8f60a2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # `uq_label_org_name` only rejects an exact-case repeat, so two requests
    # racing each other can each pass the service's case-insensitive check
    # before either commits, leaving an org with both "Bug" and "bug". This
    # index makes the rejection hold under that race by enforcing it in the
    # database the service's IntegrityError handler already expects.
    op.create_index(
        "uq_label_org_name_ci",
        "labels",
        ["organization_id", sa.text("lower(name)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_label_org_name_ci", table_name="labels")
