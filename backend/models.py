from __future__ import annotations
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    BigInteger, Integer, String, Float, Boolean, DateTime, Text,
    ForeignKey, UniqueConstraint, Index, Numeric, JSON,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ── Group 1: Users ─────────────────────────────────────────────────────────────

class User(Base):
    __tablename__ = "users"

    id:         Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    email:      Mapped[str]            = mapped_column(String, unique=True, nullable=False)
    name:       Mapped[Optional[str]]  = mapped_column(String)
    tier:                Mapped[str]            = mapped_column(String, default="free")
    google_id:           Mapped[Optional[str]]  = mapped_column(String, unique=True)
    avatar_url:          Mapped[Optional[str]]  = mapped_column(String)
    onboarding_complete: Mapped[bool]           = mapped_column(Boolean, default=False)
    created_at:          Mapped[datetime]        = mapped_column(DateTime(timezone=True), default=_now)
    last_login:          Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    equity_holdings:     Mapped[list[EquityHolding]]     = relationship(back_populates="user", cascade="all, delete-orphan")
    portfolio_meta:      Mapped[Optional[PortfolioMeta]] = relationship(back_populates="user", cascade="all, delete-orphan", uselist=False)
    global_holdings:     Mapped[list[GlobalHolding]]     = relationship(back_populates="user", cascade="all, delete-orphan")
    crypto_holdings:     Mapped[list[CryptoHolding]]     = relationship(back_populates="user", cascade="all, delete-orphan")
    mf_holdings:         Mapped[list[MFHolding]]         = relationship(back_populates="user", cascade="all, delete-orphan")
    mf_watchpoints:      Mapped[list[MFWatchpoint]]      = relationship(back_populates="user", cascade="all, delete-orphan")
    investment_theses:   Mapped[list[InvestmentThesis]]  = relationship(back_populates="user", cascade="all, delete-orphan")
    swing_trades:        Mapped[list[SwingTrade]]        = relationship(back_populates="user", cascade="all, delete-orphan")
    watchlists:          Mapped[list[Watchlist]]         = relationship(back_populates="user", cascade="all, delete-orphan")
    scan_runs:           Mapped[list[ScanRun]]           = relationship(back_populates="user", cascade="all, delete-orphan")
    import_jobs:         Mapped[list[ImportJob]]         = relationship(back_populates="user", cascade="all, delete-orphan")
    price_alerts:        Mapped[list[PriceAlert]]        = relationship(back_populates="user", cascade="all, delete-orphan")
    price_bands:         Mapped[list[PriceBand]]         = relationship(back_populates="user", cascade="all, delete-orphan")
    notifications:       Mapped[list[Notification]]      = relationship(back_populates="user", cascade="all, delete-orphan")
    dashboard_modules:   Mapped[list[UserDashboardModule]] = relationship(back_populates="user", cascade="all, delete-orphan")
    preferences:         Mapped[list[UserPreference]]    = relationship(back_populates="user", cascade="all, delete-orphan")
    provider_credentials: Mapped[list[ProviderCredential]] = relationship(back_populates="user", cascade="all, delete-orphan")


# ── Group 2: Stock Master ──────────────────────────────────────────────────────

class StockMaster(Base):
    __tablename__ = "stock_master"
    __table_args__ = (
        Index("idx_stock_master_name", "name"),
    )

    id:           Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    sym:          Mapped[str]           = mapped_column(String, unique=True, nullable=False)
    name:         Mapped[str]           = mapped_column(String, nullable=False)
    exchange:     Mapped[str]           = mapped_column(String, default="NSE")
    asset_class:  Mapped[str]           = mapped_column(String, default="equity")
    sector:       Mapped[Optional[str]] = mapped_column(String)
    mcap_bucket:  Mapped[Optional[str]] = mapped_column(String)
    mcap_cr:      Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    is_etf:          Mapped[bool]          = mapped_column(Boolean, default=False)
    is_microcap_idx: Mapped[bool]          = mapped_column(Boolean, default=False)
    last_updated:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Scanner v2 knowledge-base enrichment
    basic_industry:    Mapped[Optional[str]]   = mapped_column(String)
    rs_rating_csv:     Mapped[Optional[float]] = mapped_column(Float)
    rs_rating:         Mapped[Optional[float]] = mapped_column(Float)  # computed IBD-style percentile
    pct_from_52wh_csv: Mapped[Optional[float]] = mapped_column(Float)
    ret_1m_csv:        Mapped[Optional[float]] = mapped_column(Float)
    ret_3m_csv:        Mapped[Optional[float]] = mapped_column(Float)
    listing_date:      Mapped[Optional[str]]   = mapped_column(String)
    is_ipo:            Mapped[bool]            = mapped_column(Boolean, default=False)
    is_custom_idx:     Mapped[bool]            = mapped_column(Boolean, default=False)
    source:            Mapped[Optional[str]]   = mapped_column(String)
    yf_ok:             Mapped[Optional[bool]]  = mapped_column(Boolean)
    csv_updated_at:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # WS12 order-flow / earnings
    last_q_revenue_cr:  Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    last_q_date:        Mapped[Optional[str]]   = mapped_column(String)
    next_earnings_date: Mapped[Optional[str]]   = mapped_column(String)


# ── Group 3: Equity Holdings ───────────────────────────────────────────────────

