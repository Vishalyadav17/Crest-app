"""Month-end time-exit close for scanner picks whose basket month has fully ended.

A monthly-basket pick that never hit SL or target stays scan_result=None forever, so the
vault shows '–' for a month that is already over. Once the basket's calendar month has ended,
an *untraded* pick is closed at that month's last trading-day close → scan_result='TIME_EXIT',
notional return measured from the entry baseline (entry_lo trigger). WIN if return >= 0 else FAIL.

Traded picks (held in My Trades) are never force-closed here — those carry forward and get a
live hold/tighten/exit advisory instead (see services/holding_advisory.py).
"""
from __future__ import annotations

import calendar
import logging
from datetime import date, datetime

log = logging.getLogger(__name__)

TIME_EXIT = "TIME_EXIT"


def _month_end(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _notional_entry(pick) -> float | None:
    lvl = pick.levels or {}
    for k in ("entry_lo", "entry"):
        v = lvl.get(k)
        if v:
            return float(v)
    return None


def time_exit_run(db, run) -> int:
    """Close untraded, still-open picks in a run whose basket month has fully ended.

    Returns number of picks closed via TIME_EXIT.
    """
    from models import ScanPick, ScanOutcome
    from shared.tickers import nse
    from shared.yfinance_client import get_bulk_daily
    from shared.strength_recheck import _clean_hist

    if not run.scanned_at:
        return 0
    ry, rm = run.scanned_at.year, run.scanned_at.month
    # only act on baskets whose month is strictly in the past
    today = date.today()
    if (ry, rm) >= (today.year, today.month):
        return 0
    m_end = _month_end(ry, rm)

    picks = [
        p for p in db.query(ScanPick).filter(ScanPick.scan_run_id == run.id).all()
        if not p.scan_result
        and not any(o.was_traded for o in p.outcomes)
    ]
    if not picks:
        return 0

    syms = [p.symbol for p in picks]
    try:
        bulk = get_bulk_daily([nse(s) for s in syms], period="1y")
    except Exception:
        log.exception("time_exit_run: bulk fetch failed for run %s", run.id)
        return 0

    closed = 0
    for p in picks:
        entry = _notional_entry(p)
        if not entry:
            continue
        hist = _clean_hist(bulk.get(nse(p.symbol)))
        if hist is None:
            continue
        try:
            import pandas as pd
            idx = pd.to_datetime(hist.index).tz_localize(None)
            upto = hist[idx <= pd.Timestamp(m_end)]
            if upto.empty:
                continue
            close_px = float(upto.iloc[-1].get("Close"))
            close_dt = str(pd.Timestamp(upto.index[-1]).date())
        except Exception:
            log.exception("time_exit_run: hist parse failed for %s", p.symbol)
            continue

        ret = round((close_px - entry) / entry * 100, 2)
        p.scan_result = TIME_EXIT
        tr = dict(p.tracking_json or {})
        tr["strength_status"] = "closed"
        tr["close_result"] = TIME_EXIT
        p.tracking_json = tr

        # synthetic outcome so the vault renders the % (was_traded=False = notional, not a real fill)
        oc = ScanOutcome(
            scan_pick_id=p.id,
            user_id=run.user_id,
            was_traded=False,
            entry_price=entry,
            exit_price=close_px,
            exit_date=close_dt,
            return_pct=ret,
            outcome_note=f"Month-end time-exit ({date(ry, rm, 1).strftime('%b %Y')}), no SL/target hit",
        )
        db.add(oc)
        closed += 1

    if closed:
        db.commit()
        log.info("time_exit_run run=%s: %d picks time-exited", run.id, closed)
    return closed


def time_exit_user_past_months(db, user_id: int) -> int:
    """Sweep every past-month run with still-open untraded picks. Returns #closed."""
    from models import ScanRun

    runs = db.query(ScanRun).filter(ScanRun.user_id == user_id).all()
    today = date.today()
    total = 0
    for run in runs:
        if not run.scanned_at:
            continue
        if (run.scanned_at.year, run.scanned_at.month) >= (today.year, today.month):
            continue
        total += time_exit_run(db, run)
    return total
