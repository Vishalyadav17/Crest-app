"""pick_tracking

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-06-10

Add scan_picks.tracking_json — nightly strength re-check + closed-detection
state for the weekly frozen basket (enterable | weak | missed | closed).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd5e6f7a8b9c0'
down_revision: Union[str, Sequence[str], None] = 'c4d5e6f7a8b9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('scan_picks', sa.Column('tracking_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column('scan_picks', 'tracking_json')