class EquityHolding(Base):
    __tablename__ = "equity_holdings"
    __table_args__ = (
        Index("idx_equity_user", "user_id"),
    )

    id:          Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:     Mapped[int]            = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    sym:         Mapped[str]            = mapped_column(String, nullable=False)
    name:        Mapped[Optional[str]]  = mapped_column(String)
    sector:      Mapped[Optional[str]]  = mapped_column(String)
    mcap_bucket: Mapped[Optional[str]]  = mapped_column(String)
    mcap_cr:     Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    qty:         Mapped[float]          = mapped_column(Numeric(18, 4), nullable=False)
    avg_price:   Mapped[float]          = mapped_column(Numeric(18, 4), nullable=False)
    ltp:         Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    is_etf:      Mapped[bool]           = mapped_column(Boolean, default=False)
    hold_type:   Mapped[str]            = mapped_column(String, default="long")
    broker:             Mapped[Optional[str]]  = mapped_column(String)
    note:               Mapped[Optional[str]]  = mapped_column(Text)
    source:             Mapped[str]            = mapped_column(String, default="manual")
    isin:               Mapped[Optional[str]]  = mapped_column(String)
    instrument_token:   Mapped[Optional[int]]  = mapped_column(BigInteger)
    exchange:           Mapped[Optional[str]]  = mapped_column(String)
    product:            Mapped[Optional[str]]  = mapped_column(String)
    t1_quantity:        Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    close_price:        Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    pnl:                Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    day_change:         Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    day_change_pct:     Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    imported_at:        Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at:         Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user: Mapped[User] = relationship(back_populates="equity_holdings")


class PortfolioMeta(Base):
    __tablename__ = "portfolio_meta"

    id:               Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:          Mapped[int]           = mapped_column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    first_trade_date: Mapped[Optional[str]] = mapped_column(String)
    as_of:            Mapped[Optional[str]] = mapped_column(String)
    cash:             Mapped[float]         = mapped_column(Numeric(18, 4), default=0)
    health_score:     Mapped[Optional[float]] = mapped_column(Float)
    score_json:       Mapped[Optional[dict]] = mapped_column(JSON)
    updated_at:       Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user: Mapped[User] = relationship(back_populates="portfolio_meta")


# ── Group 4: Global Holdings ───────────────────────────────────────────────────

class GlobalHolding(Base):
    __tablename__ = "global_holdings"
    __table_args__ = (
        Index("idx_global_user", "user_id"),
    )

    id:                Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:           Mapped[int]           = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    sym:               Mapped[str]           = mapped_column(String, nullable=False)
    name:              Mapped[Optional[str]] = mapped_column(String)
    exchange:          Mapped[Optional[str]] = mapped_column(String)
    asset_type:        Mapped[str]           = mapped_column(String, default="stock")
    qty:               Mapped[float]         = mapped_column(Numeric(18, 4), nullable=False)
    avg_price_usd:     Mapped[float]         = mapped_column(Numeric(18, 4), nullable=False)
    current_price_usd: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    broker:            Mapped[Optional[str]] = mapped_column(String)
    note:              Mapped[Optional[str]] = mapped_column(Text)
    status:            Mapped[str]           = mapped_column(String, default="active", server_default="active", nullable=False)
    closed_at:         Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    imported_at:       Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at:        Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user: Mapped[User] = relationship(back_populates="global_holdings")


# ── Group 5: Crypto Holdings ───────────────────────────────────────────────────

class CryptoHolding(Base):
    __tablename__ = "crypto_holdings"
    __table_args__ = (
        Index("idx_crypto_user", "user_id"),
    )

    id:                 Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:            Mapped[int]           = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    sym:                Mapped[str]           = mapped_column(String, nullable=False)
    coingecko_id:       Mapped[Optional[str]] = mapped_column(String)
    name:               Mapped[Optional[str]] = mapped_column(String)
    qty:                Mapped[float]         = mapped_column(Numeric(18, 4), nullable=False)
    avg_price_usd:      Mapped[float]         = mapped_column(Numeric(18, 4), nullable=False)
    current_price_usd:  Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    wallet_or_exchange: Mapped[Optional[str]] = mapped_column(String)
    note:               Mapped[Optional[str]] = mapped_column(Text)
    status:             Mapped[str]           = mapped_column(String, default="active", server_default="active", nullable=False)
    closed_at:          Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    imported_at:        Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at:         Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user: Mapped[User] = relationship(back_populates="crypto_holdings")


# ── Group 6: Mutual Funds ──────────────────────────────────────────────────────

class MFHolding(Base):
    __tablename__ = "mf_holdings"
    __table_args__ = (
        Index("idx_mf_holdings_user", "user_id"),
    )

    id:           Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:      Mapped[int]           = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    folio_number: Mapped[Optional[str]] = mapped_column(String)
    name:         Mapped[str]           = mapped_column(String, nullable=False)
    short:        Mapped[Optional[str]] = mapped_column(String)
    amc:          Mapped[Optional[str]] = mapped_column(String)
    category:     Mapped[Optional[str]] = mapped_column(String)
    type:         Mapped[Optional[str]] = mapped_column(String)
    units:         Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    avg_nav:       Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    current_nav:   Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    invested:      Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    current_value: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    pnl:               Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    pnl_pct:           Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    scheme_code:       Mapped[Optional[str]] = mapped_column(String, index=True)
    source:            Mapped[str]           = mapped_column(String, default="manual")
    tradingsymbol:     Mapped[Optional[str]] = mapped_column(String)
    last_price_date:   Mapped[Optional[str]] = mapped_column(String)
    pledged_quantity:  Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    imported_at:       Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at:        Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user: Mapped[User] = relationship(back_populates="mf_holdings")


class MFWatchpoint(Base):
    __tablename__ = "mf_watchpoints"
    __table_args__ = (
        UniqueConstraint("user_id", "fund_key"),
        Index("idx_mf_watchpoints_user", "user_id"),
    )

    id:       Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:  Mapped[int]           = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    fund_key: Mapped[str]           = mapped_column(String, nullable=False)
    note:     Mapped[Optional[str]] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="mf_watchpoints")


# ── Group 7: Investment Thesis ─────────────────────────────────────────────────

