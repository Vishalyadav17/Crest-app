"""ws8_kb_v2

Revision ID: j0k1l2m3n4o5
Revises: i9j0k1l2m3n4
Create Date: 2026-06-13

WS8: KB v2 self-computed columns:
  - industry_master.kb_as_of (DateTime): freshness stamp from refresh_kb job
  - industry_master.rrg_history (JSON): last 8 weeks of RRG trail points
  - stock_master.rs_rating (Float): computed IBD-style RS percentile
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "j0k1l2m3n4o5"
down_revision: Union[str, None] = "i9j0k1l2m3n4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("industry_master", sa.Column("kb_as_of", sa.DateTime(timezone=True), nullable=True))
    op.add_column("industry_master", sa.Column("rrg_history", sa.JSON(), nullable=True))
    op.add_column("stock_master", sa.Column("rs_rating", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("stock_master", "rs_rating")
    op.drop_column("industry_master", "rrg_history")
    op.drop_column("industry_master", "kb_as_of")
