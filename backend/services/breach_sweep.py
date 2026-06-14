"""
Historical SL/target breach sweep for scan picks.

`recheck_basket` only runs nightly on the *current* week's basket, so picks in older vault
folders (and stale open My-Trades rows) never get their SL/target hits detected. This sweep walks
daily OHLC since each pick's scan date and freezes any pick that breached — setting `scan_result`
for untraded picks and closing the open `ScanOutcome` for traded ones.

Used by the one-time backfill script, the vault-folder open route, and My Trades load.
get_bulk_daily is disk-cached, so repeated same-day calls are cheap enough for on-load use.
"""
from __future__ import annotations

import logging
from datetime import date

log = logging.getLogger(__name__)


def sweep_run_breaches(db, run) -> int:
    """Detect + freeze SL/target breaches for one run's still-open picks. Returns #closed."""
    from models import ScanPick
    from shared.tickers import nse
    from shared.yfinance_client import get_bulk_daily
    from shared.strength_recheck import _clean_hist, _detect_close

    picks = [
        p for p in db.query(ScanPick).filter(ScanPick.scan_run_id == run.id).all()
        if not p.scan_result
    ]
    if not picks:
        return 0

    syms = [p.symbol for p in picks]
    try:
        bulk = get_bulk_daily([nse(s) for s in syms], period="1y")
    except Exception:
        log.exception("sweep_run_breaches: bulk fetch failed for run %s", run.id)
        return 0

    closed = 0
    for p in picks:
        lvl = p.levels or {}
        hist = _clean_hist(bulk.get(nse(p.symbol)))
        since = getattr(p, "added_at", None) or run.scanned_at  # per-pick baseline (merge-aware)
        result, level = _detect_close(hist, since, lvl.get("sl"), lvl.get("target"))
        if not result:
            continue
        p.scan_result = result
        # keep tracking_json in sync so grouping/reports don't show a closed pick as enterable
        tr = dict(p.tracking_json or {})
        tr["strength_status"] = "closed"
        tr["close_result"] = result
        p.tracking_json = tr
        exit_p = level if level is not None else (
            lvl.get("target") if result == "TARGET_HIT" else lvl.get("sl"))
        oc = next((o for o in p.outcomes if o.was_traded and not o.exit_price), None)
        if oc and oc.entry_price and exit_p:
            ep = float(oc.entry_price)
            oc.exit_price = exit_p
            oc.exit_date = str(date.today())
            oc.return_pct = round((exit_p - ep) / ep * 100, 2)
        closed += 1

    if closed:
        db.commit()
        log.info("sweep_run_breaches run=%s: %d picks closed", run.id, closed)
    return closed


def sweep_user_open_runs(db, user_id: int, exclude_run_id: int | None = None) -> int:
    """Sweep every run with any still-open pick (nightly background pass, all history)."""
    from models import ScanRun, ScanPick

    run_ids = [
        r[0] for r in db.query(ScanPick.scan_run_id)
        .join(ScanRun, ScanRun.id == ScanPick.scan_run_id)
        .filter(ScanRun.user_id == user_id, ScanPick.scan_result.is_(None))
        .distinct().all()
    ]
    total = 0
    for rid in run_ids:
        if exclude_run_id and rid == exclude_run_id:
            continue
        run = db.query(ScanRun).filter(ScanRun.id == rid).first()
        if run:
            total += sweep_run_breaches(db, run)
    return total


def sweep_open_trade_breaches(db, user_id: int) -> int:
    """Sweep every run that still has an open *traded* outcome for this user (My Trades load)."""
    from models import ScanRun, ScanPick, ScanOutcome

    run_ids = [
        r[0] for r in db.query(ScanPick.scan_run_id)
        .join(ScanOutcome, ScanOutcome.scan_pick_id == ScanPick.id)
        .join(ScanRun, ScanRun.id == ScanPick.scan_run_id)
        .filter(ScanRun.user_id == user_id, ScanOutcome.user_id == user_id,
                ScanOutcome.was_traded.is_(True), ScanOutcome.exit_price.is_(None),
                ScanPick.scan_result.is_(None))
        .distinct().all()
    ]
    total = 0
    for rid in run_ids:
        run = db.query(ScanRun).filter(ScanRun.id == rid).first()
        if run:
            total += sweep_run_breaches(db, run)
    return total

