"""price_bands

Revision ID: e5f6a1b2c3d4
Revises: d4e5f6a1b2c3
Create Date: 2026-06-01

Adds price_bands table — valuation/chart entry zones for long-term + swing
watchlist alerting (Telegram). One row per (user, sym, category).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e5f6a1b2c3d4'
down_revision: Union[str, Sequence[str], None] = 'd4e5f6a1b2c3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'price_bands',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('sym', sa.String(), nullable=False),
        sa.Column('name', sa.String(), nullable=True),
        sa.Column('category', sa.String(), nullable=False, server_default='long_term'),
        sa.Column('ideal_lo', sa.Numeric(18, 4), nullable=True),
        sa.Column('ideal_hi', sa.Numeric(18, 4), nullable=True),
        sa.Column('accept_lo', sa.Numeric(18, 4), nullable=True),
        sa.Column('accept_hi', sa.Numeric(18, 4), nullable=True),
        sa.Column('sl', sa.Numeric(18, 4), nullable=True),
        sa.Column('target', sa.Numeric(18, 4), nullable=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column('last_alert_zone', sa.String(), nullable=True),
        sa.Column('last_alerted_date', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('user_id', 'sym', 'category', name='uq_price_bands_user_sym_cat'),
    )
    op.create_index('idx_price_bands_user_active', 'price_bands', ['user_id', 'is_active'])


def downgrade() -> None:
    op.drop_index('idx_price_bands_user_active', table_name='price_bands')
    op.drop_table('price_bands')
