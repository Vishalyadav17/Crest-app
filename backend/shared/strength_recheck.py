"""
Nightly strength re-check for the weekly frozen basket.

For the current basket's picks:
  * recompute the composite (live) via scanner_v2._score_universe
  * detect CLOSED picks — target or SL touched since the pick date (daily OHLC)
  * classify each still-open pick:
      enterable — composite >= MIN_COMPOSITE and CMP <= entry_hi (zone intact)
      missed    — extended above entry_hi (zone blown), still tracked
      weak      — composite dropped below MIN_COMPOSITE, still tracked
  * persist the verdict on ScanPick.tracking_json (+ scan_result when newly closed)

Strength rule agreed with user: composite >= 70 AND CMP <= entry_hi AND not
SL/target hit AND tradeability not EXCLUDED.
"""
from __future__ import annotations
import logging
from datetime import datetime, timezone

import pandas as pd

log = logging.getLogger(__name__)

MIN_COMPOSITE = 70.0


def _clean_hist(raw) -> pd.DataFrame | None:
    if raw is None or getattr(raw, "empty", True):
        return None
    h = raw
    if isinstance(h.columns, pd.MultiIndex):
        h = h.droplevel(1, axis=1)
    h.columns = [str(c).capitalize() for c in h.columns]
    return h


def _detect_close(hist: pd.DataFrame, since, sl, target) -> tuple[str | None, float | None]:
    """Return (SL_HIT|TARGET_HIT|None, level) by walking daily candles since pick date.
    SL takes priority when both are touched on the same day (conservative)."""
    if hist is None or sl is None or target is None:
        return None, None
    try:
        df = hist
        if since is not None:
            idx = pd.to_datetime(df.index).tz_localize(None)
            df = df[idx >= pd.Timestamp(since).tz_localize(None)]
        for _, row in df.iterrows():
            lo = float(row.get("Low")) if row.get("Low") is not None else None
            hi = float(row.get("High")) if row.get("High") is not None else None
            if lo is not None and lo <= sl:
                return "SL_HIT", sl
            if hi is not None and hi >= target:
                return "TARGET_HIT", target
    except Exception:
        log.exception("_detect_close failed")
    return None, None


def recheck_basket(db, run, picks) -> dict:
    """Re-check every pick in the basket. Mutates ScanPick rows + commits.
    Returns a grouped dict for the report:
      {enterable[], missed[], weak[], closed[], ipo[], counts{}}.
    """
    from modules.swing_detector.scanner_v2 import (
        _stock_meta, _benchmark_close, _score_universe, _load_config)
    from shared.sector_momentum import rank_sectors
    from shared.tickers import nse
    from shared.yfinance_client import get_bulk_daily

    syms = [p.symbol for p in picks]
    cfg = _load_config()
    weights = cfg.get("composite_weights", {})

    # live sector scores (DB-backed, refreshed by its own job)
    try:
        ranked_sectors = rank_sectors(db)
    except Exception:
        ranked_sectors = []
    sector_scores = {s["name"]: (s.get("score") or 0.0) for s in ranked_sectors}

    bulk = get_bulk_daily([nse(s) for s in syms], period="1y")
    meta = _stock_meta(db, syms)
    benchmark = _benchmark_close()

    open_syms = [p.symbol for p in picks if not p.scan_result]
    comp_map: dict[str, dict] = {}
    if open_syms:
        try:
            ranked, _ = _score_universe(open_syms, bulk, meta, sector_scores, benchmark, weights)
            comp_map = {r["symbol"]: r for r in ranked}
        except Exception:
            log.exception("recheck composite recompute failed")

    now = datetime.now(timezone.utc)
    groups = {"enterable": [], "missed": [], "weak": [], "closed": [], "churned": [], "ipo": []}
    ipo_syms = {p.symbol for p in picks if p.is_ipo_pick}

    for p in picks:
        # a symbol that also qualifies as an IPO pick is shown only in the IPO group
        if not p.is_ipo_pick and p.symbol in ipo_syms:
            continue
        lvl = p.levels or {}
        hist = _clean_hist(bulk.get(nse(p.symbol)))
        cmp_px = None
        if hist is not None and len(hist):
            cmp_px = round(float(hist["Close"].dropna().iloc[-1]), 2)

        # 1) closed? (respect any already-set result; else detect from OHLC)
        result = p.scan_result
        level = None
        if not result:
            since = getattr(p, "added_at", None) or run.scanned_at  # baseline = when pick was added
            result, level = _detect_close(
                hist, since, lvl.get("sl"), lvl.get("target"))
            if result:
                p.scan_result = result

        entry = lvl.get("entry")
        comp_live = (comp_map.get(p.symbol) or {}).get("composite_score")
        composite = comp_live if comp_live is not None else p.composite_score
        entry_hi = lvl.get("entry_hi")

        if result == "CHURNED":  # dropped from the weekly basket by a higher-scored pick
            status = "churned"
            close_level = None
            ret_pct = None
        elif result:  # CLOSED (SL/target hit)
            close_level = level if level is not None else (
                lvl.get("target") if result == "TARGET_HIT" else lvl.get("sl"))
            ret_pct = None
            if entry and close_level:
                ret_pct = round((close_level - entry) / entry * 100, 1)
            status = "closed"
        else:
            below_or_in = (entry_hi is None) or (cmp_px is None) or (cmp_px <= entry_hi)
            if composite is not None and composite < MIN_COMPOSITE:
                status = "weak"
            elif not below_or_in:
                status = "missed"
            else:
                status = "enterable"
            ret_pct = None
            close_level = None

        band_state = None
        if cmp_px is not None and lvl.get("entry_lo") and entry_hi:
            if cmp_px > entry_hi:
                band_state = "extended"
            elif cmp_px < lvl["entry_lo"]:
                band_state = "approaching"
            else:
                band_state = "in_band"

        tracking = {
            "cmp": cmp_px,
            "composite_live": round(composite, 1) if composite is not None else None,
            "strength_status": status,
            "band_state": band_state,
            "close_result": result,
            "close_level": close_level,
            "return_pct": ret_pct,
            "checked_at": now.isoformat(),
        }
        p.tracking_json = tracking

        bucket = "ipo" if p.is_ipo_pick else (status if status in groups else "enterable")
        if p.is_ipo_pick:
            bucket = "ipo"
        groups[bucket].append({"pick": p, "tracking": tracking})

    db.commit()

    counts = {k: len(v) for k, v in groups.items()}
    log.info("recheck basket run=%s: %s", run.id, counts)
    return {**groups, "counts": counts}
