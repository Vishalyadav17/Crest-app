"""
Dashboard bootstrap endpoint — single call that returns all module data needed for initial page load.
All reads come from snapshot tables / market_cache; zero yfinance/requests calls.

GET /api/dashboard/bootstrap?modules=m1,m2,m3
Response: { cached_at, m1?, m2?, m3? }
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Request, Query
from sqlalchemy.orm import Session

from database import get_db
from deps import get_current_user_id
from auth import is_authenticated
from fastapi.responses import JSONResponse

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


# ── M1: Portfolio snapshot (pure DB reads) ────────────────────────────────────

def _m1_data(user_id: int, db: Session) -> dict:
    from models import PortfolioSnapshot
    from crud.mf import get_mf_holdings
    from crud.swings import get_swing_trades, get_swing_budget
    from services.portfolio_service import recompute_portfolio_snapshot

    snap = db.query(PortfolioSnapshot).filter(PortfolioSnapshot.user_id == user_id).first()
    if snap is None:
        snap = recompute_portfolio_snapshot(user_id, db)

    swings_data = get_swing_trades(db, user_id)
    mf_holdings = get_mf_holdings(db, user_id)

    mf_total_invested = sum(f["invested"] or 0 for f in mf_holdings if f.get("invested") is not None)
    mf_total_value    = sum(f["current"]  or 0 for f in mf_holdings if f.get("current") is not None)

    return {
        "overview": {
            "first_trade_date": snap.first_trade_date,
            "as_of":            snap.as_of,
            "total_wealth":     round(float(snap.total_wealth or 0)),
            "total_pnl":        round(float(snap.total_pnl or 0)),
            "total_pnl_pct":    round(float(snap.total_pnl_pct or 0), 1),
            "cagr":             round(float(snap.cagr), 1) if snap.cagr is not None else None,
            "stocks_pct":       round(float(snap.stocks_pct or 0), 1),
            "mf_pct":           round(float(snap.mf_pct or 0), 1),
            "cash_pct":         round(float(snap.cash_pct or 0), 1),
            "equity_value":     round(float(snap.equity_value or 0)),
            "mf_value":         round(float(snap.mf_value or 0)),
            "cash":             round(float(snap.cash or 0)),
            "computed_at":      snap.computed_at.isoformat() if snap.computed_at else None,
        },
        "allocation": {
            "sectors": snap.allocation_sector_json or {"total_equity": 0, "sectors": []},
            "mcap":    snap.allocation_mcap_json   or {"total_equity": 0, "buckets": []},
        },
        "swings_summary": swings_data["summary"],
        "mf_summary": {
            "total_invested": round(mf_total_invested),
            "total_value":    round(mf_total_value),
            "total_pnl":      round(mf_total_value - mf_total_invested),
            "total_pnl_pct":  round(
                (mf_total_value - mf_total_invested) / mf_total_invested * 100, 1
            ) if mf_total_invested else 0,
            "fund_count":     len(mf_holdings),
        },
    }


# ── M2: Market monitor (pure cache reads) ────────────────────────────────────

def _m2_data() -> dict:
    from shared.cache import cache_get

    return {
        "indices":       cache_get("market_overview|indices", 900),
        "ad_ratio":      cache_get("market_overview|ad_ratio", 900),
        "sectors":       cache_get("sector_heatmap", 900),
        "gainers_losers": cache_get("gainers_losers|10", 300),
        "breadth":       cache_get("market_breadth_v2", 14400),
        "news":          cache_get("market_news", 1800),
    }


# ── M3: Swing dashboard (pure DB reads) ─────────────────────────────────────

def _m3_data(user_id: int, db: Session) -> dict:
    from crud.scan import get_all_trades
    from crud.swings import get_swing_trades

    scanner = get_all_trades(db, user_id)
    swings  = get_swing_trades(db, user_id)

    ss = scanner["summary"]
    ws = swings["summary"]

    total_invested = (ss["total_invested"] or 0) + (ws["total_invested"] or 0)
    closed_pl      = (ss["closed_pl"] or 0)      + (ws["closed_pl"] or 0)
    scan_wins      = round((ss["win_rate"] or 0) / 100 * (ss["closed_count"] or 0))
    swing_wins     = round((ws["win_rate"] or 0) / 100 * (ws["closed_count"] or 0))
    total_closed   = (ss["closed_count"] or 0) + (ws["closed_count"] or 0)
    win_rate       = round((scan_wins + swing_wins) / total_closed * 100) if total_closed else None
    win_rate_class = ("green" if (win_rate or 0) >= 60 else "gold-c" if (win_rate or 0) > 0 else "")

    return {
        "scanner_trades": {
            "open":    scanner["open"],
            "closed":  scanner["closed"],
            "summary": ss,
        },
        "manual_swings": {
            "active":  swings["active"],
            "closed":  swings["closed"],
            "budget":  swings["budget"],
            "summary": ws,
        },
        "combined": {
            "total_invested":  round(total_invested, 2),
            "closed_pl":       round(closed_pl, 2),
            "win_rate":        win_rate,
            "win_rate_class":  win_rate_class,
            "open_count":      (ss["open_count"] or 0) + (ws["open_count"] or 0),
            "closed_count":    total_closed,
        },
    }


# ── Endpoint ──────────────────────────────────────────────────────────────────

@router.get("/bootstrap")
async def bootstrap(
    request: Request,
    modules: str = Query("m1,m2,m3", description="Comma-separated list of modules to include"),
    db: Session = Depends(get_db),
):
    """
    Single page-load endpoint. Returns pre-aggregated data for all requested modules.
    M1/M3 = DB snapshot reads (< 5ms). M2 = market_cache reads (< 2ms).
    If market_cache is cold, M2 keys will be null — FE should trigger individual refreshes.
    """
    if not is_authenticated(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)

    user_id = get_current_user_id(request, db)
    mods    = {m.strip().lower() for m in modules.split(",") if m.strip()}

    result: dict = {"cached_at": datetime.now(timezone.utc).isoformat()}

    try:
        if "m1" in mods:
            result["m1"] = _m1_data(user_id, db)
    except Exception:
        log.exception("bootstrap m1 failed for user %d", user_id)
        result["m1"] = {"error": "unavailable"}

    try:
        if "m2" in mods:
            result["m2"] = _m2_data()
    except Exception:
        log.exception("bootstrap m2 failed")
        result["m2"] = {"error": "unavailable"}

    try:
        if "m3" in mods:
            result["m3"] = _m3_data(user_id, db)
    except Exception:
        log.exception("bootstrap m3 failed for user %d", user_id)
        result["m3"] = {"error": "unavailable"}

    return result