class InvestmentThesis(Base):
    __tablename__ = "investment_thesis"
    __table_args__ = (
        UniqueConstraint("user_id", "asset_type", "sym"),
        Index("idx_investment_thesis_user", "user_id"),
    )

    id:            Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:       Mapped[int]           = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    asset_type:    Mapped[str]           = mapped_column(String, nullable=False)
    sym:           Mapped[str]           = mapped_column(String, nullable=False)
    name:          Mapped[Optional[str]] = mapped_column(String)
    why_holding:   Mapped[Optional[str]] = mapped_column(Text)
    entry_trigger: Mapped[Optional[str]] = mapped_column(Text)
    exit_trigger:  Mapped[Optional[str]] = mapped_column(Text)
    conviction:    Mapped[int]           = mapped_column(Integer, default=3)
    review_date:   Mapped[Optional[str]] = mapped_column(String)
    created_at:    Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=_now)
    updated_at:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user: Mapped[User] = relationship(back_populates="investment_theses")


# ── Group 8: Swing Trades ──────────────────────────────────────────────────────

class SwingTrade(Base):
    __tablename__ = "swing_trades"
    __table_args__ = (
        Index("idx_swing_user", "user_id"),
    )

    id:           Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:      Mapped[int]            = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    sym:          Mapped[str]            = mapped_column(String, nullable=False)
    name:         Mapped[Optional[str]]  = mapped_column(String)
    sector:       Mapped[Optional[str]]  = mapped_column(String)
    mcap_cr:      Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    qty:          Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    avg_price:    Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    ltp:          Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    sl:           Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    target:       Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    exit_rule:    Mapped[Optional[str]]  = mapped_column(String)
    trade_type:   Mapped[str]            = mapped_column(String, default="technical")
    status:       Mapped[str]            = mapped_column(String, default="active")
    exit_price:   Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    exit_date:    Mapped[Optional[str]]  = mapped_column(String)
    realized_pnl: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    invested:     Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    return_pct:   Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    note:           Mapped[Optional[str]]  = mapped_column(Text)
    hold_long_term: Mapped[bool]           = mapped_column(Boolean, default=False)
    created_at:     Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=_now)
    updated_at:     Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user: Mapped[User] = relationship(back_populates="swing_trades")


# ── Group 9: Watchlists ────────────────────────────────────────────────────────

class Watchlist(Base):
    __tablename__ = "watchlists"
    __table_args__ = (
        Index("idx_watchlists_user", "user_id"),
    )

    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:    Mapped[int]           = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name:       Mapped[str]           = mapped_column(String, nullable=False)
    list_type:  Mapped[str]           = mapped_column(String, default="custom")
    created_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=_now)

    user:  Mapped[User]             = relationship(back_populates="watchlists")
    items: Mapped[list[WatchlistItem]] = relationship(back_populates="watchlist", cascade="all, delete-orphan")


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    __table_args__ = (
        UniqueConstraint("watchlist_id", "sym"),
        Index("idx_watchlist_items_wl", "watchlist_id"),
    )

    id:           Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    watchlist_id: Mapped[int]           = mapped_column(Integer, ForeignKey("watchlists.id", ondelete="CASCADE"), nullable=False)
    sym:          Mapped[str]           = mapped_column(String, nullable=False)
    name:         Mapped[Optional[str]] = mapped_column(String)
    note:         Mapped[Optional[str]] = mapped_column(Text)
    added_at:     Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=_now)

    watchlist: Mapped[Watchlist] = relationship(back_populates="items")


# ── Group 10: Alpha Scanner / Scan Vault ──────────────────────────────────────

class ScanRun(Base):
    __tablename__ = "scan_runs"
    __table_args__ = (
        Index("idx_scan_runs_user", "user_id"),
        Index("idx_scan_runs_scanned_at", "scanned_at"),
    )

    id:               Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:          Mapped[int]            = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    scanned_at:       Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    elapsed_seconds:  Mapped[Optional[float]] = mapped_column(Float)
    top_n:            Mapped[Optional[int]]  = mapped_column(Integer)
    min_score:        Mapped[Optional[float]] = mapped_column(Float)
    market_summary:   Mapped[Optional[dict]] = mapped_column(JSON)
    stats_json:       Mapped[Optional[dict]] = mapped_column(JSON)
    pass1_candidates: Mapped[Optional[int]]  = mapped_column(Integer)
    created_at:       Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=_now)

    user:  Mapped[User]          = relationship(back_populates="scan_runs")
    picks: Mapped[list[ScanPick]] = relationship(back_populates="scan_run", cascade="all, delete-orphan")


class ScanPick(Base):
    __tablename__ = "scan_picks"
    __table_args__ = (
        Index("idx_scan_picks_run", "scan_run_id"),
    )

    id:              Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_run_id:     Mapped[int]            = mapped_column(Integer, ForeignKey("scan_runs.id", ondelete="CASCADE"), nullable=False)
    symbol:          Mapped[str]            = mapped_column(String, nullable=False)
    name:            Mapped[Optional[str]]  = mapped_column(String)
    total_score:     Mapped[Optional[float]] = mapped_column(Float)
    grade:           Mapped[Optional[str]]  = mapped_column(String)
    criteria:        Mapped[Optional[dict]] = mapped_column(JSON)
    pullback_signal: Mapped[Optional[str]]  = mapped_column(String)
    sector:          Mapped[Optional[str]]  = mapped_column(String)
    from_pass:       Mapped[Optional[str]]  = mapped_column(String)
    levels:          Mapped[Optional[dict]] = mapped_column(JSON)
    is_holding:          Mapped[bool]           = mapped_column(Boolean, default=False)
    mcap_cr:             Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    is_portfolio_fit:    Mapped[bool]            = mapped_column(Boolean, default=False)
    is_microcap:         Mapped[bool]            = mapped_column(Boolean, default=False)
    scan_result:           Mapped[Optional[str]]   = mapped_column(String)
    initial_badge:         Mapped[Optional[str]]   = mapped_column(String)
    initial_badge_class:   Mapped[Optional[str]]   = mapped_column(String)
    promoted_to_trade_id:  Mapped[Optional[int]]   = mapped_column(Integer, nullable=True)
    # Scanner v2 composite scoring + risk + audit
    sector_momentum_score: Mapped[Optional[float]] = mapped_column(Float)
    leadership_score:      Mapped[Optional[float]] = mapped_column(Float)
    breakout_score:        Mapped[Optional[float]] = mapped_column(Float)
    composite_score:       Mapped[Optional[float]] = mapped_column(Float)
    is_ipo_pick:           Mapped[bool]            = mapped_column(Boolean, default=False)  # came from IPO sub-scan bucket
    is_ipo:                Mapped[bool]            = mapped_column(Boolean, default=False)  # underlying stock is a recent IPO
    added_at:              Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))  # when pick entered the basket (merge-aware baseline)
    tradeability_status:   Mapped[Optional[str]]   = mapped_column(String)
    position_size_json:    Mapped[Optional[dict]]  = mapped_column(JSON)
    audit_json:            Mapped[Optional[dict]]  = mapped_column(JSON)
    # Nightly tracking: strength re-check + closed detection (weekly frozen basket)
    tracking_json:         Mapped[Optional[dict]]  = mapped_column(JSON)

    scan_run: Mapped[ScanRun]              = relationship(back_populates="picks")
    outcomes: Mapped[list[ScanOutcome]]    = relationship(back_populates="pick", cascade="all, delete-orphan")


