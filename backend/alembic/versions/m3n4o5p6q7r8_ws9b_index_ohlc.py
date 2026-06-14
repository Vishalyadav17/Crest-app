"""ws9b_index_ohlc

Revision ID: m3n4o5p6q7r8
Revises: l2m3n4o5p6q7
Create Date: 2026-06-13

WS9b: custom_index_history gains OHLC + volume so indices render as
weighted candlesticks (ChartMaze _MCW style). `value` stays = close.
"""
from alembic import op
import sqlalchemy as sa

revision = "m3n4o5p6q7r8"
down_revision = "l2m3n4o5p6q7"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("custom_index_history", sa.Column("open",   sa.Numeric(18, 4), nullable=True))
    op.add_column("custom_index_history", sa.Column("high",   sa.Numeric(18, 4), nullable=True))
    op.add_column("custom_index_history", sa.Column("low",    sa.Numeric(18, 4), nullable=True))
    op.add_column("custom_index_history", sa.Column("volume", sa.Numeric(20, 2), nullable=True))


def downgrade():
    op.drop_column("custom_index_history", "volume")
    op.drop_column("custom_index_history", "low")
    op.drop_column("custom_index_history", "high")
    op.drop_column("custom_index_history", "open")
