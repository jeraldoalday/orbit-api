"""create invitations

Revision ID: ceaceae7afcd
Revises: d13d65048453
Create Date: 2026-08-12 00:00:01.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = 'ceaceae7afcd'
down_revision: Union[str, None] = 'd13d65048453'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('invitations',
    sa.Column('organization_id', sa.UUID(), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column(
        'role',
        postgresql.ENUM('OWNER', 'ADMIN', 'MEMBER', name='membership_role', create_type=False),
        nullable=False,
    ),
    sa.Column('token', sa.String(length=64), nullable=False),
    sa.Column('invited_by_id', sa.UUID(), nullable=True),
    sa.Column('status', sa.Enum('PENDING', 'ACCEPTED', 'REVOKED', name='invitation_status'), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('accepted_by_id', sa.UUID(), nullable=True),
    sa.Column('id', sa.UUID(), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['accepted_by_id'], ['users.id'], name=op.f('fk_invitations_accepted_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['invited_by_id'], ['users.id'], name=op.f('fk_invitations_invited_by_id_users'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], name=op.f('fk_invitations_organization_id_organizations'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_invitations')),
    sa.UniqueConstraint('token', name=op.f('uq_invitations_token'))
    )
    op.create_index(op.f('ix_invitations_email'), 'invitations', ['email'], unique=False)
    op.create_index(op.f('ix_invitations_organization_id'), 'invitations', ['organization_id'], unique=False)
    op.create_index(op.f('ix_invitations_token'), 'invitations', ['token'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_invitations_token'), table_name='invitations')
    op.drop_index(op.f('ix_invitations_organization_id'), table_name='invitations')
    op.drop_index(op.f('ix_invitations_email'), table_name='invitations')
    op.drop_table('invitations')