class ScanOutcome(Base):
    __tablename__ = "scan_outcomes"
    __table_args__ = (
        Index("idx_scan_outcomes_user", "user_id"),
        Index("idx_scan_outcomes_pick", "scan_pick_id"),
    )

    id:           Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_pick_id: Mapped[int]            = mapped_column(Integer, ForeignKey("scan_picks.id"), nullable=False)
    user_id:      Mapped[int]            = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    was_traded:   Mapped[bool]           = mapped_column(Boolean, default=False)
    qty:          Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    entry_price:  Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    exit_price:   Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    exit_date:    Mapped[Optional[str]]  = mapped_column(String)
    return_pct:   Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    outcome_note: Mapped[Optional[str]]  = mapped_column(Text)
    created_at:   Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=_now)

    pick: Mapped[ScanPick] = relationship(back_populates="outcomes")


# ── Group 11: Import Jobs ──────────────────────────────────────────────────────

class ImportJob(Base):
    __tablename__ = "import_jobs"
    __table_args__ = (
        Index("idx_import_jobs_user", "user_id"),
    )

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:     Mapped[int]           = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    source:      Mapped[str]           = mapped_column(String, nullable=False)
    filename:    Mapped[Optional[str]] = mapped_column(String)
    status:      Mapped[str]           = mapped_column(String, default="pending")
    parsed_rows: Mapped[Optional[int]] = mapped_column(Integer)
    error_msg:   Mapped[Optional[str]] = mapped_column(Text)
    created_at:  Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=_now)
    completed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="import_jobs")


# ── Group 12: Alerts & Notifications ──────────────────────────────────────────

class PriceAlert(Base):
    __tablename__ = "price_alerts"
    __table_args__ = (
        Index("idx_alerts_active", "user_id", "is_triggered"),
        Index("idx_alerts_sym_triggered", "sym", "is_triggered"),
    )

    id:           Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:      Mapped[int]            = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    sym:          Mapped[str]            = mapped_column(String, nullable=False)
    name:         Mapped[Optional[str]]  = mapped_column(String)
    condition:    Mapped[str]            = mapped_column(String, nullable=False)
    target_price: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    is_triggered: Mapped[bool]           = mapped_column(Boolean, default=False)
    triggered_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    note:         Mapped[Optional[str]]  = mapped_column(Text)
    created_at:   Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="price_alerts")


class PriceBand(Base):
    __tablename__ = "price_bands"
    __table_args__ = (
        UniqueConstraint("user_id", "sym", "category"),
        Index("idx_price_bands_user_active", "user_id", "is_active"),
    )

    id:        Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:   Mapped[int]            = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    sym:       Mapped[str]            = mapped_column(String, nullable=False)
    name:      Mapped[Optional[str]]  = mapped_column(String)
    category:  Mapped[str]            = mapped_column(String, default="long_term")  # long_term | swing | momentum
    ideal_lo:  Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    ideal_hi:  Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    accept_lo: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    accept_hi: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    sl:        Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    target:    Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    note:      Mapped[Optional[str]]  = mapped_column(Text)
    source:    Mapped[Optional[str]]  = mapped_column(String)
    is_active: Mapped[bool]           = mapped_column(Boolean, default=True)
    last_alert_zone: Mapped[Optional[str]] = mapped_column(String)  # ideal|acceptable|sl|target
    last_alerted_date: Mapped[Optional[str]] = mapped_column(String)  # ISO date — daily dedupe
    created_at: Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)

    user: Mapped[User] = relationship(back_populates="price_bands")


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        Index("idx_notif_unread", "user_id", "is_read"),
    )

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:     Mapped[int]           = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    type:        Mapped[Optional[str]] = mapped_column(String)
    title:       Mapped[Optional[str]] = mapped_column(String)
    body:        Mapped[Optional[str]] = mapped_column(Text)
    is_read:     Mapped[bool]          = mapped_column(Boolean, default=False)
    related_sym: Mapped[Optional[str]] = mapped_column(String)
    created_at:  Mapped[datetime]      = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="notifications")


# ── Group 13: Dashboard Config ─────────────────────────────────────────────────

class UserDashboardModule(Base):
    __tablename__ = "user_dashboard_modules"
    __table_args__ = (
        UniqueConstraint("user_id", "module_key"),
        Index("idx_dashboard_modules_user", "user_id"),
    )

    id:            Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:       Mapped[int]           = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    module_key:    Mapped[str]           = mapped_column(String, nullable=False)
    is_enabled:    Mapped[bool]          = mapped_column(Boolean, default=True)
    display_order: Mapped[int]           = mapped_column(Integer, default=0)
    custom_label:  Mapped[Optional[str]] = mapped_column(String)
    config:        Mapped[Optional[dict]] = mapped_column(JSON)

    user: Mapped[User] = relationship(back_populates="dashboard_modules")


