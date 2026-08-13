"""add task filter indexes and membership user index

Revision ID: fa666d3d9ae1
Revises: ceaceae7afcd
Create Date: 2026-08-13 18:25:36.187217

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'fa666d3d9ae1'
down_revision: Union[str, None] = 'ceaceae7afcd'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(op.f('ix_tasks_status'), 'tasks', ['status'], unique=False)
    op.create_index(op.f('ix_tasks_assignee_id'), 'tasks', ['assignee_id'], unique=False)
    op.create_index(op.f('ix_memberships_user_id'), 'memberships', ['user_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_memberships_user_id'), table_name='memberships')
    op.drop_index(op.f('ix_tasks_assignee_id'), table_name='tasks')
    op.drop_index(op.f('ix_tasks_status'), table_name='tasks')
