"""step6_swing_ux

Revision ID: d4e5f6a1b2c3
Revises: 06e34d247fdc
Create Date: 2026-05-31

Adds:
  - swing_trades.hold_long_term   BOOLEAN NOT NULL DEFAULT FALSE
  - scan_picks.promoted_to_trade_id  INTEGER NULL
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd4e5f6a1b2c3'
down_revision: Union[str, Sequence[str], None] = '06e34d247fdc'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('swing_trades',
        sa.Column('hold_long_term', sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column('scan_picks',
        sa.Column('promoted_to_trade_id', sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column('swing_trades', 'hold_long_term')
    op.drop_column('scan_picks', 'promoted_to_trade_id')
