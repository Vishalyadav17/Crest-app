from __future__ import annotations
import logging
from datetime import datetime, timezone
from sqlalchemy import func, case
from sqlalchemy.orm import Session, joinedload, selectinload, object_session
from models import ScanRun, ScanPick, ScanOutcome, PickAnalysis, ScanReview
from crud.stock import upsert_stock

log = logging.getLogger(__name__)


def _score_label(score) -> dict:
    """Classify a SEPA score into display label + CSS class. Single source of truth."""
    if score is None:
        return {"label": "–", "css": "low"}
    if score >= 80:
        return {"label": "HIGH", "css": "high"}
    if score >= 70:
        return {"label": "MID", "css": "mid"}
    return {"label": "LOW", "css": "low"}


def _compute_initial_badge(levels: dict) -> tuple[str | None, str | None]:
    cmp      = levels.get("price")
    entry_lo = levels.get("entry_lo")
    entry_hi = levels.get("entry_hi")
    if cmp and entry_lo and entry_hi:
        if cmp < entry_lo:
            return "BELOW", "below"
        if cmp <= entry_hi:
            return "IN RANGE", "in-range"
        return "ABOVE", "above"
    return None, None


def _build_scan_pick(scan_run_id: int, pick: dict) -> ScanPick:
    """Construct a ScanPick from a scanner_v2 pick dict (not added to session)."""
    sym    = pick.get("symbol", "")
    name   = pick.get("name", sym)
    levels = pick.get("levels", {})
    badge, badge_class = _compute_initial_badge(levels)
    return ScanPick(
        scan_run_id=scan_run_id,
        symbol=sym,
        name=name,
        total_score=pick.get("total"),
        grade=pick.get("grade"),
        criteria=pick.get("criteria", {}),
        pullback_signal=pick.get("pullback_signal"),
        sector=pick.get("sector"),
        from_pass=pick.get("from_pass"),
        levels=levels,
        is_holding=bool(pick.get("is_holding", False)),
        mcap_cr=pick.get("mcap_cr"),
        is_portfolio_fit=bool(pick.get("is_portfolio_fit", False)),
        is_microcap=bool(pick.get("is_microcap", False)),
        initial_badge=badge,
        initial_badge_class=badge_class,
        sector_momentum_score=pick.get("sector_momentum_score"),
        leadership_score=pick.get("leadership_score"),
        breakout_score=pick.get("breakout_score"),
        composite_score=pick.get("composite_score"),
        is_ipo_pick=bool(pick.get("is_ipo_pick", False)),
        is_ipo=bool(pick.get("is_ipo", False)),
        added_at=datetime.now(timezone.utc),  # baseline = when this pick entered the basket
        tradeability_status=pick.get("tradeability_status"),
        position_size_json=pick.get("position_size_json"),
        audit_json=pick.get("audit_json"),
    )


def _live_composite(p: ScanPick) -> float:
    """Composite used for the weekly survival ranking — prefer the live recheck value."""
    live = (p.tracking_json or {}).get("composite_live")
    if live is not None:
        return live
    if p.composite_score is not None:
        return p.composite_score
    return p.total_score if p.total_score is not None else -1.0


def merge_basket(db: Session, run: ScanRun, new_picks: list[dict], top_n: int) -> dict:
    """Survival-of-fittest weekly merge (nightly track).

    Pool = current OPEN picks (no scan_result) + brand-new candidates, ranked by live composite.
    Top-`top_n` survive. New survivors are inserted into the week run; open picks that fall out
    are marked scan_result='CHURNED' (kept for the churn log, excluded from future competition).
    Closed picks (SL_HIT/TARGET_HIT/CHURNED) are never re-added or re-ranked.
    """
    existing = (db.query(ScanPick)
                .options(joinedload(ScanPick.outcomes))
                .filter(ScanPick.scan_run_id == run.id).all())
    existing_syms = {p.symbol for p in existing}
    open_picks = [p for p in existing if not p.scan_result and not p.is_ipo_pick]

    # Picks the user has ENTERED (traded) or is holding long-term are never churned —
    # they're actively tracked regardless of score (weakening is surfaced via an alert instead).
    def _is_protected(p):
        return p.is_holding or any(o.was_traded for o in (p.outcomes or []))

    protected = [p for p in open_picks if _is_protected(p)]
    compete   = [p for p in open_picks if not _is_protected(p)]

    def _comp_new(d):
        c = d.get("composite_score")
        if c is None:
            c = d.get("total")
        return c if c is not None else -1.0

    candidates = [d for d in new_picks
                  if not d.get("is_ipo_pick") and d.get("symbol") not in existing_syms]

    # Protected picks occupy slots first; the rest compete for what's left.
    slots = max(0, top_n - len(protected))
    pool = ([("old", p, _live_composite(p)) for p in compete]
            + [("new", d, _comp_new(d)) for d in candidates])
    pool.sort(key=lambda t: t[2], reverse=True)
    survivors = pool[:slots]
    survivor_old = {id(p) for kind, p, _ in survivors if kind == "old"}

    added, churned = [], []
    for kind, obj, _ in survivors:
        if kind == "new":
            sp = _build_scan_pick(run.id, obj)
            db.add(sp)
            if sp.symbol:
                upsert_stock(db, sp.symbol, sp.name, sector=obj.get("sector"), mcap_cr=obj.get("mcap_cr"))
            added.append(sp.symbol)

    for p in compete:
        if id(p) not in survivor_old:
            p.scan_result = "CHURNED"
            churned.append(p.symbol)

    db.commit()
    log.info("merge_basket run=%s: +%d added, %d churned, %d protected",
             run.id, len(added), len(churned), len(protected))
    return {"added": added, "churned": churned, "protected": [p.symbol for p in protected]}