# ── Group 14: User Preferences ────────────────────────────────────────────────

class UserPreference(Base):
    __tablename__ = "user_preferences"
    __table_args__ = (
        UniqueConstraint("user_id", "key"),
        Index("idx_user_preferences_user", "user_id"),
    )

    id:      Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int]           = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    key:     Mapped[str]           = mapped_column(String, nullable=False)
    value:   Mapped[Optional[str]] = mapped_column(Text)

    user: Mapped[User] = relationship(back_populates="preferences")


# ── Group 15: Portfolio Snapshot ──────────────────────────────────────────────

class PortfolioSnapshot(Base):
    __tablename__ = "portfolio_snapshots"
    __table_args__ = (
        Index("idx_portfolio_snapshot_user", "user_id"),
    )

    id:                     Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:                Mapped[int]            = mapped_column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    as_of:                  Mapped[Optional[str]]  = mapped_column(String)
    total_wealth:           Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    equity_value:           Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    mf_value:               Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    global_value:           Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    crypto_value:           Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    cash:                   Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    total_invested:         Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    total_pnl:              Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    total_pnl_pct:          Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    cagr:                   Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    stocks_pct:             Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    mf_pct:                 Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    cash_pct:               Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    global_pct:             Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    crypto_pct:             Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    allocation_sector_json: Mapped[Optional[dict]]  = mapped_column(JSON)
    allocation_mcap_json:   Mapped[Optional[dict]]  = mapped_column(JSON)
    first_trade_date:       Mapped[Optional[str]]  = mapped_column(String)
    computed_at:            Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ── Group 16: Swing Summary ────────────────────────────────────────────────────

class SwingSummary(Base):
    __tablename__ = "swing_summaries"

    id:              Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:         Mapped[int]            = mapped_column(Integer, ForeignKey("users.id"), unique=True, nullable=False)
    total_invested:  Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    open_count:      Mapped[int]            = mapped_column(Integer, default=0)
    closed_count:    Mapped[int]            = mapped_column(Integer, default=0)
    wins:            Mapped[int]            = mapped_column(Integer, default=0)
    win_rate:        Mapped[Optional[float]] = mapped_column(Float)
    win_rate_class:  Mapped[Optional[str]]  = mapped_column(String)
    closed_pl:       Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    updated_at:      Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ── Group 17: Price Snapshot ───────────────────────────────────────────────────

class PriceSnapshot(Base):
    __tablename__ = "price_snapshots"

    id:             Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    sym:            Mapped[str]            = mapped_column(String, unique=True, nullable=False)
    ltp:            Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    prev_close:     Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    day_high:       Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    day_low:        Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    day_change_pct: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    ohlc_today_json: Mapped[Optional[dict]] = mapped_column(JSON)
    fetched_at:     Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ── Group 18: Market Cache ─────────────────────────────────────────────────────

class MarketCache(Base):
    __tablename__ = "market_cache"
    __table_args__ = (
        Index("idx_market_cache_key", "key"),
    )

    id:          Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    key:         Mapped[str]           = mapped_column(String, unique=True, nullable=False)
    data_json:   Mapped[Optional[dict]] = mapped_column(JSON)
    ttl_seconds: Mapped[int]           = mapped_column(Integer, default=900)
    expires_at:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    updated_at:  Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ── Group 19: Market Snapshot Daily ───────────────────────────────────────────

class MarketSnapshotDaily(Base):
    __tablename__ = "market_snapshots_daily"
    __table_args__ = (
        Index("idx_market_snap_date", "date"),
    )

    id:                  Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    date:                Mapped[str]           = mapped_column(String, unique=True, nullable=False)
    indices_json:        Mapped[Optional[dict]] = mapped_column(JSON)
    breadth_json:        Mapped[Optional[dict]] = mapped_column(JSON)
    sector_heatmap_json: Mapped[Optional[dict]] = mapped_column(JSON)
    ad_ratio_json:       Mapped[Optional[dict]] = mapped_column(JSON)
    top_gainers_json:    Mapped[Optional[dict]] = mapped_column(JSON)
    rs_universe_json:    Mapped[Optional[dict]] = mapped_column(JSON)
    created_at:          Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=_now)


# ── Group 20: MF NAV History ───────────────────────────────────────────────────

class MFNavHistory(Base):
    __tablename__ = "mf_nav_history"
    __table_args__ = (
        UniqueConstraint("fund_key", "nav_date"),
        Index("idx_mf_nav_history_key", "fund_key"),
    )

    id:        Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    fund_key:  Mapped[str]           = mapped_column(String, nullable=False)
    nav_date:  Mapped[str]           = mapped_column(String, nullable=False)
    nav_value: Mapped[float]         = mapped_column(Numeric(18, 4), nullable=False)


# ── Group 21: Bhavcopy Daily ──────────────────────────────────────────────────

class BhavcopydAily(Base):
    __tablename__ = "bhavcopy_daily"
    __table_args__ = (
        UniqueConstraint("date", "sym"),
        Index("idx_bhavcopy_sym_date", "sym", "date"),
        Index("idx_bhavcopy_date", "date"),
    )

    id:       Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    date:     Mapped[str]            = mapped_column(String, nullable=False)
    sym:      Mapped[str]            = mapped_column(String, nullable=False)
    series:   Mapped[str]            = mapped_column(String, nullable=False, default="EQ")
    open:     Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    high:     Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    low:      Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    close:    Mapped[float]           = mapped_column(Numeric(18, 4), nullable=False)
    volume:   Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    tottrdval: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))


# ── Group 22: Provider Credentials (BYOK Vault) ────────────────────────────────

