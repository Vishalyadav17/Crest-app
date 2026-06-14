"""phase1_snapshot_tables

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-05-27

Phase 1 schema:
  - New tables: portfolio_snapshots, swing_summaries, price_snapshots,
                market_cache, market_snapshots_daily, mf_nav_history
  - New columns: swing_trades.invested/return_pct, scan_runs.stats_json,
                 scan_picks.initial_badge/class, mf_holdings.invested/
                 current_value/pnl/pnl_pct
  - SQL backfill for swing_trades and mf_holdings precomputed fields
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'a1b2c3d4e5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_N = sa.Numeric(18, 4)


def upgrade() -> None:
    # ── New columns on existing tables ────────────────────────────────────────

    op.add_column('swing_trades', sa.Column('invested',   _N, nullable=True))
    op.add_column('swing_trades', sa.Column('return_pct', _N, nullable=True))

    op.add_column('scan_runs',  sa.Column('stats_json', sa.JSON(), nullable=True))

    op.add_column('scan_picks', sa.Column('initial_badge',       sa.String(), nullable=True))
    op.add_column('scan_picks', sa.Column('initial_badge_class', sa.String(), nullable=True))

    op.add_column('mf_holdings', sa.Column('invested',      _N, nullable=True))
    op.add_column('mf_holdings', sa.Column('current_value', _N, nullable=True))
    op.add_column('mf_holdings', sa.Column('pnl',           _N, nullable=True))
    op.add_column('mf_holdings', sa.Column('pnl_pct',       _N, nullable=True))

    # ── SQL backfill for swing_trades ─────────────────────────────────────────

    op.execute("""
        UPDATE swing_trades
        SET invested = qty * avg_price
        WHERE status = 'active'
          AND qty IS NOT NULL
          AND avg_price IS NOT NULL
    """)

    op.execute("""
        UPDATE swing_trades
        SET return_pct = ROUND(((exit_price - avg_price) / avg_price * 100)::numeric, 4)
        WHERE status = 'closed'
          AND avg_price IS NOT NULL
          AND exit_price IS NOT NULL
          AND avg_price <> 0
    """)

    # ── SQL backfill for mf_holdings ──────────────────────────────────────────

    op.execute("""
        UPDATE mf_holdings
        SET invested      = units * avg_nav,
            current_value = units * COALESCE(current_nav, avg_nav),
            pnl           = units * COALESCE(current_nav, avg_nav) - units * avg_nav
        WHERE units IS NOT NULL
          AND avg_nav IS NOT NULL
    """)

    op.execute("""
        UPDATE mf_holdings
        SET pnl_pct = ROUND((pnl / (units * avg_nav) * 100)::numeric, 4)
        WHERE units IS NOT NULL
          AND avg_nav IS NOT NULL
          AND avg_nav <> 0
          AND pnl IS NOT NULL
    """)

    # ── New tables ────────────────────────────────────────────────────────────

    op.create_table(
        'portfolio_snapshots',
        sa.Column('id',                     sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id',                sa.Integer(), sa.ForeignKey('users.id'), nullable=False, unique=True),
        sa.Column('as_of',                  sa.String(),  nullable=True),
        sa.Column('total_wealth',           _N,           nullable=True),
        sa.Column('equity_value',           _N,           nullable=True),
        sa.Column('mf_value',               _N,           nullable=True),
        sa.Column('global_value',           _N,           nullable=True),
        sa.Column('crypto_value',           _N,           nullable=True),
        sa.Column('cash',                   _N,           nullable=True),
        sa.Column('total_invested',         _N,           nullable=True),
        sa.Column('total_pnl',              _N,           nullable=True),
        sa.Column('total_pnl_pct',          _N,           nullable=True),
        sa.Column('cagr',                   _N,           nullable=True),
        sa.Column('stocks_pct',             _N,           nullable=True),
        sa.Column('mf_pct',                 _N,           nullable=True),
        sa.Column('cash_pct',               _N,           nullable=True),
        sa.Column('global_pct',             _N,           nullable=True),
        sa.Column('crypto_pct',             _N,           nullable=True),
        sa.Column('allocation_sector_json', sa.JSON(),    nullable=True),
        sa.Column('allocation_mcap_json',   sa.JSON(),    nullable=True),
        sa.Column('first_trade_date',       sa.String(),  nullable=True),
        sa.Column('computed_at',            sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('idx_portfolio_snapshot_user', 'portfolio_snapshots', ['user_id'])

    op.create_table(
        'swing_summaries',
        sa.Column('id',             sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('user_id',        sa.Integer(), sa.ForeignKey('users.id'), nullable=False, unique=True),
        sa.Column('total_invested', _N,           nullable=True),
        sa.Column('open_count',     sa.Integer(), nullable=False, server_default='0'),
        sa.Column('closed_count',   sa.Integer(), nullable=False, server_default='0'),
        sa.Column('wins',           sa.Integer(), nullable=False, server_default='0'),
        sa.Column('win_rate',       sa.Float(),   nullable=True),
        sa.Column('win_rate_class', sa.String(),  nullable=True),
        sa.Column('closed_pl',      _N,           nullable=True),
        sa.Column('updated_at',     sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        'price_snapshots',
        sa.Column('id',              sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('sym',             sa.String(),  nullable=False, unique=True),
        sa.Column('ltp',             _N,           nullable=True),
        sa.Column('prev_close',      _N,           nullable=True),
        sa.Column('day_high',        _N,           nullable=True),
        sa.Column('day_low',         _N,           nullable=True),
        sa.Column('day_change_pct',  _N,           nullable=True),
        sa.Column('ohlc_today_json', sa.JSON(),    nullable=True),
        sa.Column('fetched_at',      sa.DateTime(timezone=True), nullable=True),
    )

    op.create_table(
        'market_cache',
        sa.Column('id',          sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('key',         sa.String(),  nullable=False, unique=True),
        sa.Column('data_json',   sa.JSON(),    nullable=True),
        sa.Column('ttl_seconds', sa.Integer(), nullable=False, server_default='900'),
        sa.Column('expires_at',  sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at',  sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index('idx_market_cache_key', 'market_cache', ['key'])

    op.create_table(
        'market_snapshots_daily',
        sa.Column('id',                  sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('date',                sa.String(),  nullable=False, unique=True),
        sa.Column('indices_json',        sa.JSON(),    nullable=True),
        sa.Column('breadth_json',        sa.JSON(),    nullable=True),
        sa.Column('sector_heatmap_json', sa.JSON(),    nullable=True),
        sa.Column('ad_ratio_json',       sa.JSON(),    nullable=True),
        sa.Column('top_gainers_json',    sa.JSON(),    nullable=True),
        sa.Column('rs_universe_json',    sa.JSON(),    nullable=True),
        sa.Column('created_at',          sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index('idx_market_snap_date', 'market_snapshots_daily', ['date'])

    op.create_table(
        'mf_nav_history',
        sa.Column('id',        sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column('fund_key',  sa.String(),  nullable=False),
        sa.Column('nav_date',  sa.String(),  nullable=False),
        sa.Column('nav_value', _N,           nullable=False),
        sa.UniqueConstraint('fund_key', 'nav_date', name='uq_mf_nav_history'),
    )
    op.create_index('idx_mf_nav_history_key', 'mf_nav_history', ['fund_key'])


def downgrade() -> None:
    op.drop_table('mf_nav_history')
    op.drop_table('market_snapshots_daily')
    op.drop_table('market_cache')
    op.drop_table('price_snapshots')
    op.drop_table('swing_summaries')
    op.drop_table('portfolio_snapshots')

    op.drop_column('mf_holdings', 'pnl_pct')
    op.drop_column('mf_holdings', 'pnl')
    op.drop_column('mf_holdings', 'current_value')
    op.drop_column('mf_holdings', 'invested')

    op.drop_column('scan_picks', 'initial_badge_class')
    op.drop_column('scan_picks', 'initial_badge')
    op.drop_column('scan_runs',  'stats_json')

    op.drop_column('swing_trades', 'return_pct')
    op.drop_column('swing_trades', 'invested')
