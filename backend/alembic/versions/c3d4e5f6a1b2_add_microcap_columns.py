"""add_microcap_columns

Revision ID: c3d4e5f6a1b2
Revises: 678ababf3e9b
Create Date: 2026-05-27 12:00:00.000000

Adds:
  - stock_master.is_microcap_idx (NIFTY Microcap 250 membership flag)
  - scan_picks.is_microcap (pick came from microcap index universe)
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'c3d4e5f6a1b2'
down_revision: Union[str, Sequence[str], None] = '678ababf3e9b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('stock_master',
        sa.Column('is_microcap_idx', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('scan_picks',
        sa.Column('is_microcap', sa.Boolean(), nullable=False, server_default='false'))


def downgrade() -> None:
    op.drop_column('stock_master', 'is_microcap_idx')
    op.drop_column('scan_picks', 'is_microcap')