class ProviderCredential(Base):
    __tablename__ = "provider_credentials"
    __table_args__ = (
        UniqueConstraint("user_id", "provider", "key_label", name="uq_cred_user_provider_label"),
        Index("idx_cred_user", "user_id"),
    )

    id:               Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:          Mapped[int]            = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    provider:         Mapped[str]            = mapped_column(String, nullable=False)
    key_label:        Mapped[str]            = mapped_column(String, nullable=False)
    ciphertext:       Mapped[str]            = mapped_column(Text, nullable=False)
    status:           Mapped[str]            = mapped_column(String, default="active")
    last_used:        Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rl_cooldown_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    created_at:       Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=_now)

    user: Mapped[User] = relationship(back_populates="provider_credentials")


# ── Group 23: Kite Positions ───────────────────────────────────────────────────

class KitePosition(Base):
    __tablename__ = "kite_positions"
    __table_args__ = (
        Index("idx_kite_positions_user", "user_id"),
    )

    id:                Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:           Mapped[int]            = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    tradingsymbol:     Mapped[Optional[str]]  = mapped_column(String)
    exchange:          Mapped[Optional[str]]  = mapped_column(String)
    instrument_token:  Mapped[Optional[int]]  = mapped_column(BigInteger)
    product:           Mapped[Optional[str]]  = mapped_column(String)
    quantity:          Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    overnight_quantity: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    multiplier:        Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    average_price:     Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    last_price:        Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    close_price:       Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    value:             Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    pnl:               Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    m2m:               Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    unrealised:        Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    realised:          Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    buy_quantity:      Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    buy_price:         Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    buy_value:         Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    sell_quantity:     Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    sell_price:        Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    sell_value:        Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    day_buy_quantity:  Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    day_buy_price:     Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    day_sell_quantity: Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    day_sell_price:    Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    fetched_at:        Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ── Group 24: Kite Orders ──────────────────────────────────────────────────────

class KiteOrder(Base):
    __tablename__ = "kite_orders"
    __table_args__ = (
        UniqueConstraint("user_id", "order_id", name="uq_kite_order_user_orderid"),
        Index("idx_kite_orders_user", "user_id"),
    )

    id:                   Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:              Mapped[int]            = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    order_id:             Mapped[Optional[str]]  = mapped_column(String)
    parent_order_id:      Mapped[Optional[str]]  = mapped_column(String)
    exchange_order_id:    Mapped[Optional[str]]  = mapped_column(String)
    placed_by:            Mapped[Optional[str]]  = mapped_column(String)
    variety:              Mapped[Optional[str]]  = mapped_column(String)
    status:               Mapped[Optional[str]]  = mapped_column(String)
    status_message:       Mapped[Optional[str]]  = mapped_column(String)
    tradingsymbol:        Mapped[Optional[str]]  = mapped_column(String)
    exchange:             Mapped[Optional[str]]  = mapped_column(String)
    instrument_token:     Mapped[Optional[int]]  = mapped_column(BigInteger)
    transaction_type:     Mapped[Optional[str]]  = mapped_column(String)
    order_type:           Mapped[Optional[str]]  = mapped_column(String)
    product:              Mapped[Optional[str]]  = mapped_column(String)
    validity:             Mapped[Optional[str]]  = mapped_column(String)
    price:                Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    quantity:             Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    trigger_price:        Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    average_price:        Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    pending_quantity:     Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    filled_quantity:      Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    disclosed_quantity:   Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    cancelled_quantity:   Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    order_timestamp:      Mapped[Optional[str]]  = mapped_column(String)
    exchange_timestamp:   Mapped[Optional[str]]  = mapped_column(String)
    tag:                  Mapped[Optional[str]]  = mapped_column(String)
    fetched_at:           Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ── Group 25: Kite Trades ──────────────────────────────────────────────────────

class KiteTrade(Base):
    __tablename__ = "kite_trades"
    __table_args__ = (
        UniqueConstraint("user_id", "trade_id", name="uq_kite_trade_user_tradeid"),
        Index("idx_kite_trades_user", "user_id"),
    )

    id:                 Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:            Mapped[int]            = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    trade_id:           Mapped[Optional[str]]  = mapped_column(String)
    order_id:           Mapped[Optional[str]]  = mapped_column(String)
    exchange_order_id:  Mapped[Optional[str]]  = mapped_column(String)
    exchange:           Mapped[Optional[str]]  = mapped_column(String)
    tradingsymbol:      Mapped[Optional[str]]  = mapped_column(String)
    instrument_token:   Mapped[Optional[int]]  = mapped_column(BigInteger)
    product:            Mapped[Optional[str]]  = mapped_column(String)
    average_price:      Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    quantity:           Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    transaction_type:   Mapped[Optional[str]]  = mapped_column(String)
    fill_timestamp:     Mapped[Optional[str]]  = mapped_column(String)
    order_timestamp:    Mapped[Optional[str]]  = mapped_column(String)
    exchange_timestamp: Mapped[Optional[str]]  = mapped_column(String)
    fetched_at:         Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ── Group 26: Kite Margins ─────────────────────────────────────────────────────

class KiteMargin(Base):
    __tablename__ = "kite_margins"
    __table_args__ = (
        UniqueConstraint("user_id", "segment", name="uq_kite_margins_user_segment"),
    )

    id:             Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:        Mapped[int]            = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    segment:        Mapped[str]            = mapped_column(String, nullable=False)
    enabled:        Mapped[Optional[bool]] = mapped_column(Boolean)
    net:            Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    available_json: Mapped[Optional[dict]] = mapped_column(JSON)
    utilised_json:  Mapped[Optional[dict]] = mapped_column(JSON)
    fetched_at:     Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ── Group 27: Kite GTTs ────────────────────────────────────────────────────────