def save_scan_run(db: Session, user_id: int, result: dict) -> int:
    scanned_at_raw = result.get("scanned_at")
    if isinstance(scanned_at_raw, str):
        try:
            scanned_at = datetime.fromisoformat(scanned_at_raw.replace("Z", "+00:00"))
        except Exception:
            scanned_at = datetime.now(timezone.utc)
    elif isinstance(scanned_at_raw, datetime):
        scanned_at = scanned_at_raw
    else:
        scanned_at = datetime.now(timezone.utc)
    if scanned_at.tzinfo is None:
        scanned_at = scanned_at.replace(tzinfo=timezone.utc)

    run = ScanRun(
        user_id=user_id,
        scanned_at=scanned_at,
        elapsed_seconds=result.get("elapsed_seconds"),
        top_n=result.get("top_n"),
        min_score=result.get("min_score"),
        market_summary=result.get("market_summary", {}),
        pass1_candidates=result.get("pass1_candidates"),
        created_at=datetime.now(timezone.utc),
    )
    db.add(run)
    db.flush()

    pick_objs = []
    for pick in result.get("picks", []):
        p = _build_scan_pick(run.id, pick)
        db.add(p)
        pick_objs.append((p, pick))
        if p.symbol:
            upsert_stock(db, p.symbol, p.name, sector=pick.get("sector"), mcap_cr=pick.get("mcap_cr"))

    # Compute and store stats_json on the run
    success_count = 0
    failure_count = 0
    traded_count  = 0
    rr_vals: list[float] = []
    sector_counts: dict[str, int] = {}

    for p_obj, pick in pick_objs:
        lvl = pick.get("levels") or {}
        if lvl.get("rr"):
            rr_vals.append(lvl["rr"])
        sec = pick.get("sector") or "Other"
        sector_counts[sec] = sector_counts.get(sec, 0) + 1

    total_picks = len(pick_objs)
    sector_dist = sorted(
        [{"sector": s, "count": c, "pct": round(c / total_picks * 100) if total_picks else 0}
         for s, c in sector_counts.items()],
        key=lambda x: -x["count"]
    )[:5]

    run.stats_json = {
        "success_count": success_count,
        "failure_count": failure_count,
        "traded_count":  traded_count,
        "avg_rr":        round(sum(rr_vals) / len(rr_vals), 1) if rr_vals else None,
        "total_count":   total_picks,
        "sector_dist":   sector_dist,
    }

    db.commit()
    return run.id


def _load_run_with_picks(q):
    """Eagerly load picks + outcomes in 2 queries (avoids N+1)."""
    return q.options(
        joinedload(ScanRun.picks).joinedload(ScanPick.outcomes)
    )


def get_latest_scan(db: Session, user_id: int) -> dict | None:
    run = _load_run_with_picks(
        db.query(ScanRun).filter(ScanRun.user_id == user_id).order_by(ScanRun.scanned_at.desc())
    ).first()
    if not run:
        return None
    return _run_to_dict(run)


