"""Reconcile per-pick AI verdicts + the basket review with ACTUAL outcomes.

Entry-time verdicts ("Strong uptrend, high conviction") were never updated once a pick closed,
so a pick that hit its stop still read as high-conviction. This generates an outcome-explained
verdict for every closed pick (winner → why it worked, loser → why it failed) and regenerates the
basket ScanReview from real returns. Used by the one-time backfill and the nightly close job.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_CLOSED = {"SL_HIT", "TARGET_HIT", "TIME_EXIT"}


def _entry_lo(pick) -> float | None:
    lvl = pick.levels or {}
    v = lvl.get("entry_lo") or lvl.get("entry")
    return float(v) if v else None


def _pct(frm, to) -> float | None:
    if not frm or to is None:
        return None
    return round((float(to) - float(frm)) / float(frm) * 100, 2)


def _pick_returns(pick) -> dict:
    """Return-context for ranking/summaries: realised, notional target/sl, unrealised."""
    lvl = pick.levels or {}
    entry = _entry_lo(pick)
    closed = next((o for o in pick.outcomes if o.exit_price is not None), None)
    return {
        "return_pct": float(closed.return_pct) if closed and closed.return_pct is not None else None,
        "target_pct": _pct(entry, lvl.get("target")),
        "sl_pct": _pct(entry, lvl.get("sl")),
        "unrealized_pct": _pct(entry, lvl.get("price")),
    }


def _is_green(pick) -> bool:
    closed = next((o for o in pick.outcomes if o.exit_price is not None), None)
    if closed and closed.return_pct is not None:
        return float(closed.return_pct) >= 0
    return pick.scan_result == "TARGET_HIT"


def _pick_dict(pick) -> dict:
    return {
        "symbol": pick.symbol,
        "sector": pick.sector,
        "grade": pick.grade,
        "total_score": pick.total_score,
        "composite_score": pick.composite_score,
        "scan_result": pick.scan_result,
        "criteria": pick.criteria,
        "outcomes": [
            {"was_traded": o.was_traded, "entry_price": float(o.entry_price) if o.entry_price else None,
             "exit_price": float(o.exit_price) if o.exit_price else None,
             "return_pct": float(o.return_pct) if o.return_pct is not None else None,
             "note": o.outcome_note}
            for o in pick.outcomes
        ],
    }


def _is_closed(pick) -> bool:
    return pick.scan_result in _CLOSED or any(o.exit_price is not None for o in pick.outcomes)


async def reconcile_run(db, run, *, regen_review: bool = True) -> dict:
    """Generate winner/failure verdicts for closed picks + (re)generate the basket review."""
    from models import ScanPick, PickAnalysis, ScanReview
    from services.llm.prompts.winner_review import run as run_winner
    from services.llm.prompts.failure import run as run_failure
    from services.llm.prompts.batch_review import run as run_review

    picks = db.query(ScanPick).filter(ScanPick.scan_run_id == run.id).all()
    counts = {"winner": 0, "failure": 0}

    for p in picks:
        if not _is_closed(p):
            continue
        # a closed pick is no longer held — drop any stale live advisory so it can't shadow
        # the outcome verdict (advisory outranks winner/failure in the display).
        stale_adv = db.query(PickAnalysis).filter(
            PickAnalysis.scan_pick_id == p.id, PickAnalysis.kind == "advisory").first()
        if stale_adv:
            db.delete(stale_adv)
            db.flush()
        green = _is_green(p)
        kind = "winner" if green else "failure"
        exists = db.query(PickAnalysis).filter(
            PickAnalysis.scan_pick_id == p.id, PickAnalysis.kind == kind
        ).first()
        if exists:
            continue
        pd = _pick_dict(p)
        result = await (run_winner if green else run_failure)(pd)
        if not result:
            continue
        db.add(PickAnalysis(
            scan_pick_id=p.id,
            kind=kind,
            verdict_short=result.get("verdict_short"),
            verdict_class=result.get("verdict_class", "pass" if green else "fail"),
            thesis=result.get("thesis"),
            risk_flags_json=result.get("risk_flags", []),
            failure_reason=result.get("failure_reason"),
            model_used=result.get("model_used"),
            provider=result.get("provider"),
        ))
        db.commit()
        counts[kind] += 1

    existing_review = db.query(ScanReview).filter(
        ScanReview.scan_run_id == run.id, ScanReview.kind == "auto"
    ).first()
    changed = counts["winner"] + counts["failure"] > 0
    if regen_review and (changed or existing_review is None):
        picks_data = []
        for p in picks:
            d = {"symbol": p.symbol, "sector": p.sector, "grade": p.grade,
                 "total_score": p.total_score, "composite_score": p.composite_score,
                 "scan_result": p.scan_result, "criteria": p.criteria}
            d.update(_pick_returns(p))
            picks_data.append(d)
        review = await run_review(picks_data)
        if review:
            row = existing_review
            if not row:
                row = ScanReview(scan_run_id=run.id, kind="auto")
                db.add(row)
            row.summary = review.get("summary")
            row.strong_count = review.get("strong_count")
            row.weak_count = review.get("weak_count")
            row.themes_json = review.get("themes", [])
            row.best_sym = review.get("best_sym")
            row.worst_sym = review.get("worst_sym")
            row.model_used = review.get("model_used")
            db.commit()
        counts["review"] = bool(review)

    log.info("reconcile_run run=%s: %s", run.id, counts)
    return counts
