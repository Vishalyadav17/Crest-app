"""
Earnings-setup score — measures QTD order flow vs guidance and prev-quarter revenue.

Score:
  strong  — qtd_orders_cr >= prev-Q revenue AND >= guidance  (both thresholds met)
  building — either ratio >= 0.7
  neutral  — order data present but below thresholds
  unknown  — no order data for the quarter window

Compute on WRITE (nightly job writes to market_cache); endpoints read only.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import TypedDict

log = logging.getLogger(__name__)

_CACHE_TTL = 86400  # 24h
_STRONG_THRESHOLD = 1.0
_BUILDING_THRESHOLD = 0.7


def _current_quarter_start(today: date) -> date:
    """Return start date of current Indian FY quarter (Apr/Jul/Oct/Jan)."""
    month = today.month
    if month >= 4 and month <= 6:
        return date(today.year, 4, 1)
    elif month >= 7 and month <= 9:
        return date(today.year, 7, 1)
    elif month >= 10 and month <= 12:
        return date(today.year, 10, 1)
    else:  # Jan-Mar
        return date(today.year, 1, 1)


class SetupResult(TypedDict):
    sym: str
    qtd_orders_cr: float
    vs_prev_q: float | None
    vs_guidance: float | None
    score: str          # strong|building|neutral|unknown
    last_ann_date: str | None
    ann_count: int


def compute_setup(db, sym: str) -> SetupResult:
    """Compute earnings-setup score for `sym`. Returns a SetupResult dict."""
    from models import OrderAnnouncement, EarningsGuidance, StockMaster

    today = date.today()
    q_start = _current_quarter_start(today)
    q_start_str = q_start.isoformat()

    # QTD orders in current quarter
    rows = (
        db.query(OrderAnnouncement)
        .filter(
            OrderAnnouncement.sym == sym,
            OrderAnnouncement.ann_date >= q_start_str,
            OrderAnnouncement.value_cr.isnot(None),
        )
        .all()
    )

    qtd_orders_cr = sum(float(r.value_cr) for r in rows if r.value_cr)
    ann_count = len(rows)
    last_ann_date = max((r.ann_date for r in rows), default=None)

    if ann_count == 0:
        return SetupResult(
            sym=sym, qtd_orders_cr=0.0, vs_prev_q=None, vs_guidance=None,
            score="unknown", last_ann_date=None, ann_count=0,
        )

    # Previous quarter revenue
    sm = db.query(StockMaster).filter(StockMaster.sym == sym).first()
    prev_q_rev = float(sm.last_q_revenue_cr) if sm and sm.last_q_revenue_cr else None

    # Guidance
    guidance = db.query(EarningsGuidance).filter(EarningsGuidance.sym == sym).first()
    q_guidance = float(guidance.q_revenue_guidance_cr) if guidance and guidance.q_revenue_guidance_cr else None

    vs_prev_q = (qtd_orders_cr / prev_q_rev) if prev_q_rev else None
    vs_guidance = (qtd_orders_cr / q_guidance) if q_guidance else None

    ratios = [r for r in [vs_prev_q, vs_guidance] if r is not None]
    if ratios and all(r >= _STRONG_THRESHOLD for r in ratios):
        score = "strong"
    elif ratios and any(r >= _BUILDING_THRESHOLD for r in ratios):
        score = "building"
    elif ratios:
        score = "neutral"
    else:
        # orders exist but no benchmark to compare against
        score = "neutral"

    return SetupResult(
        sym=sym,
        qtd_orders_cr=round(qtd_orders_cr, 2),
        vs_prev_q=round(vs_prev_q, 3) if vs_prev_q is not None else None,
        vs_guidance=round(vs_guidance, 3) if vs_guidance is not None else None,
        score=score,
        last_ann_date=last_ann_date,
        ann_count=ann_count,
    )


def get_or_compute_setup(db, sym: str) -> SetupResult:
    """
    Return cached setup result or compute fresh.
    Cached in market_cache key `earnings_setup|{sym}` with 24h TTL.
    """
    from shared.cache import cache_get, cache_set
    key = f"earnings_setup|{sym}"
    cached = cache_get(key, _CACHE_TTL)
    if cached is not None:
        return cached  # type: ignore[return-value]
    result = compute_setup(db, sym)
    cache_set(key, dict(result), _CACHE_TTL)
    return result


def invalidate_setup_cache(sym: str) -> None:
    """Call after new OrderAnnouncement rows are written for `sym`."""
    from shared.cache import cache_set
    cache_set(f"earnings_setup|{sym}", None, 1)


def get_tracked_syms(db) -> list[str]:
    """
    Symbols to poll for order announcements:
      - latest basket scan picks
      - open swing trades
      - active price bands
    """
    from models import ScanRun, ScanPick, SwingTrade, PriceBand

    syms: set[str] = set()

    # latest scan run picks
    run = db.query(ScanRun).order_by(ScanRun.id.desc()).first()
    if run:
        for p in db.query(ScanPick).filter(ScanPick.scan_run_id == run.id).all():
            syms.add(p.symbol)

    # open swing trades
    for t in db.query(SwingTrade).filter(SwingTrade.status == "active").all():
        syms.add(t.sym)

    # research watchlist via price bands
    for b in db.query(PriceBand).filter(PriceBand.is_active.is_(True)).all():
        syms.add(b.sym)

    return sorted(syms)