class KiteGTT(Base):
    __tablename__ = "kite_gtts"
    __table_args__ = (
        UniqueConstraint("user_id", "trigger_id", name="uq_kite_gtt_user_triggerid"),
    )

    id:                Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:           Mapped[int]            = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    trigger_id:        Mapped[Optional[int]]  = mapped_column(BigInteger)
    type:              Mapped[Optional[str]]  = mapped_column(String)
    status:            Mapped[Optional[str]]  = mapped_column(String)
    tradingsymbol:     Mapped[Optional[str]]  = mapped_column(String)
    exchange:          Mapped[Optional[str]]  = mapped_column(String)
    instrument_token:  Mapped[Optional[int]]  = mapped_column(BigInteger)
    trigger_values_json: Mapped[Optional[dict]] = mapped_column(JSON)
    last_price:        Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    orders_json:       Mapped[Optional[dict]] = mapped_column(JSON)
    created_at_kite:   Mapped[Optional[str]]  = mapped_column(String)
    updated_at_kite:   Mapped[Optional[str]]  = mapped_column(String)
    expires_at:        Mapped[Optional[str]]  = mapped_column(String)
    fetched_at:        Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))


# ── Group 28: LLM Analysis — Pick Analysis ────────────────────────────────────

class PickAnalysis(Base):
    __tablename__ = "pick_analysis"
    __table_args__ = (
        UniqueConstraint("scan_pick_id", "kind", name="uq_pick_analysis_pick_kind"),
        Index("idx_pick_analysis_pick", "scan_pick_id"),
    )

    id:              Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_pick_id:    Mapped[int]            = mapped_column(Integer, ForeignKey("scan_picks.id", ondelete="CASCADE"), nullable=False)
    kind:            Mapped[str]            = mapped_column(String, nullable=False)
    verdict_short:   Mapped[Optional[str]]  = mapped_column(String)
    verdict_class:   Mapped[Optional[str]]  = mapped_column(String)
    conviction_score: Mapped[Optional[int]] = mapped_column(Integer)
    thesis:          Mapped[Optional[str]]  = mapped_column(Text)
    risk_flags_json: Mapped[Optional[dict]] = mapped_column(JSON)
    failure_reason:  Mapped[Optional[str]]  = mapped_column(Text)
    detail_json:     Mapped[Optional[dict]] = mapped_column(JSON)
    model_used:      Mapped[Optional[str]]  = mapped_column(String)
    provider:        Mapped[Optional[str]]  = mapped_column(String)
    generated_at:    Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=_now)


# ── Group 29: LLM Analysis — Scan Review ─────────────────────────────────────

class ScanReview(Base):
    __tablename__ = "scan_reviews"
    __table_args__ = (
        UniqueConstraint("scan_run_id", "kind", name="uq_scan_review_run_kind"),
        Index("idx_scan_reviews_run", "scan_run_id"),
    )

    id:           Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    scan_run_id:  Mapped[int]            = mapped_column(Integer, ForeignKey("scan_runs.id", ondelete="CASCADE"), nullable=False)
    kind:         Mapped[str]            = mapped_column(String, nullable=False, server_default="auto")
    summary:      Mapped[Optional[str]]  = mapped_column(Text)
    strong_count: Mapped[Optional[int]]  = mapped_column(Integer)
    weak_count:   Mapped[Optional[int]]  = mapped_column(Integer)
    themes_json:  Mapped[Optional[dict]] = mapped_column(JSON)
    best_sym:     Mapped[Optional[str]]  = mapped_column(String)
    worst_sym:    Mapped[Optional[str]]  = mapped_column(String)
    model_used:   Mapped[Optional[str]]  = mapped_column(String)
    generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=_now)


# ── Group 30: LLM Analysis — Daily Market Note ────────────────────────────────

class MarketNoteDaily(Base):
    __tablename__ = "market_notes_daily"
    __table_args__ = (
        Index("idx_market_notes_date", "date"),
    )

    id:           Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    date:         Mapped[str]            = mapped_column(String, unique=True, nullable=False)
    note:         Mapped[Optional[str]]  = mapped_column(Text)
    context_json: Mapped[Optional[dict]] = mapped_column(JSON)
    model_used:   Mapped[Optional[str]]  = mapped_column(String)
    generated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=_now)


# ── Group: Scanner v2 Knowledge Base ───────────────────────────────────────────

class IndustryMaster(Base):
    __tablename__ = "industry_master"

    id:             Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    name:           Mapped[str]            = mapped_column(String, unique=True, nullable=False)
    kind:           Mapped[str]            = mapped_column(String, default="basic_industry")  # basic_industry | sector | broad
    num_stocks:     Mapped[Optional[int]]  = mapped_column(Integer)
    group_mcap_cr:  Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    # CSV seed (Industry Analytics.csv)
    perf_1w:        Mapped[Optional[float]] = mapped_column(Float)
    perf_1m:        Mapped[Optional[float]] = mapped_column(Float)
    perf_3m:        Mapped[Optional[float]] = mapped_column(Float)
    rank_1w:        Mapped[Optional[int]]  = mapped_column(Integer)
    rank_1m:        Mapped[Optional[int]]  = mapped_column(Integer)
    rank_3m:        Mapped[Optional[int]]  = mapped_column(Integer)
    rrg_quadrant:   Mapped[Optional[str]]  = mapped_column(String)
    csv_updated_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    # Live MCW synthetic index
    mcw_price:              Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    ema20:                  Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    ema50:                  Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    ema200:                 Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    ema200_rising:          Mapped[Optional[bool]]  = mapped_column(Boolean)
    pct_from_52wh:          Mapped[Optional[float]] = mapped_column(Float)
    pct_from_ath:           Mapped[Optional[float]] = mapped_column(Float)
    breadth_above_ema20:    Mapped[Optional[float]] = mapped_column(Float)
    breadth_above_ema50:    Mapped[Optional[float]] = mapped_column(Float)
    breadth_above_ema200:   Mapped[Optional[float]] = mapped_column(Float)
    count_near_high:        Mapped[Optional[int]]   = mapped_column(Integer)
    sector_momentum_score:  Mapped[Optional[float]] = mapped_column(Float)
    live_updated_at:        Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    kb_as_of:               Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    rrg_history:            Mapped[Optional[dict]]     = mapped_column(JSON)