def list_scan_history(db: Session, user_id: int, limit: int = 20, offset: int = 0) -> list[dict]:
    runs = (
        db.query(ScanRun)
        .filter(ScanRun.user_id == user_id)
        .options(selectinload(ScanRun.picks))
        .order_by(ScanRun.scanned_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    result = []
    for r in runs:
        summary = r.market_summary or {}
        result.append({
            "id":          r.id,
            "scanned_at":  r.scanned_at.isoformat() if r.scanned_at else None,
            "picks_count": len(r.picks),
            "signal":      summary.get("signal"),
            "top_n":       r.top_n,
            "min_score":   r.min_score,
        })
    return result


def get_scan_run(db: Session, user_id: int, run_id: int) -> dict | None:
    run = _load_run_with_picks(
        db.query(ScanRun).filter(ScanRun.id == run_id, ScanRun.user_id == user_id)
    ).first()
    if not run:
        return None
    return _run_to_dict(run)


def _run_to_dict(run: ScanRun) -> dict:
    market_summary = run.market_summary or {}

    # Batch-load LLM verdicts for all picks in this run (one query, no N+1).
    db = object_session(run)
    pick_ids = [p.id for p in run.picks]
    ai_map: dict[int, dict] = {}
    hold_map: dict[int, int] = {}
    if db is not None and pick_ids:
        # outcome verdicts (winner/failure/retro) are authoritative for a closed pick — they
        # outrank the entry-time validation so a stopped-out pick never shows "high conviction".
        # advisory (live hold/exit call on an open held pick) tops everything; outcome verdicts
        # (winner/failure/retro) win for a closed pick; deep > entry-time validation.
        _kind_pri = {"advisory": 4, "failure": 3, "winner": 3, "outcome_retro": 3, "deep": 2, "validation": 1}
        for a in db.query(PickAnalysis).filter(PickAnalysis.scan_pick_id.in_(pick_ids)).all():
            slot = ai_map.setdefault(a.scan_pick_id, {})
            pri = _kind_pri.get(a.kind, 0)
            if pri >= slot.get("_pri", -1):
                slot["verdict"] = a.verdict_short
                slot["class"]   = a.verdict_class
                slot["kind"]    = a.kind
                slot["_pri"]    = pri
            slot["has_detail"] = slot.get("has_detail") or bool(a.thesis or a.failure_reason)
            # holding horizon comes from the deep-dive analysis (single source of truth)
            if a.kind == "deep" and (a.detail_json or {}).get("hold_horizon_days"):
                hold_map[a.scan_pick_id] = (a.detail_json or {}).get("hold_horizon_days")

    picks = []
    for p in run.picks:
        outcomes = []
        for o in p.outcomes:
            absolute_pl = None
            if o.entry_price and o.exit_price and o.qty:
                absolute_pl = round((float(o.exit_price) - float(o.entry_price)) * float(o.qty), 2)
            outcomes.append({
                "id":           o.id,
                "was_traded":   o.was_traded,
                "qty":          float(o.qty) if o.qty is not None else None,
                "entry_price":  float(o.entry_price) if o.entry_price is not None else None,
                "exit_price":   float(o.exit_price) if o.exit_price is not None else None,
                "exit_date":    o.exit_date,
                "return_pct":   float(o.return_pct) if o.return_pct is not None else None,
                "absolute_pl":  absolute_pl,
                "outcome_note": o.outcome_note,
            })

        # Update live stats from outcomes (success/failure/traded counts can change as outcomes are recorded)
        for o in p.outcomes:
            pass  # stats_json is refreshed via update_scan_stats below when outcomes change

        sl = _score_label(p.total_score)
        picks.append({
            "id":                p.id,
            "symbol":            p.symbol,
            "name":              p.name or p.symbol,
            "total":             p.total_score,
            "score_label":       sl["label"],
            "score_class":       sl["css"],
            "grade":             p.grade,
            "criteria":          p.criteria or {},
            "pullback_signal":   p.pullback_signal,
            "sector":            p.sector,
            "from_pass":         p.from_pass,
            "levels":            p.levels or {},
            "is_holding":        p.is_holding,
            "mcap_cr":           float(p.mcap_cr) if p.mcap_cr is not None else None,
            "is_portfolio_fit":  p.is_portfolio_fit,
            "is_microcap":       p.is_microcap,
            "scan_result":         p.scan_result,
            "initial_badge":       p.initial_badge,
            "initial_badge_class": p.initial_badge_class,
            "promoted_to_trade_id": p.promoted_to_trade_id,
            "sector_momentum_score": p.sector_momentum_score,
            "leadership_score":    p.leadership_score,
            "breakout_score":      p.breakout_score,
            "composite_score":     p.composite_score,
            "is_ipo_pick":         p.is_ipo_pick,
            "is_ipo":              p.is_ipo,
            "tradeability_status": p.tradeability_status,
            "tradeability_flags":  ((p.audit_json or {}).get("gate") or {}).get("flags") or [],
            "position_size_json":  p.position_size_json,
            "audit_json":          p.audit_json,
            "tracking":            p.tracking_json,
            "strength_status":     (p.tracking_json or {}).get("strength_status"),
            "band_state":          (p.tracking_json or {}).get("band_state"),
            "outcomes":            outcomes,
            "ai":                  ai_map.get(p.id),
            "hold_horizon_days":   hold_map.get(p.id),
        })

    # Stats: use stored value; recompute outcome-based counters live (outcomes change after scan)
    stored_stats = run.stats_json or {}
    success_count = 0
    failure_count = 0
    traded_count  = 0
    for p in picks:
        outcomes = p.get("outcomes") or []
        traded = any(o["was_traded"] for o in outcomes)
        if traded:
            traded_count += 1
        closed_outcome = next((o for o in outcomes if o.get("exit_price")), None)
        if closed_outcome:
            if (closed_outcome.get("return_pct") or 0) > 0:
                success_count += 1
            else:
                failure_count += 1
        elif p.get("scan_result") == "TARGET_HIT" and not traded:
            success_count += 1
        elif p.get("scan_result") == "SL_HIT" and not traded:
            failure_count += 1

    stats = {
        "success_count": success_count,
        "failure_count": failure_count,
        "traded_count":  traded_count,
        "avg_rr":        stored_stats.get("avg_rr"),
        "total_count":   stored_stats.get("total_count", len(picks)),
        "sector_dist":   stored_stats.get("sector_dist", []),
    }

    review = None
    if db is not None:
        r = (db.query(ScanReview)
             .filter(ScanReview.scan_run_id == run.id, ScanReview.kind == "auto").first()
             or db.query(ScanReview).filter(ScanReview.scan_run_id == run.id).first())
        if r:
            review = {
                "summary":      r.summary,
                "strong_count": r.strong_count,
                "weak_count":   r.weak_count,
                "themes":       r.themes_json,
                "best_sym":     r.best_sym,
                "worst_sym":    r.worst_sym,
                "model_used":   r.model_used,
            }

    return {
        "id":               run.id,
        "scanned_at":       run.scanned_at.isoformat() if run.scanned_at else None,
        "elapsed_seconds":  run.elapsed_seconds,
        "top_n":            run.top_n,
        "min_score":        run.min_score,
        "market_summary":   market_summary,
        "pass1_candidates": run.pass1_candidates,
        "picks":            picks,
        "stats":            stats,
        "review":           review,
    }


def get_all_trades(
    db: Session, user_id: int, limit: int = 50, offset: int = 0,
    status: str | None = None,
) -> dict:
    """All scan_outcomes where was_traded=True for a user, with pick + run context.

    status: 'open' | 'closed' | None (all). open_count / closed_count in summary
    are always accurate total counts regardless of pagination.
    """
    base_q = (
        db.query(ScanOutcome, ScanPick, ScanRun)
        .join(ScanPick, ScanOutcome.scan_pick_id == ScanPick.id)
        .join(ScanRun, ScanPick.scan_run_id == ScanRun.id)
        .filter(ScanOutcome.user_id == user_id, ScanOutcome.was_traded.is_(True))
    )

    open_q   = base_q.filter(ScanOutcome.exit_price.is_(None))
    closed_q = base_q.filter(ScanOutcome.exit_price.isnot(None))

    open_count   = open_q.count()
    win_row = (
        db.query(
            func.count(ScanOutcome.id).label("total"),
            func.sum(case((ScanOutcome.return_pct > 0, 1), else_=0)).label("wins"),
        )
        .join(ScanPick, ScanOutcome.scan_pick_id == ScanPick.id)
        .join(ScanRun, ScanPick.scan_run_id == ScanRun.id)
        .filter(ScanOutcome.user_id == user_id, ScanOutcome.was_traded.is_(True),
                ScanOutcome.exit_price.isnot(None))
        .first()
    )
    closed_count = win_row.total or 0
    _wins        = win_row.wins  or 0
    win_rate     = round(_wins / closed_count * 100) if closed_count else None
    win_rate_class = ("green" if (win_rate or 0) >= 60 else "gold-c" if (win_rate or 0) > 0 else "")

    if status == "open":
        rows_q = open_q
    elif status == "closed":
        rows_q = closed_q
    else:
        rows_q = base_q

    rows = (
        rows_q
        .order_by(ScanRun.scanned_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    open_trades, closed_trades = [], []
    for outcome, pick, run in rows:
        levels = pick.levels or {}
        sl = _score_label(pick.total_score)
        trade = {
            "outcome_id":   outcome.id,
            "pick_id":      pick.id,
            "symbol":       pick.symbol,
            "name":         pick.name or pick.symbol,
            "sector":       pick.sector,
            "grade":        pick.grade,
            "total_score":  pick.total_score,
            "score_label":  sl["label"],
            "score_class":  sl["css"],
            "scanned_at":   run.scanned_at.isoformat() if run.scanned_at else None,
            "entry_price":  float(outcome.entry_price) if outcome.entry_price is not None else None,
            "exit_price":   float(outcome.exit_price) if outcome.exit_price is not None else None,
            "exit_date":    outcome.exit_date,
            "qty":          float(outcome.qty) if outcome.qty is not None else None,
            "return_pct":   float(outcome.return_pct) if outcome.return_pct is not None else None,
            "outcome_note": outcome.outcome_note,
            "sl":           levels.get("sl"),
            "target":       levels.get("target"),
            "entry_lo":     levels.get("entry_lo"),
            "entry_hi":     levels.get("entry_hi"),
        }
        (closed_trades if outcome.exit_price else open_trades).append(trade)

    for t in open_trades:
        t["invested"] = round((t["entry_price"] or 0) * (t["qty"] or 0), 2) if (t["entry_price"] and t["qty"]) else None

    for t in closed_trades:
        if t["entry_price"] and t["exit_price"] and t["qty"]:
            t["absolute_pl"] = round((t["exit_price"] - t["entry_price"]) * t["qty"], 2)
        else:
            t["absolute_pl"] = None

    total_invested = sum(t["invested"] or 0 for t in open_trades)
    closed_pl      = sum(t["absolute_pl"] or 0 for t in closed_trades)

    return {
        "open":   open_trades,
        "closed": closed_trades,
        "summary": {
            "total_invested": round(total_invested, 2),
            "closed_pl":      round(closed_pl, 2),
            "win_rate":       win_rate,
            "win_rate_class": win_rate_class,
            "open_count":     open_count,
            "closed_count":   closed_count,
        },
    }


def update_pick_result(db: Session, pick_id: int, result: str) -> bool:
    """Set scan_result on a pick (SL_HIT or TARGET_HIT). Idempotent — won't overwrite existing."""
    pick = db.query(ScanPick).filter(ScanPick.id == pick_id).first()
    if not pick:
        return False
    if pick.scan_result:
        return True
    pick.scan_result = result
    db.commit()
    return True


def save_scan_outcome(db: Session, user_id: int, pick_id: int, data: dict) -> dict | None:
    pick = db.query(ScanPick).filter(ScanPick.id == pick_id).first()
    if not pick:
        return None

    existing = db.query(ScanOutcome).filter(
        ScanOutcome.scan_pick_id == pick_id,
        ScanOutcome.user_id == user_id,
    ).first()

    def _f(val):
        try: return float(val) if val is not None else None
        except (TypeError, ValueError): return None

    entry = existing or ScanOutcome(scan_pick_id=pick_id, user_id=user_id, created_at=datetime.now(timezone.utc))
    entry.was_traded  = data.get("was_traded", False)
    entry.qty         = _f(data.get("qty"))
    entry.entry_price = _f(data.get("entry_price"))
    entry.exit_price  = _f(data.get("exit_price"))
    entry.exit_date   = data.get("exit_date")
    entry.outcome_note = data.get("outcome_note")
    if entry.entry_price and entry.exit_price:
        entry.return_pct = round((entry.exit_price - entry.entry_price) / entry.entry_price * 100, 2)
    else:
        entry.return_pct = None

    if not existing:
        db.add(entry)
    db.commit()
    db.refresh(entry)
    return {
        "id":           entry.id,
        "was_traded":   entry.was_traded,
        "qty":          float(entry.qty) if entry.qty is not None else None,
        "entry_price":  float(entry.entry_price) if entry.entry_price is not None else None,
        "exit_price":   float(entry.exit_price) if entry.exit_price is not None else None,
        "exit_date":    entry.exit_date,
        "return_pct":   float(entry.return_pct) if entry.return_pct is not None else None,
        "outcome_note": entry.outcome_note,
    }
