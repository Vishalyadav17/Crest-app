"""phase0_foundation

Revision ID: a1b2c3d4e5f6
Revises: c3d4e5f6a1b2
Create Date: 2026-05-27

Phase 0 schema hardening:
  0.1 — Float → NUMERIC(18,4) for all money/qty/price columns
  0.3 — Missing FK/hot-column indexes
  0.4 — Text → JSON for ScanPick.criteria/levels, ScanRun.market_summary,
         PortfolioMeta.score_json, UserDashboardModule.config
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'a1b2c3d4e5f6'
down_revision: Union[str, Sequence[str], None] = 'c3d4e5f6a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_NUMERIC = sa.Numeric(18, 4)


def upgrade() -> None:
    # ── 0.1  Float → NUMERIC(18,4) ───────────────────────────────────────────

    # stock_master
    op.alter_column('stock_master', 'mcap_cr',
                    existing_type=sa.Float(),
                    type_=_NUMERIC,
                    existing_nullable=True,
                    postgresql_using='mcap_cr::numeric(18,4)')

    # equity_holdings
    for col in ('mcap_cr', 'qty', 'avg_price', 'ltp'):
        op.alter_column('equity_holdings', col,
                        existing_type=sa.Float(),
                        type_=_NUMERIC,
                        existing_nullable=(col != 'qty' and col != 'avg_price'),
                        postgresql_using=f'{col}::numeric(18,4)')

    # portfolio_meta
    op.alter_column('portfolio_meta', 'cash',
                    existing_type=sa.Float(),
                    type_=_NUMERIC,
                    existing_nullable=True,
                    postgresql_using='cash::numeric(18,4)')

    # global_holdings
    for col in ('qty', 'avg_price_usd', 'current_price_usd'):
        op.alter_column('global_holdings', col,
                        existing_type=sa.Float(),
                        type_=_NUMERIC,
                        existing_nullable=(col == 'current_price_usd'),
                        postgresql_using=f'{col}::numeric(18,4)')

    # crypto_holdings
    for col in ('qty', 'avg_price_usd', 'current_price_usd'):
        op.alter_column('crypto_holdings', col,
                        existing_type=sa.Float(),
                        type_=_NUMERIC,
                        existing_nullable=(col == 'current_price_usd'),
                        postgresql_using=f'{col}::numeric(18,4)')

    # mf_holdings
    for col in ('units', 'avg_nav', 'current_nav'):
        op.alter_column('mf_holdings', col,
                        existing_type=sa.Float(),
                        type_=_NUMERIC,
                        existing_nullable=True,
                        postgresql_using=f'{col}::numeric(18,4)')

    # swing_trades
    for col in ('mcap_cr', 'qty', 'avg_price', 'ltp', 'sl', 'target', 'exit_price', 'realized_pnl'):
        op.alter_column('swing_trades', col,
                        existing_type=sa.Float(),
                        type_=_NUMERIC,
                        existing_nullable=True,
                        postgresql_using=f'{col}::numeric(18,4)')

    # scan_picks
    op.alter_column('scan_picks', 'mcap_cr',
                    existing_type=sa.Float(),
                    type_=_NUMERIC,
                    existing_nullable=True,
                    postgresql_using='mcap_cr::numeric(18,4)')

    # scan_outcomes
    for col in ('qty', 'entry_price', 'exit_price', 'return_pct'):
        op.alter_column('scan_outcomes', col,
                        existing_type=sa.Float(),
                        type_=_NUMERIC,
                        existing_nullable=True,
                        postgresql_using=f'{col}::numeric(18,4)')

    # price_alerts
    op.alter_column('price_alerts', 'target_price',
                    existing_type=sa.Float(),
                    type_=_NUMERIC,
                    existing_nullable=True,
                    postgresql_using='target_price::numeric(18,4)')

    # ── 0.3  Missing FK indexes ───────────────────────────────────────────────

    op.create_index('idx_global_user',            'global_holdings',        ['user_id'])
    op.create_index('idx_crypto_user',            'crypto_holdings',        ['user_id'])
    op.create_index('idx_mf_holdings_user',       'mf_holdings',            ['user_id'])
    op.create_index('idx_mf_watchpoints_user',    'mf_watchpoints',         ['user_id'])
    op.create_index('idx_investment_thesis_user', 'investment_thesis',      ['user_id'])
    op.create_index('idx_watchlists_user',        'watchlists',             ['user_id'])
    op.create_index('idx_watchlist_items_wl',     'watchlist_items',        ['watchlist_id'])
    op.create_index('idx_import_jobs_user',       'import_jobs',            ['user_id'])
    op.create_index('idx_scan_runs_user',         'scan_runs',              ['user_id'])
    op.create_index('idx_scan_picks_run',         'scan_picks',             ['scan_run_id'])
    op.create_index('idx_scan_outcomes_user',     'scan_outcomes',          ['user_id'])
    op.create_index('idx_scan_outcomes_pick',     'scan_outcomes',          ['scan_pick_id'])
    op.create_index('idx_dashboard_modules_user', 'user_dashboard_modules', ['user_id'])
    op.create_index('idx_user_preferences_user',  'user_preferences',       ['user_id'])
    op.create_index('idx_alerts_sym_triggered',   'price_alerts',           ['sym', 'is_triggered'])

    # ── 0.4  Text → JSON ─────────────────────────────────────────────────────

    op.alter_column('scan_runs', 'market_summary',
                    existing_type=sa.Text(),
                    type_=sa.JSON(),
                    existing_nullable=True,
                    postgresql_using="CASE WHEN market_summary IS NULL THEN NULL ELSE market_summary::json END")

    op.alter_column('scan_picks', 'criteria',
                    existing_type=sa.Text(),
                    type_=sa.JSON(),
                    existing_nullable=True,
                    postgresql_using="CASE WHEN criteria IS NULL THEN NULL ELSE criteria::json END")

    op.alter_column('scan_picks', 'levels',
                    existing_type=sa.Text(),
                    type_=sa.JSON(),
                    existing_nullable=True,
                    postgresql_using="CASE WHEN levels IS NULL THEN NULL ELSE levels::json END")

    op.alter_column('portfolio_meta', 'score_json',
                    existing_type=sa.Text(),
                    type_=sa.JSON(),
                    existing_nullable=True,
                    postgresql_using="CASE WHEN score_json IS NULL THEN NULL ELSE score_json::json END")

    op.alter_column('user_dashboard_modules', 'config',
                    existing_type=sa.Text(),
                    type_=sa.JSON(),
                    existing_nullable=True,
                    postgresql_using="CASE WHEN config IS NULL THEN NULL ELSE config::json END")


def downgrade() -> None:
    # ── 0.4  JSON → Text ─────────────────────────────────────────────────────

    op.alter_column('user_dashboard_modules', 'config',
                    existing_type=sa.JSON(),
                    type_=sa.Text(),
                    existing_nullable=True,
                    postgresql_using='config::text')

    op.alter_column('portfolio_meta', 'score_json',
                    existing_type=sa.JSON(),
                    type_=sa.Text(),
                    existing_nullable=True,
                    postgresql_using='score_json::text')

    op.alter_column('scan_picks', 'levels',
                    existing_type=sa.JSON(),
                    type_=sa.Text(),
                    existing_nullable=True,
                    postgresql_using='levels::text')

    op.alter_column('scan_picks', 'criteria',
                    existing_type=sa.JSON(),
                    type_=sa.Text(),
                    existing_nullable=True,
                    postgresql_using='criteria::text')

    op.alter_column('scan_runs', 'market_summary',
                    existing_type=sa.JSON(),
                    type_=sa.Text(),
                    existing_nullable=True,
                    postgresql_using='market_summary::text')

    # ── 0.3  Drop FK indexes ──────────────────────────────────────────────────

    op.drop_index('idx_alerts_sym_triggered',   'price_alerts')
    op.drop_index('idx_user_preferences_user',  'user_preferences')
    op.drop_index('idx_dashboard_modules_user', 'user_dashboard_modules')
    op.drop_index('idx_scan_outcomes_pick',     'scan_outcomes')
    op.drop_index('idx_scan_outcomes_user',     'scan_outcomes')
    op.drop_index('idx_scan_picks_run',         'scan_picks')
    op.drop_index('idx_scan_runs_user',         'scan_runs')
    op.drop_index('idx_import_jobs_user',       'import_jobs')
    op.drop_index('idx_watchlist_items_wl',     'watchlist_items')
    op.drop_index('idx_watchlists_user',        'watchlists')
    op.drop_index('idx_investment_thesis_user', 'investment_thesis')
    op.drop_index('idx_mf_watchpoints_user',    'mf_watchpoints')
    op.drop_index('idx_mf_holdings_user',       'mf_holdings')
    op.drop_index('idx_crypto_user',            'crypto_holdings')
    op.drop_index('idx_global_user',            'global_holdings')

    # ── 0.1  NUMERIC(18,4) → Float ───────────────────────────────────────────

    op.alter_column('price_alerts', 'target_price',
                    existing_type=_NUMERIC, type_=sa.Float(), existing_nullable=True,
                    postgresql_using='target_price::float')

    for col in ('qty', 'entry_price', 'exit_price', 'return_pct'):
        op.alter_column('scan_outcomes', col,
                        existing_type=_NUMERIC, type_=sa.Float(), existing_nullable=True,
                        postgresql_using=f'{col}::float')

    op.alter_column('scan_picks', 'mcap_cr',
                    existing_type=_NUMERIC, type_=sa.Float(), existing_nullable=True,
                    postgresql_using='mcap_cr::float')

    for col in ('mcap_cr', 'qty', 'avg_price', 'ltp', 'sl', 'target', 'exit_price', 'realized_pnl'):
        op.alter_column('swing_trades', col,
                        existing_type=_NUMERIC, type_=sa.Float(), existing_nullable=True,
                        postgresql_using=f'{col}::float')

    for col in ('units', 'avg_nav', 'current_nav'):
        op.alter_column('mf_holdings', col,
                        existing_type=_NUMERIC, type_=sa.Float(), existing_nullable=True,
                        postgresql_using=f'{col}::float')

    for col in ('qty', 'avg_price_usd', 'current_price_usd'):
        op.alter_column('crypto_holdings', col,
                        existing_type=_NUMERIC, type_=sa.Float(), existing_nullable=True,
                        postgresql_using=f'{col}::float')

    for col in ('qty', 'avg_price_usd', 'current_price_usd'):
        op.alter_column('global_holdings', col,
                        existing_type=_NUMERIC, type_=sa.Float(), existing_nullable=True,
                        postgresql_using=f'{col}::float')

    op.alter_column('portfolio_meta', 'cash',
                    existing_type=_NUMERIC, type_=sa.Float(), existing_nullable=True,
                    postgresql_using='cash::float')

    for col in ('mcap_cr', 'qty', 'avg_price', 'ltp'):
        op.alter_column('equity_holdings', col,
                        existing_type=_NUMERIC, type_=sa.Float(), existing_nullable=True,
                        postgresql_using=f'{col}::float')

    op.alter_column('stock_master', 'mcap_cr',
                    existing_type=_NUMERIC, type_=sa.Float(), existing_nullable=True,
                    postgresql_using='mcap_cr::float')
