"""
Sector momentum scorer — ranks every index_master row (chartmaze basic-industry,
NSE sector index, broad tier) 0..100 by blending:

  Component A (CSV, weight ~0.40): Industry Analytics rank (1M/3M) + RRG quadrant.
      Only available for basic-industry rows that have an Industry Analytics row.
  Component B (live MCW, weight ~0.60): trend template + 52WH proximity + breadth
      from the synthetic MCW index (shared/mcw_index). Live → dominates daily scans
      because RRG/rank CSV goes stale within ~a week.

When CSV is unavailable (NSE sector/broad rows), the score is pure MCW.
Weights come from config.json -> scanner_v2.sector_momentum_weights.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path

from shared.mcw_index import compute_mcw_index, persist_to_industry_master

log = logging.getLogger(__name__)

_CONFIG = Path(__file__).parent.parent / "config.json"

_RRG_SCORE = {
    "Leading": 100.0, "Improving": 75.0, "Weakening": 40.0, "Lagging": 10.0,
}


def _cfg() -> dict:
    try:
        with open(_CONFIG) as f:
            return json.load(f).get("scanner_v2", {})
    except Exception:
        return {}


def _csv_component(row, n: int) -> float | None:
    """0..100 from Industry Analytics rank (1M/3M) + RRG. None if no rank data."""
    if row.rank_1m is None and row.rank_3m is None:
        return None
    n = max(n, 2)

    def rank_to_score(rank):
        if rank is None:
            return None
        return max(0.0, (1.0 - (rank - 1) / (n - 1)) * 100.0)

    s1 = rank_to_score(row.rank_1m)
    s3 = rank_to_score(row.rank_3m)
    parts, weights = [], []
    if s3 is not None:
        parts.append(s3); weights.append(0.6)
    if s1 is not None:
        parts.append(s1); weights.append(0.4)
    rank_score = sum(p * w for p, w in zip(parts, weights)) / sum(weights) if parts else 50.0

    rrg_score = _RRG_SCORE.get((row.rrg_quadrant or "").strip(), 50.0)
    return 0.6 * rank_score + 0.4 * rrg_score


def _mcw_component(sig: dict) -> float:
    """0..100 from MCW trend template + 52WH proximity + breadth."""
    # Trend (40): full if strict template, else partial by sub-checks.
    if sig.get("trend_template"):
        trend = 40.0
    else:
        checks = sum([
            sig["mcw_price"] > sig["ema20"],
            sig["ema20"] > sig["ema50"],
            sig["ema50"] > sig["ema200"],
            bool(sig.get("ema200_rising")),
        ])
        trend = checks / 4 * 40.0

    # Proximity to 52W high (30): within 0% → 30, ≥25% off → 0.
    pct = sig.get("pct_from_52wh")
    proximity = 0.0 if pct is None else max(0.0, (1.0 - min(pct, 25.0) / 25.0)) * 30.0

    # Breadth (30): average of % constituents above EMA20/50/200.
    breadth_avg = (sig["breadth_above_ema20"] + sig["breadth_above_ema50"]
                   + sig["breadth_above_ema200"]) / 3.0
    breadth = breadth_avg / 100.0 * 30.0

    return round(trend + proximity + breadth, 1)


def score_sector(row, db, n_industries: int, persist: bool = True) -> dict:
    cfg = _cfg().get("sector_momentum_weights", {"csv": 0.40, "mcw": 0.60})
    wc = cfg.get("csv", 0.40)
    wm = cfg.get("mcw", 0.60)

    sig = compute_mcw_index(row.name, row.kind, db)

    # When csv weight is 0 (KB v2 mode), use self-computed ranks from industry_master
    # (written by refresh_kb job) instead of CSV-derived rank/RRG data.
    if wc == 0.0 and row.rank_1m is not None:
        # KB v2: ranks are freshly computed; treat as csv_component for blending
        a = _csv_component(row, n_industries)
    elif wc == 0.0:
        a = None
    else:
        a = _csv_component(row, n_industries)

    b = _mcw_component(sig) if sig else None

    if b is None and a is None:
        score = None
    elif b is None:
        # When csv=0.0 but ranks available, use purely MCW with self-computed rank as tiebreak
        score = a
    elif a is None or wc == 0.0:
        score = b
    else:
        score = (wc * a + wm * b) / (wc + wm)

    if persist:
        if sig:
            persist_to_industry_master(db, sig)
        if score is not None:
            row.sector_momentum_score = round(score, 1)

    return {
        "name": row.name,
        "kind": row.kind,
        "csv_component": round(a, 1) if a is not None else None,
        "mcw_component": b,
        "score": round(score, 1) if score is not None else None,
        "mcw": sig,
        "kb_as_of": row.kb_as_of.isoformat() if row.kb_as_of else None,
    }


def rank_sectors(db, kinds: tuple[str, ...] = ("basic_industry", "sector"),
                 commit: bool = True) -> list[dict]:
    """Score + rank all index_master rows of the given kinds, best first."""
    from models import IndustryMaster
    rows = db.query(IndustryMaster).filter(IndustryMaster.kind.in_(kinds)).all()
    n = max((r.rank_3m or 0) for r in rows) if rows else 112
    n = max(n, 112)

    results = []
    for row in rows:
        try:
            results.append(score_sector(row, db, n))
        except Exception as e:
            log.warning("sector score failed %s: %s", row.name, e)
    if commit:
        db.commit()

    results = [r for r in results if r["score"] is not None]
    results.sort(key=lambda x: x["score"], reverse=True)
    return results
