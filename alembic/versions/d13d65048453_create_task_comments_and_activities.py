"""create task comments and activities

Revision ID: d13d65048453
Revises: 28c3f3fe0f02
Create Date: 2026-08-12 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd13d65048453'
down_revision: Union[str, None] = '28c3f3fe0f02'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('task_comments',
    sa.Column('task_id', sa.UUID(), nullable=False),
    sa.Column('author_id', sa.UUID(), nullable=True),
    sa.Column('body', sa.Text(), nullable=False),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['author_id'], ['users.id'], name=op.f('fk_task_comments_author_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], name=op.f('fk_task_comments_task_id_tasks'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_task_comments'))
    )
    op.create_index(op.f('ix_task_comments_task_id'), 'task_comments', ['task_id'], unique=False)
    op.create_table('task_activities',
    sa.Column('task_id', sa.UUID(), nullable=False),
    sa.Column('actor_id', sa.UUID(), nullable=True),
    sa.Column('activity_type', sa.Enum('CREATED', 'UPDATED', name='task_activity_type'), nullable=False),
    sa.Column('data', sa.JSON(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['actor_id'], ['users.id'], name=op.f('fk_task_activities_actor_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['task_id'], ['tasks.id'], name=op.f('fk_task_activities_task_id_tasks'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_task_activities'))
    )
    op.create_index(op.f('ix_task_activities_task_id'), 'task_activities', ['task_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_task_activities_task_id'), table_name='task_activities')
    op.drop_table('task_activities')
    op.drop_index(op.f('ix_task_comments_task_id'), table_name='task_comments')
    op.drop_table('task_comments')
