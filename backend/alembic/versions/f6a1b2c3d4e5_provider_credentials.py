"""provider_credentials

Revision ID: f6a1b2c3d4e5
Revises: e5f6a1b2c3d4
Create Date: 2026-06-01

BYOK vault — encrypted provider API keys per user.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'f6a1b2c3d4e5'
down_revision: Union[str, Sequence[str], None] = 'e5f6a1b2c3d4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'provider_credentials',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('provider', sa.String(), nullable=False),
        sa.Column('key_label', sa.String(), nullable=False),
        sa.Column('ciphertext', sa.Text(), nullable=False),
        sa.Column('status', sa.String(), nullable=False, server_default='active'),
        sa.Column('last_used', sa.DateTime(timezone=True), nullable=True),
        sa.Column('rl_cooldown_until', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('user_id', 'provider', 'key_label', name='uq_cred_user_provider_label'),
    )
    op.create_index('idx_cred_user', 'provider_credentials', ['user_id'])


def downgrade() -> None:
    op.drop_index('idx_cred_user', table_name='provider_credentials')
    op.drop_table('provider_credentials')
