"""ws12_order_flow

Revision ID: k1l2m3n4o5p6
Revises: j0k1l2m3n4o5
Create Date: 2026-06-13

WS12: Order-flow intelligence + earnings-setup score.
  - stock_master: last_q_revenue_cr, last_q_date, next_earnings_date
  - order_announcements: new table
  - earnings_guidance: new table
"""
from typing import Sequence, Union
import sqlalchemy as sa
from alembic import op

revision: str = "k1l2m3n4o5p6"
down_revision: Union[str, None] = "j0k1l2m3n4o5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # stock_master new columns
    op.add_column("stock_master", sa.Column("last_q_revenue_cr", sa.Numeric(18, 4), nullable=True))
    op.add_column("stock_master", sa.Column("last_q_date", sa.String(), nullable=True))
    op.add_column("stock_master", sa.Column("next_earnings_date", sa.String(), nullable=True))

    # order_announcements table
    op.create_table(
        "order_announcements",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sym", sa.String(), nullable=False),
        sa.Column("ann_date", sa.String(), nullable=False),
        sa.Column("headline", sa.String(), nullable=False),
        sa.Column("body_excerpt", sa.Text(), nullable=True),
        sa.Column("value_cr", sa.Numeric(18, 4), nullable=True),
        sa.Column("extraction", sa.String(), nullable=False, server_default="none"),
        sa.Column("source_url", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_order_ann_sym", "order_announcements", ["sym"])
    op.create_index("idx_order_ann_date", "order_announcements", ["ann_date"])
    op.create_unique_constraint(
        "uq_order_ann_sym_date_headline",
        "order_announcements",
        ["sym", "ann_date", "headline"],
    )

    # earnings_guidance table
    op.create_table(
        "earnings_guidance",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("sym", sa.String(), unique=True, nullable=False),
        sa.Column("fy_revenue_guidance_cr", sa.Numeric(18, 4), nullable=True),
        sa.Column("q_revenue_guidance_cr", sa.Numeric(18, 4), nullable=True),
        sa.Column("guidance_note", sa.Text(), nullable=True),
        sa.Column("guidance_as_of", sa.String(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("idx_earnings_guidance_sym", "earnings_guidance", ["sym"])


def downgrade() -> None:
    op.drop_table("earnings_guidance")
    op.drop_table("order_announcements")
    op.drop_column("stock_master", "next_earnings_date")
    op.drop_column("stock_master", "last_q_date")
    op.drop_column("stock_master", "last_q_revenue_cr")
