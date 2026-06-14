"""scanner_v2_kb

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-06-09

Scanner v2 momentum engine: knowledge-base tables (industry_master,
index_membership, stock_surveillance), stock_master enrichment columns,
scan_picks composite-score / risk / audit columns.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── industry_master ──────────────────────────────────────────────────────────
    op.create_table(
        'industry_master',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('num_stocks', sa.Integer(), nullable=True),
        sa.Column('group_mcap_cr', sa.Numeric(18, 4), nullable=True),
        sa.Column('perf_1w', sa.Float(), nullable=True),
        sa.Column('perf_1m', sa.Float(), nullable=True),
        sa.Column('perf_3m', sa.Float(), nullable=True),
        sa.Column('rank_1w', sa.Integer(), nullable=True),
        sa.Column('rank_1m', sa.Integer(), nullable=True),
        sa.Column('rank_3m', sa.Integer(), nullable=True),
        sa.Column('rrg_quadrant', sa.String(), nullable=True),
        sa.Column('csv_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('mcw_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('ema20', sa.Numeric(18, 4), nullable=True),
        sa.Column('ema50', sa.Numeric(18, 4), nullable=True),
        sa.Column('ema200', sa.Numeric(18, 4), nullable=True),
        sa.Column('ema200_rising', sa.Boolean(), nullable=True),
        sa.Column('pct_from_52wh', sa.Float(), nullable=True),
        sa.Column('pct_from_ath', sa.Float(), nullable=True),
        sa.Column('breadth_above_ema20', sa.Float(), nullable=True),
        sa.Column('breadth_above_ema50', sa.Float(), nullable=True),
        sa.Column('breadth_above_ema200', sa.Float(), nullable=True),
        sa.Column('count_near_high', sa.Integer(), nullable=True),
        sa.Column('sector_momentum_score', sa.Float(), nullable=True),
        sa.Column('live_updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('name', name='uq_industry_master_name'),
    )

    # ── index_membership ─────────────────────────────────────────────────────────
    op.create_table(
        'index_membership',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('sym', sa.String(), nullable=False),
        sa.Column('index_name', sa.String(), nullable=False),
        sa.Column('index_type', sa.String(), nullable=False),
        sa.UniqueConstraint('sym', 'index_name', 'index_type', name='uq_index_membership'),
    )
    op.create_index('idx_index_membership_name_type', 'index_membership', ['index_name', 'index_type'])
    op.create_index('idx_index_membership_sym', 'index_membership', ['sym'])

    # ── stock_surveillance ───────────────────────────────────────────────────────
    op.create_table(
        'stock_surveillance',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('sym', sa.String(), nullable=False),
        sa.Column('asm_stage', sa.String(), nullable=True),
        sa.Column('gsm_stage', sa.String(), nullable=True),
        sa.Column('esm_stage', sa.String(), nullable=True),
        sa.Column('is_t2t', sa.Boolean(), nullable=True, server_default=sa.false()),
        sa.Column('circuit_band_pct', sa.Float(), nullable=True),
        sa.Column('delivery_pct', sa.Float(), nullable=True),
        sa.Column('flags', sa.JSON(), nullable=True),
        sa.Column('source', sa.String(), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('sym', name='uq_stock_surveillance_sym'),
    )
    op.create_index('idx_stock_surveillance_sym', 'stock_surveillance', ['sym'])

    # ── stock_master ALTER ───────────────────────────────────────────────────────
    op.add_column('stock_master', sa.Column('basic_industry', sa.String(), nullable=True))
    op.add_column('stock_master', sa.Column('rs_rating_csv', sa.Float(), nullable=True))
    op.add_column('stock_master', sa.Column('pct_from_52wh_csv', sa.Float(), nullable=True))
    op.add_column('stock_master', sa.Column('ret_1m_csv', sa.Float(), nullable=True))
    op.add_column('stock_master', sa.Column('ret_3m_csv', sa.Float(), nullable=True))
    op.add_column('stock_master', sa.Column('listing_date', sa.String(), nullable=True))
    op.add_column('stock_master', sa.Column('is_ipo', sa.Boolean(), nullable=True, server_default=sa.false()))
    op.add_column('stock_master', sa.Column('is_custom_idx', sa.Boolean(), nullable=True, server_default=sa.false()))
    op.add_column('stock_master', sa.Column('source', sa.String(), nullable=True))
    op.add_column('stock_master', sa.Column('yf_ok', sa.Boolean(), nullable=True))
    op.add_column('stock_master', sa.Column('csv_updated_at', sa.DateTime(timezone=True), nullable=True))

    # ── scan_picks ALTER ─────────────────────────────────────────────────────────
    op.add_column('scan_picks', sa.Column('sector_momentum_score', sa.Float(), nullable=True))
    op.add_column('scan_picks', sa.Column('leadership_score', sa.Float(), nullable=True))
    op.add_column('scan_picks', sa.Column('breakout_score', sa.Float(), nullable=True))
    op.add_column('scan_picks', sa.Column('composite_score', sa.Float(), nullable=True))
    op.add_column('scan_picks', sa.Column('is_ipo_pick', sa.Boolean(), nullable=True, server_default=sa.false()))
    op.add_column('scan_picks', sa.Column('tradeability_status', sa.String(), nullable=True))
    op.add_column('scan_picks', sa.Column('position_size_json', sa.JSON(), nullable=True))
    op.add_column('scan_picks', sa.Column('audit_json', sa.JSON(), nullable=True))


def downgrade() -> None:
    for col in ('audit_json', 'position_size_json', 'tradeability_status', 'is_ipo_pick',
                'composite_score', 'breakout_score', 'leadership_score', 'sector_momentum_score'):
        op.drop_column('scan_picks', col)
    for col in ('csv_updated_at', 'yf_ok', 'source', 'is_custom_idx', 'is_ipo', 'listing_date',
                'ret_3m_csv', 'ret_1m_csv', 'pct_from_52wh_csv', 'rs_rating_csv', 'basic_industry'):
        op.drop_column('stock_master', col)
    op.drop_index('idx_stock_surveillance_sym', table_name='stock_surveillance')
    op.drop_table('stock_surveillance')
    op.drop_index('idx_index_membership_sym', table_name='index_membership')
    op.drop_index('idx_index_membership_name_type', table_name='index_membership')
    op.drop_table('index_membership')
    op.drop_table('industry_master')
