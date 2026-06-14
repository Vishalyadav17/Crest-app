"""
Forward-track validation — THE METRIC WE TRUST before scaling capital.

For every historical ScanPick, snapshot the stock's price at +1/+2/+4/+12 weeks
after the scan date and measure the forward return from the recommendation baseline
(the pick's entry level, or the close on the scan date if no level). Aggregate
hit-rate + average forward return by score bucket, sector, and pass.

This is survivorship-free and look-ahead-free: it only asks "of the picks we ACTUALLY
made, in real time, which ones worked?" — no re-selection on hindsight.

Backend-logic rule: forward returns are computed here in Python with a single formula.
We deliberately do NOT write these into ScanOutcome — that table is the user's real
traded P&L (was_traded), and salting it with hypothetical snapshots would corrupt the
live win-rate. Output is a standalone report under data/validation/.

CLI:
  python backend/scripts/validation/forward_track.py
  python backend/scripts/validation/forward_track.py --json   # print full report
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

_BACKEND = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_BACKEND))

from shared.tickers import nse
from shared.yfinance_client import get_bulk_daily

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
log = logging.getLogger(__name__)

_OUT_DIR = _BACKEND / "data" / "validation"
_HORIZONS = {"1w": 7, "2w": 14, "4w": 28, "12w": 84}  # label -> days forward


def _score_bucket(score: float | None) -> str:
    if score is None:
        return "n/a"
    if score >= 90:
        return "90+"
    if score >= 80:
        return "80-90"
    if score >= 70:
        return "70-80"
    return "<70"


def _price_on_or_after(close: pd.Series, when: datetime) -> float | None:
    """First available close on/after `when`. None if series ends before it."""
    idx = close.index
    ts = pd.Timestamp(when).tz_localize(None)
    naive = idx.tz_localize(None) if getattr(idx, "tz", None) is not None else idx
    mask = naive >= ts
    if not mask.any():
        return None
    return float(close[mask].iloc[0])


def _sub_score_bucket(val: float | None, thresholds: list[float], labels: list[str]) -> str:
    """Bucket a sub-score into labeled ranges."""
    if val is None:
        return "n/a"
    for t, lbl in zip(thresholds, labels):
        if val >= t:
            return lbl
    return labels[-1]


def _load_picks(db) -> list[dict]:
    from models import ScanRun, ScanPick
    rows = (
        db.query(ScanPick, ScanRun.scanned_at)
        .join(ScanRun, ScanPick.scan_run_id == ScanRun.id)
        .filter(ScanRun.scanned_at.isnot(None))
        .all()
    )
    picks = []
    for p, scanned_at in rows:
        levels = p.levels or {}
        audit = p.audit_json or {}
        sub = audit.get("sub_scores", {})
        picks.append({
            "symbol": p.symbol,
            "scanned_at": scanned_at,
            "score": p.composite_score if p.composite_score is not None else p.total_score,
            "sector": p.sector or "Other",
            "pass": "IPO" if p.is_ipo_pick else (p.from_pass or "v2"),
            "entry": levels.get("entry"),
            # Sub-scores for attribution
            "sepa_total":       sub.get("sepa_total"),
            "rs_pct":           sub.get("rs_pct"),
            "leadership":       sub.get("leadership"),
            "breakout":         sub.get("breakout"),
            "sector_momentum":  sub.get("sector_momentum"),
        })
    return picks


def _agg(items: list[dict], horizon: str) -> dict:
    """Hit-rate + avg fwd-return over items that have a value for this horizon."""
    vals = [it["returns"][horizon] for it in items if it["returns"].get(horizon) is not None]
    if not vals:
        return {"n": 0, "hit_rate": None, "avg_return": None, "median_return": None}
    wins = sum(1 for v in vals if v > 0)
    s = pd.Series(vals)
    return {
        "n": len(vals),
        "hit_rate": round(wins / len(vals) * 100, 1),
        "avg_return": round(float(s.mean()), 2),
        "median_return": round(float(s.median()), 2),
    }


def _group_report(items: list[dict], key: str) -> dict:
    groups: dict[str, list[dict]] = {}
    for it in items:
        groups.setdefault(str(it[key]), []).append(it)
    out = {}
    for g, gi in groups.items():
        out[g] = {h: _agg(gi, h) for h in _HORIZONS}
    return out


def run_forward_track(db=None, *, asof: datetime | None = None) -> dict:
    own_db = db is None
    if own_db:
        from database import SessionLocal
        db = SessionLocal()
    asof = asof or datetime.now(timezone.utc)
    try:
        picks = _load_picks(db)
        if not picks:
            log.warning("No historical picks to forward-track.")
            return {"items": [], "generated_at": asof.isoformat(), "picks": 0}

        syms = sorted({p["symbol"] for p in picks})
        log.info("Forward-tracking %d picks across %d symbols", len(picks), len(syms))
        bulk = get_bulk_daily([nse(s) for s in syms], period="1y")

        items = []
        for p in picks:
            hist = bulk.get(nse(p["symbol"]))
            if hist is None or hist.empty or "Close" not in hist.columns:
                continue
            close = hist["Close"].dropna()
            scan_dt = pd.Timestamp(p["scanned_at"]).to_pydatetime()
            base = p["entry"] or _price_on_or_after(close, scan_dt)
            if not base or base <= 0:
                continue

            returns: dict[str, float | None] = {}
            for label, days in _HORIZONS.items():
                target_dt = scan_dt + pd.Timedelta(days=days)
                # only score a horizon that has fully elapsed
                if pd.Timestamp(target_dt).tz_localize(None) > pd.Timestamp(asof).tz_localize(None):
                    returns[label] = None
                    continue
                px = _price_on_or_after(close, target_dt)
                returns[label] = round((px - base) / base * 100, 2) if px else None

            items.append({
                "symbol": p["symbol"], "scanned_at": scan_dt.isoformat(),
                "score": p["score"], "score_bucket": _score_bucket(p["score"]),
                "sector": p["sector"], "pass": p["pass"],
                "base": round(base, 2), "returns": returns,
            })

        report = {
            "generated_at": asof.isoformat(),
            "picks_tracked": len(items),
            "horizons": list(_HORIZONS),
            "overall": {h: _agg(items, h) for h in _HORIZONS},
            "by_score_bucket": _group_report(items, "score_bucket"),
            "by_sector": _group_report(items, "sector"),
            "by_pass": _group_report(items, "pass"),
            "items": items,
        }

        _OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = _OUT_DIR / f"forward_track_{asof.strftime('%Y%m%d')}.json"
        with open(path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        log.info("Forward-track report → %s", path.name)
        return report
    finally:
        if own_db:
            db.close()


def run_attribution(db=None, *, asof: datetime | None = None) -> dict:
    """
    Per-component attribution: for each sub-score component, bucket by high/mid/low
    and compute hit-rate at 2w and 4w horizons.

    Writes data/validation/attribution_<date>.json and returns the dict.
    Only produces meaningful output with ≥20 picks that have sub_scores populated.
    """
    own_db = db is None
    if own_db:
        from database import SessionLocal
        db = SessionLocal()
    asof = asof or datetime.now(timezone.utc)

    COMPONENTS = {
        "sepa_total":      ([70, 50], ["high≥70", "mid50-70", "low<50"]),
        "rs_pct":          ([80, 60], ["high≥80", "mid60-80", "low<60"]),
        "leadership":      ([70, 50], ["high≥70", "mid50-70", "low<50"]),
        "breakout":        ([60, 40], ["high≥60", "mid40-60", "low<40"]),
        "sector_momentum": ([70, 50], ["high≥70", "mid50-70", "low<50"]),
    }

    try:
        picks = _load_picks(db)
        if not picks:
            return {"error": "no picks", "generated_at": asof.isoformat()}

        syms = sorted({p["symbol"] for p in picks})
        bulk = get_bulk_daily([nse(s) for s in syms], period="1y")

        items = []
        for p in picks:
            hist = bulk.get(nse(p["symbol"]))
            if hist is None or hist.empty or "Close" not in hist.columns:
                continue
            close = hist["Close"].dropna()
            scan_dt = pd.Timestamp(p["scanned_at"]).to_pydatetime()
            base = p["entry"] or _price_on_or_after(close, scan_dt)
            if not base or base <= 0:
                continue

            returns: dict[str, float | None] = {}
            for label, days in _HORIZONS.items():
                if label not in ("2w", "4w"):
                    continue
                target_dt = scan_dt + pd.Timedelta(days=days)
                if pd.Timestamp(target_dt).tz_localize(None) > pd.Timestamp(asof).tz_localize(None):
                    returns[label] = None
                    continue
                px = _price_on_or_after(close, target_dt)
                returns[label] = round((px - base) / base * 100, 2) if px else None

            items.append({**p, "returns": returns})

        attribution: dict[str, dict] = {}
        for comp, (thresholds, labels) in COMPONENTS.items():
            buckets: dict[str, list[dict]] = {}
            for it in items:
                b = _sub_score_bucket(it.get(comp), thresholds, labels)
                buckets.setdefault(b, []).append(it)
            attribution[comp] = {
                b: {h: _agg(g, h) for h in ("2w", "4w")}
                for b, g in buckets.items()
            }

        # Suggested weights: component with highest 4w hit-rate in top bucket → highest weight
        suggestions: list[dict] = []
        for comp, buckets in attribution.items():
            top_bucket = labels[0] if labels else None
            if top_bucket and top_bucket in buckets:
                agg4 = buckets[top_bucket].get("4w", {})
                suggestions.append({
                    "component": comp,
                    "top_bucket": top_bucket,
                    "4w_hit_rate": agg4.get("hit_rate"),
                    "4w_n": agg4.get("n", 0),
                })
        suggestions.sort(key=lambda x: (x["4w_hit_rate"] or 0), reverse=True)

        result = {
            "generated_at": asof.isoformat(),
            "picks_tracked": len(items),
            "attribution": attribution,
            "suggested_weight_order": suggestions,
            "note": "Re-tune composite weights manually once n≥50 picks. Observe, don't auto-apply.",
        }

        _OUT_DIR.mkdir(parents=True, exist_ok=True)
        path = _OUT_DIR / f"attribution_{asof.strftime('%Y%m%d')}.json"
        with open(path, "w") as f:
            json.dump(result, f, indent=2, default=str)
        log.info("Attribution report → %s", path.name)
        return result
    finally:
        if own_db:
            db.close()


def _print_summary(rep: dict) -> None:
    print("\n=== FORWARD-TRACK VALIDATION ===")
    print(f"Picks tracked: {rep.get('picks_tracked', 0)}  (generated {rep['generated_at'][:10]})")
    print("\nOverall (hit-rate% / avg-return% / n):")
    for h in rep.get("horizons", []):
        a = rep["overall"][h]
        hr = "—" if a["hit_rate"] is None else f"{a['hit_rate']}%"
        ar = "—" if a["avg_return"] is None else f"{a['avg_return']:+}%"
        print(f"  {h:>3}: {hr:>6}  {ar:>7}  n={a['n']}")
    print("\nBy score bucket (4w):")
    for b in ("90+", "80-90", "70-80", "<70"):
        a = rep.get("by_score_bucket", {}).get(b, {}).get("4w")
        if a and a["n"]:
            print(f"  {b:>6}: hit={a['hit_rate']}%  avg={a['avg_return']:+}%  n={a['n']}")
    print("\nNote: a horizon only scores once it has fully elapsed; recent picks show — until then.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Forward-track scan picks (truth metric)")
    ap.add_argument("--json", action="store_true", help="Print full report JSON")
    ap.add_argument("--attribution", action="store_true", help="Per-component attribution report")
    args = ap.parse_args()
    if args.attribution:
        rep = run_attribution()
        print(json.dumps(rep, indent=2, default=str))
    else:
        rep = run_forward_track()
        if args.json:
            print(json.dumps(rep, indent=2, default=str))
        else:
            _print_summary(rep)