class IndexMembership(Base):
    __tablename__ = "index_membership"
    __table_args__ = (
        Index("idx_index_membership_name_type", "index_name", "index_type"),
        Index("idx_index_membership_sym", "sym"),
        UniqueConstraint("sym", "index_name", "index_type", name="uq_index_membership"),
    )

    id:         Mapped[int]           = mapped_column(Integer, primary_key=True, autoincrement=True)
    sym:        Mapped[str]           = mapped_column(String, nullable=False)
    index_name: Mapped[str]           = mapped_column(String, nullable=False)
    index_type: Mapped[str]           = mapped_column(String, nullable=False)  # basic_industry | broad | custom


# ── Group: WS12 — Order-flow Intelligence ─────────────────────────────────────

class OrderAnnouncement(Base):
    __tablename__ = "order_announcements"
    __table_args__ = (
        UniqueConstraint("sym", "ann_date", "headline", name="uq_order_ann_sym_date_headline"),
        Index("idx_order_ann_sym", "sym"),
        Index("idx_order_ann_date", "ann_date"),
    )

    id:           Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    sym:          Mapped[str]            = mapped_column(String, nullable=False)
    ann_date:     Mapped[str]            = mapped_column(String, nullable=False)
    headline:     Mapped[str]            = mapped_column(String, nullable=False)
    body_excerpt: Mapped[Optional[str]]  = mapped_column(Text)
    value_cr:     Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    extraction:   Mapped[str]            = mapped_column(String, default="none")  # regex|llm|manual|none
    source_url:   Mapped[Optional[str]]  = mapped_column(String)
    created_at:   Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=_now)


class EarningsGuidance(Base):
    __tablename__ = "earnings_guidance"
    __table_args__ = (
        Index("idx_earnings_guidance_sym", "sym"),
    )

    id:                       Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    sym:                      Mapped[str]            = mapped_column(String, unique=True, nullable=False)
    fy_revenue_guidance_cr:   Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    q_revenue_guidance_cr:    Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    guidance_note:            Mapped[Optional[str]]  = mapped_column(Text)
    guidance_as_of:           Mapped[Optional[str]]  = mapped_column(String)
    updated_at:               Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


# ── Group: WS9 — Custom Indices ───────────────────────────────────────────────

class CustomIndex(Base):
    __tablename__ = "custom_indices"
    __table_args__ = (
        Index("idx_custom_indices_user_id", "user_id"),
        UniqueConstraint("user_id", "name", name="uq_custom_index_user_name"),
    )

    id:          Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id:     Mapped[int]            = mapped_column(Integer, ForeignKey("users.id"), nullable=False)
    name:        Mapped[str]            = mapped_column(String, nullable=False)
    kind:        Mapped[str]            = mapped_column(String, default="user")   # seeded | user
    weight_mode: Mapped[str]            = mapped_column(String, default="mcap")   # mcap | equal
    base_date:   Mapped[Optional[str]]  = mapped_column(String)                   # YYYY-MM-DD
    created_at:  Mapped[datetime]       = mapped_column(DateTime(timezone=True), default=_now)


class CustomIndexMember(Base):
    __tablename__ = "custom_index_members"
    __table_args__ = (
        Index("idx_custom_index_members_idx_id", "custom_index_id"),
        UniqueConstraint("custom_index_id", "sym", name="uq_custom_index_member"),
    )

    id:              Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    custom_index_id: Mapped[int] = mapped_column(Integer, ForeignKey("custom_indices.id", ondelete="CASCADE"), nullable=False)
    sym:             Mapped[str] = mapped_column(String, nullable=False)


class CustomIndexHistory(Base):
    __tablename__ = "custom_index_history"
    __table_args__ = (
        Index("idx_custom_index_history_idx_id", "custom_index_id"),
        Index("idx_custom_index_history_date", "date"),
        UniqueConstraint("custom_index_id", "date", name="uq_custom_index_history"),
    )

    id:              Mapped[int]   = mapped_column(Integer, primary_key=True, autoincrement=True)
    custom_index_id: Mapped[int]   = mapped_column(Integer, ForeignKey("custom_indices.id", ondelete="CASCADE"), nullable=False)
    date:            Mapped[str]   = mapped_column(String, nullable=False)   # YYYY-MM-DD
    value:           Mapped[float] = mapped_column(Numeric(18, 4), nullable=False)  # = close
    open:            Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    high:            Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    low:             Mapped[Optional[float]] = mapped_column(Numeric(18, 4))
    volume:          Mapped[Optional[float]] = mapped_column(Numeric(20, 2))


class StockSurveillance(Base):
    __tablename__ = "stock_surveillance"
    __table_args__ = (
        Index("idx_stock_surveillance_sym", "sym"),
    )

    id:              Mapped[int]            = mapped_column(Integer, primary_key=True, autoincrement=True)
    sym:             Mapped[str]            = mapped_column(String, unique=True, nullable=False)
    asm_stage:       Mapped[Optional[str]]  = mapped_column(String)
    gsm_stage:       Mapped[Optional[str]]  = mapped_column(String)
    esm_stage:       Mapped[Optional[str]]  = mapped_column(String)
    is_t2t:          Mapped[bool]           = mapped_column(Boolean, default=False)
    circuit_band_pct: Mapped[Optional[float]] = mapped_column(Float)
    delivery_pct:    Mapped[Optional[float]] = mapped_column(Float)
    flags:           Mapped[Optional[dict]] = mapped_column(JSON)
    source:          Mapped[Optional[str]]  = mapped_column(String)
    updated_at:      Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), default=_now)
