"""kite_persistence

Revision ID: a2b3c4d5e6f7
Revises: f6a1b2c3d4e5
Create Date: 2026-06-01

Kite MCP persistence tables + equity_holdings/mf_holdings ALTER columns.
Also adds LLM analysis tables (pick_analysis, scan_reviews, market_notes_daily).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'a2b3c4d5e6f7'
down_revision: Union[str, Sequence[str], None] = 'f6a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── equity_holdings ALTER ──────────────────────────────────────────────────
    op.add_column('equity_holdings', sa.Column('source', sa.String(), nullable=True, server_default='manual'))
    op.add_column('equity_holdings', sa.Column('isin', sa.String(), nullable=True))
    op.add_column('equity_holdings', sa.Column('instrument_token', sa.BigInteger(), nullable=True))
    op.add_column('equity_holdings', sa.Column('exchange', sa.String(), nullable=True))
    op.add_column('equity_holdings', sa.Column('product', sa.String(), nullable=True))
    op.add_column('equity_holdings', sa.Column('t1_quantity', sa.Numeric(18, 4), nullable=True))
    op.add_column('equity_holdings', sa.Column('close_price', sa.Numeric(18, 4), nullable=True))
    op.add_column('equity_holdings', sa.Column('pnl', sa.Numeric(18, 4), nullable=True))
    op.add_column('equity_holdings', sa.Column('day_change', sa.Numeric(18, 4), nullable=True))
    op.add_column('equity_holdings', sa.Column('day_change_pct', sa.Numeric(18, 4), nullable=True))

    # ── mf_holdings ALTER ──────────────────────────────────────────────────────
    op.add_column('mf_holdings', sa.Column('tradingsymbol', sa.String(), nullable=True))
    op.add_column('mf_holdings', sa.Column('last_price_date', sa.String(), nullable=True))
    op.add_column('mf_holdings', sa.Column('pledged_quantity', sa.Numeric(18, 4), nullable=True))

    # ── kite_positions ─────────────────────────────────────────────────────────
    op.create_table(
        'kite_positions',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('tradingsymbol', sa.String(), nullable=True),
        sa.Column('exchange', sa.String(), nullable=True),
        sa.Column('instrument_token', sa.BigInteger(), nullable=True),
        sa.Column('product', sa.String(), nullable=True),
        sa.Column('quantity', sa.Numeric(18, 4), nullable=True),
        sa.Column('overnight_quantity', sa.Numeric(18, 4), nullable=True),
        sa.Column('multiplier', sa.Numeric(18, 4), nullable=True),
        sa.Column('average_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('last_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('close_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('value', sa.Numeric(18, 4), nullable=True),
        sa.Column('pnl', sa.Numeric(18, 4), nullable=True),
        sa.Column('m2m', sa.Numeric(18, 4), nullable=True),
        sa.Column('unrealised', sa.Numeric(18, 4), nullable=True),
        sa.Column('realised', sa.Numeric(18, 4), nullable=True),
        sa.Column('buy_quantity', sa.Numeric(18, 4), nullable=True),
        sa.Column('buy_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('buy_value', sa.Numeric(18, 4), nullable=True),
        sa.Column('sell_quantity', sa.Numeric(18, 4), nullable=True),
        sa.Column('sell_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('sell_value', sa.Numeric(18, 4), nullable=True),
        sa.Column('day_buy_quantity', sa.Numeric(18, 4), nullable=True),
        sa.Column('day_buy_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('day_sell_quantity', sa.Numeric(18, 4), nullable=True),
        sa.Column('day_sell_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('idx_kite_positions_user', 'kite_positions', ['user_id'])

    # ── kite_orders ────────────────────────────────────────────────────────────
    op.create_table(
        'kite_orders',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('order_id', sa.String(), nullable=True),
        sa.Column('parent_order_id', sa.String(), nullable=True),
        sa.Column('exchange_order_id', sa.String(), nullable=True),
        sa.Column('placed_by', sa.String(), nullable=True),
        sa.Column('variety', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('status_message', sa.String(), nullable=True),
        sa.Column('tradingsymbol', sa.String(), nullable=True),
        sa.Column('exchange', sa.String(), nullable=True),
        sa.Column('instrument_token', sa.BigInteger(), nullable=True),
        sa.Column('transaction_type', sa.String(), nullable=True),
        sa.Column('order_type', sa.String(), nullable=True),
        sa.Column('product', sa.String(), nullable=True),
        sa.Column('validity', sa.String(), nullable=True),
        sa.Column('price', sa.Numeric(18, 4), nullable=True),
        sa.Column('quantity', sa.Numeric(18, 4), nullable=True),
        sa.Column('trigger_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('average_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('pending_quantity', sa.Numeric(18, 4), nullable=True),
        sa.Column('filled_quantity', sa.Numeric(18, 4), nullable=True),
        sa.Column('disclosed_quantity', sa.Numeric(18, 4), nullable=True),
        sa.Column('cancelled_quantity', sa.Numeric(18, 4), nullable=True),
        sa.Column('order_timestamp', sa.String(), nullable=True),
        sa.Column('exchange_timestamp', sa.String(), nullable=True),
        sa.Column('tag', sa.String(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('user_id', 'order_id', name='uq_kite_order_user_orderid'),
    )
    op.create_index('idx_kite_orders_user', 'kite_orders', ['user_id'])

    # ── kite_trades ────────────────────────────────────────────────────────────
    op.create_table(
        'kite_trades',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('trade_id', sa.String(), nullable=True),
        sa.Column('order_id', sa.String(), nullable=True),
        sa.Column('exchange_order_id', sa.String(), nullable=True),
        sa.Column('exchange', sa.String(), nullable=True),
        sa.Column('tradingsymbol', sa.String(), nullable=True),
        sa.Column('instrument_token', sa.BigInteger(), nullable=True),
        sa.Column('product', sa.String(), nullable=True),
        sa.Column('average_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('quantity', sa.Numeric(18, 4), nullable=True),
        sa.Column('transaction_type', sa.String(), nullable=True),
        sa.Column('fill_timestamp', sa.String(), nullable=True),
        sa.Column('order_timestamp', sa.String(), nullable=True),
        sa.Column('exchange_timestamp', sa.String(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('user_id', 'trade_id', name='uq_kite_trade_user_tradeid'),
    )
    op.create_index('idx_kite_trades_user', 'kite_trades', ['user_id'])

    # ── kite_margins ───────────────────────────────────────────────────────────
    op.create_table(
        'kite_margins',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('segment', sa.String(), nullable=False),
        sa.Column('enabled', sa.Boolean(), nullable=True),
        sa.Column('net', sa.Numeric(18, 4), nullable=True),
        sa.Column('available_json', sa.JSON(), nullable=True),
        sa.Column('utilised_json', sa.JSON(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('user_id', 'segment', name='uq_kite_margins_user_segment'),
    )

    # ── kite_gtts ──────────────────────────────────────────────────────────────
    op.create_table(
        'kite_gtts',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False),
        sa.Column('trigger_id', sa.BigInteger(), nullable=True),
        sa.Column('type', sa.String(), nullable=True),
        sa.Column('status', sa.String(), nullable=True),
        sa.Column('tradingsymbol', sa.String(), nullable=True),
        sa.Column('exchange', sa.String(), nullable=True),
        sa.Column('instrument_token', sa.BigInteger(), nullable=True),
        sa.Column('trigger_values_json', sa.JSON(), nullable=True),
        sa.Column('last_price', sa.Numeric(18, 4), nullable=True),
        sa.Column('orders_json', sa.JSON(), nullable=True),
        sa.Column('created_at_kite', sa.String(), nullable=True),
        sa.Column('updated_at_kite', sa.String(), nullable=True),
        sa.Column('expires_at', sa.String(), nullable=True),
        sa.Column('fetched_at', sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint('user_id', 'trigger_id', name='uq_kite_gtt_user_triggerid'),
    )

    # ── pick_analysis ──────────────────────────────────────────────────────────
    op.create_table(
        'pick_analysis',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('scan_pick_id', sa.Integer(), sa.ForeignKey('scan_picks.id', ondelete='CASCADE'), nullable=False),
        sa.Column('kind', sa.String(), nullable=False),
        sa.Column('verdict_short', sa.String(), nullable=True),
        sa.Column('verdict_class', sa.String(), nullable=True),
        sa.Column('thesis', sa.Text(), nullable=True),
        sa.Column('risk_flags_json', sa.JSON(), nullable=True),
        sa.Column('failure_reason', sa.Text(), nullable=True),
        sa.Column('model_used', sa.String(), nullable=True),
        sa.Column('provider', sa.String(), nullable=True),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint('scan_pick_id', 'kind', name='uq_pick_analysis_pick_kind'),
    )
    op.create_index('idx_pick_analysis_pick', 'pick_analysis', ['scan_pick_id'])

    # ── scan_reviews ───────────────────────────────────────────────────────────
    op.create_table(
        'scan_reviews',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('scan_run_id', sa.Integer(), sa.ForeignKey('scan_runs.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('summary', sa.Text(), nullable=True),
        sa.Column('strong_count', sa.Integer(), nullable=True),
        sa.Column('weak_count', sa.Integer(), nullable=True),
        sa.Column('themes_json', sa.JSON(), nullable=True),
        sa.Column('best_sym', sa.String(), nullable=True),
        sa.Column('worst_sym', sa.String(), nullable=True),
        sa.Column('model_used', sa.String(), nullable=True),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_scan_reviews_run', 'scan_reviews', ['scan_run_id'])

    # ── market_notes_daily ─────────────────────────────────────────────────────
    op.create_table(
        'market_notes_daily',
        sa.Column('id', sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('date', sa.String(), nullable=False, unique=True),
        sa.Column('note', sa.Text(), nullable=True),
        sa.Column('context_json', sa.JSON(), nullable=True),
        sa.Column('model_used', sa.String(), nullable=True),
        sa.Column('generated_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('idx_market_notes_date', 'market_notes_daily', ['date'])


def downgrade() -> None:
    op.drop_index('idx_market_notes_date', table_name='market_notes_daily')
    op.drop_table('market_notes_daily')
    op.drop_index('idx_scan_reviews_run', table_name='scan_reviews')
    op.drop_table('scan_reviews')
    op.drop_index('idx_pick_analysis_pick', table_name='pick_analysis')
    op.drop_table('pick_analysis')
    op.drop_table('kite_gtts')
    op.drop_table('kite_margins')
    op.drop_index('idx_kite_trades_user', table_name='kite_trades')
    op.drop_table('kite_trades')
    op.drop_index('idx_kite_orders_user', table_name='kite_orders')
    op.drop_table('kite_orders')
    op.drop_index('idx_kite_positions_user', table_name='kite_positions')
    op.drop_table('kite_positions')
    op.drop_column('mf_holdings', 'pledged_quantity')
    op.drop_column('mf_holdings', 'last_price_date')
    op.drop_column('mf_holdings', 'tradingsymbol')
    op.drop_column('equity_holdings', 'day_change_pct')
    op.drop_column('equity_holdings', 'day_change')
    op.drop_column('equity_holdings', 'pnl')
    op.drop_column('equity_holdings', 'close_price')
    op.drop_column('equity_holdings', 't1_quantity')
    op.drop_column('equity_holdings', 'product')
    op.drop_column('equity_holdings', 'exchange')
    op.drop_column('equity_holdings', 'instrument_token')
    op.drop_column('equity_holdings', 'isin')
    op.drop_column('equity_holdings', 'source')
