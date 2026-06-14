"""Build pick context dict for deep-dive LLM prompts. Hard cap ~6KB serialized."""
from __future__ import annotations

import json
import logging
from datetime import date, timedelta

log = logging.getLogger(__name__)

_MAX_BYTES = 6144


def _trim(obj: dict, max_bytes: int = _MAX_BYTES) -> dict:
    s = json.dumps(obj, default=str)
    if len(s.encode()) <= max_bytes:
        return obj
    # Drop largest optional field until fits
    for drop_key in ("ohlcv_weekly", "ohlcv_recent", "news_headlines"):
        obj.pop(drop_key, None)
        if len(json.dumps(obj, default=str).encode()) <= max_bytes:
            break
    return obj


def build_pick_context(db, pick) -> dict:
    """
    Assemble pick context for deep-dive analysis.
    pick: ScanPick ORM object.
    Returns a dict safe to JSON-serialize and pass to LLM.
    """
    from models import (
        BhavcopydAily, MarketSnapshotDaily, MarketNoteDaily,
        PickAnalysis, ScanOutcome, KitePosition,
    )

    sym = pick.symbol

    # ── OHLCV: last 60 trading days from bhavcopy, condensed ─────────────────
    sixty_ago = (date.today() - timedelta(days=90)).isoformat()
    rows = (
        db.query(BhavcopydAily)
        .filter(BhavcopydAily.sym == sym, BhavcopydAily.date >= sixty_ago)
        .order_by(BhavcopydAily.date)
        .limit(65)
        .all()
    )
    # Last 10 dailies as-is; prior weeks aggregated by week
    recent_dailies = rows[-10:]
    earlier = rows[:-10]

    # weekly aggregation (group by ISO week)
    weeks: dict[str, dict] = {}
    for r in earlier:
        wk = date.fromisoformat(r.date).isocalendar()[:2]
        key = f"{wk[0]}-W{wk[1]:02d}"
        if key not in weeks:
            weeks[key] = {"week": key, "open": float(r.open or r.close), "high": float(r.high or r.close),
                          "low": float(r.low or r.close), "close": float(r.close), "vol": 0}
        w = weeks[key]
        w["high"] = max(w["high"], float(r.high or r.close))
        w["low"] = min(w["low"], float(r.low or r.close))
        w["close"] = float(r.close)
        w["vol"] = w["vol"] + int(r.volume or 0)

    ohlcv_weekly = list(weeks.values())
    ohlcv_recent = [
        {"date": r.date, "o": float(r.open or r.close), "h": float(r.high or r.close),
         "l": float(r.low or r.close), "c": float(r.close), "v": int(r.volume or 0)}
        for r in recent_dailies
    ]

    # ── Market breadth + sector heatmap (latest snapshot) ────────────────────
    snap = db.query(MarketSnapshotDaily).order_by(MarketSnapshotDaily.date.desc()).first()
    breadth = {}
    sector_entry = None
    if snap:
        breadth = snap.breadth_json or {}
        heatmap = snap.sector_heatmap_json or {}
        sector_entry = heatmap.get(pick.sector or "") or {}

    # ── Latest market note ───────────────────────────────────────────────────
    note_row = db.query(MarketNoteDaily).order_by(MarketNoteDaily.date.desc()).first()
    market_note = note_row.note[:400] if note_row and note_row.note else None

    # ── Prior validation analysis ────────────────────────────────────────────
    prior_validation = None
    pa = db.query(PickAnalysis).filter(
        PickAnalysis.scan_pick_id == pick.id,
        PickAnalysis.kind == "validation",
    ).first()
    if pa:
        prior_validation = {
            "verdict_short": pa.verdict_short,
            "verdict_class": pa.verdict_class,
            "thesis": pa.thesis,
            "risk_flags": pa.risk_flags_json,
        }

    # ── Trade outcomes ───────────────────────────────────────────────────────
    outcomes = db.query(ScanOutcome).filter(ScanOutcome.scan_pick_id == pick.id).all()
    outcomes_list = [
        {
            "was_traded": o.was_traded,
            "entry": float(o.entry_price) if o.entry_price else None,
            "exit": float(o.exit_price) if o.exit_price else None,
            "return_pct": float(o.return_pct) if o.return_pct else None,
        }
        for o in outcomes
    ]

    # ── Open Kite position ────────────────────────────────────────────────────
    kite_pos = None
    try:
        from sqlalchemy import func as sqlfunc
        kp = db.query(KitePosition).filter(
            KitePosition.tradingsymbol == sym,
        ).order_by(KitePosition.id.desc()).first()
        if kp and kp.quantity and float(kp.quantity) != 0:
            kite_pos = {
                "qty": float(kp.quantity),
                "avg_price": float(kp.average_price) if kp.average_price else None,
                "pnl": float(kp.pnl) if kp.pnl else None,
            }
    except Exception as e:
        log.debug("context: kite_pos lookup failed for %s: %s", sym, e)

    ctx = {
        "symbol": sym,
        "name": pick.name,
        "sector": pick.sector,
        "grade": pick.grade,
        "total_score": pick.total_score,
        "composite_score": pick.composite_score,
        "sector_momentum_score": pick.sector_momentum_score,
        "leadership_score": pick.leadership_score,
        "breakout_score": pick.breakout_score,
        "levels": pick.levels,
        "position_size": pick.position_size_json,
        "tradeability_flags": (pick.audit_json or {}).get("gate", {}).get("flags", []),
        "tracking": pick.tracking_json,
        "scan_result": pick.scan_result,
        "ohlcv_weekly": ohlcv_weekly,
        "ohlcv_recent": ohlcv_recent,
        "market_breadth": breadth,
        "sector_heatmap_entry": sector_entry,
        "market_note": market_note,
        "prior_validation": prior_validation,
        "outcomes": outcomes_list,
        "kite_position": kite_pos,
        "earnings_setup": (pick.audit_json or {}).get("earnings_setup"),
    }

    return _trim(ctx)
