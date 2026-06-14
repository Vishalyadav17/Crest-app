"""
Module — Weekend Analysis Workbench.
BYOK deep-dive per pick, basket weekend review, retro on closed picks, Q&A chat.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from deps import get_current_user_id

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/research", tags=["research"])


def _pick_verdict(pa) -> dict | None:
    if pa is None:
        return None
    return {
        "kind": pa.kind,
        "conviction": pa.conviction_score,
        "verdict_short": pa.verdict_short,
        "verdict_class": pa.verdict_class,
        "thesis": pa.thesis,
        "risk_flags": pa.risk_flags_json,
        "detail": pa.detail_json,
        "model_used": pa.model_used,
        "provider": pa.provider,
        "generated_at": pa.generated_at.isoformat() if pa.generated_at else None,
    }


@router.get("/workbench")
async def workbench(
    request: Request,
    run_id: int | None = Query(None, description="week folder to load; defaults to latest"),
    db: Session = Depends(get_db),
):
    """
    Single payload for the whole Weekend Lab surface.
    Returns the selected (or latest) run + picks with all analyses + weekend review + previous retro,
    plus the list of available week folders so the Lab can switch between them.
    """
    from models import ScanRun, ScanPick, PickAnalysis, ScanReview, ScanOutcome
    from services.llm.access import user_has_llm
    from crud.scan import list_scan_history

    user_id = get_current_user_id(request, db)
    has_llm = user_has_llm(db, user_id)
    folders = list_scan_history(db, user_id, limit=12)

    # Selected run (explicit run_id) or latest
    q = db.query(ScanRun).filter(ScanRun.user_id == user_id)
    latest_run = (
        q.filter(ScanRun.id == run_id).first() if run_id
        else q.order_by(ScanRun.scanned_at.desc()).first()
    )
    if not latest_run:
        return {"run": None, "picks": [], "weekend_review": None, "retro": None,
                "folders": folders, "user_has_llm": has_llm}

    picks = (
        db.query(ScanPick)
        .filter(ScanPick.scan_run_id == latest_run.id)
        .order_by(ScanPick.composite_score.desc().nullslast())
        .all()
    )

    # Batch-load all PickAnalysis for these picks (no N+1)
    pick_ids = [p.id for p in picks]
    analyses = (
        db.query(PickAnalysis)
        .filter(PickAnalysis.scan_pick_id.in_(pick_ids))
        .all()
    )
    # Map pick_id → kind → analysis row
    analysis_map: dict[int, dict] = {}
    for a in analyses:
        analysis_map.setdefault(a.scan_pick_id, {})[a.kind] = a

    picks_payload = []
    for p in picks:
        by_kind = analysis_map.get(p.id, {})
        picks_payload.append({
            "id": p.id,
            "symbol": p.symbol,
            "name": p.name,
            "sector": p.sector,
            "grade": p.grade,
            "total_score": p.total_score,
            "composite_score": p.composite_score,
            "scan_result": p.scan_result,
            "levels": p.levels,
            "deep": _pick_verdict(by_kind.get("deep")),
            "validation": _pick_verdict(by_kind.get("validation")),
            "retro": _pick_verdict(by_kind.get("outcome_retro")),
        })

    # Weekend review for this run
    weekend_review = (
        db.query(ScanReview)
        .filter(ScanReview.scan_run_id == latest_run.id, ScanReview.kind == "weekend")
        .first()
    )
    review_payload = None
    if weekend_review:
        review_payload = {
            "summary": weekend_review.summary,
            "themes": weekend_review.themes_json,
            "model_used": weekend_review.model_used,
            "generated_at": weekend_review.generated_at.isoformat() if weekend_review.generated_at else None,
        }

    # Previous run retro (just summary of outcome_retros)
    prev_run = (
        db.query(ScanRun)
        .filter(ScanRun.user_id == user_id, ScanRun.id != latest_run.id)
        .order_by(ScanRun.scanned_at.desc())
        .first()
    )
    retro_payload = None
    if prev_run:
        prev_picks = db.query(ScanPick).filter(ScanPick.scan_run_id == prev_run.id).all()
        prev_ids = [p.id for p in prev_picks]
        prev_retros = (
            db.query(PickAnalysis)
            .filter(PickAnalysis.scan_pick_id.in_(prev_ids), PickAnalysis.kind == "outcome_retro")
            .all()
        ) if prev_ids else []
        if prev_retros:
            retro_payload = {
                "run_id": prev_run.id,
                "scanned_at": prev_run.scanned_at.isoformat() if prev_run.scanned_at else None,
                "picks": [
                    {
                        "symbol": next((p.symbol for p in prev_picks if p.id == r.scan_pick_id), ""),
                        "verdict_short": r.verdict_short,
                        "verdict_class": r.verdict_class,
                        "thesis": r.thesis,
                    }
                    for r in prev_retros
                ],
            }

    return {
        "run": {
            "id": latest_run.id,
            "scanned_at": latest_run.scanned_at.isoformat() if latest_run.scanned_at else None,
            "pick_count": len(picks),
        },
        "picks": picks_payload,
        "weekend_review": review_payload,
        "retro": retro_payload,
        "folders": folders,
        "user_has_llm": has_llm,
    }


@router.post("/deep-dive/{pick_id}")
async def deep_dive(pick_id: int, request: Request, db: Session = Depends(get_db)):
    """
    Run deep-dive analysis on a pick. BYOK first; falls back to system tier.
    Upserts (delete + insert) pick_analysis with kind='deep'.
    """
    from models import ScanPick, ScanRun, PickAnalysis
    from services.llm.context import build_pick_context
    from services.llm.prompts import deep_dive as dd_prompt

    user_id = get_current_user_id(request, db)

    pick = db.query(ScanPick).join(ScanRun).filter(
        ScanPick.id == pick_id,
        ScanRun.user_id == user_id,
    ).first()
    if not pick:
        raise HTTPException(status_code=404, detail="Pick not found")

    pick_ctx = await asyncio.to_thread(build_pick_context, db, pick)
    result = await dd_prompt.run(pick_ctx, tier="user", user_id=user_id, db=db)
    if result is None:
        raise HTTPException(status_code=503, detail="LLM unavailable — try again or add a model key in Settings")

    # Delete existing deep analysis (upsert via delete+insert)
    existing = db.query(PickAnalysis).filter(
        PickAnalysis.scan_pick_id == pick_id,
        PickAnalysis.kind == "deep",
    ).first()
    if existing:
        db.delete(existing)
        db.flush()

    pa = PickAnalysis(
        scan_pick_id=pick_id,
        kind="deep",
        verdict_short=result.get("verdict_short"),
        verdict_class=result.get("verdict_class"),
        conviction_score=int(result["conviction"]) if result.get("conviction") else None,
        thesis=result.get("thesis"),
        risk_flags_json=result.get("risk_flags"),
        detail_json={k: result[k] for k in result if k not in ("model_used", "provider")},
        model_used=result.get("model_used"),
        provider=result.get("provider"),
        generated_at=datetime.now(timezone.utc),
    )
    db.add(pa)
    db.commit()
    db.refresh(pa)

    return {
        "id": pa.id,
        "pick_id": pick_id,
        "conviction": pa.conviction_score,
        "verdict_short": pa.verdict_short,
        "verdict_class": pa.verdict_class,
        "thesis": pa.thesis,
        "risk_flags": pa.risk_flags_json,
        "detail": pa.detail_json,
        "model_used": pa.model_used,
        "provider": pa.provider,
        "generated_at": pa.generated_at.isoformat(),
    }


@router.post("/weekend-review/{run_id}")
async def weekend_review(run_id: int, request: Request, db: Session = Depends(get_db)):
    """
    Generate weekend basket review. Requires ≥3 picks with deep analysis.
    Persists as ScanReview kind='weekend'.
    """
    from models import ScanRun, ScanPick, PickAnalysis, ScanReview, MarketSnapshotDaily, MarketNoteDaily
    from services.llm.prompts import weekend_review as wr_prompt

    user_id = get_current_user_id(request, db)

    run = db.query(ScanRun).filter(ScanRun.id == run_id, ScanRun.user_id == user_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    picks = db.query(ScanPick).filter(ScanPick.scan_run_id == run_id).all()
    pick_ids = [p.id for p in picks]

    deep_analyses = db.query(PickAnalysis).filter(
        PickAnalysis.scan_pick_id.in_(pick_ids), PickAnalysis.kind == "deep",
    ).all() if pick_ids else []

    if len(deep_analyses) < 3:
        raise HTTPException(status_code=400, detail=f"Need ≥3 deep analyses, have {len(deep_analyses)}")

    pick_map = {p.id: p for p in picks}
    picks_verdicts = [
        {
            "symbol": pick_map[a.scan_pick_id].symbol if a.scan_pick_id in pick_map else "?",
            "verdict_class": a.verdict_class,
            "conviction": a.conviction_score,
            "verdict_short": a.verdict_short,
            "thesis": a.thesis,
            "sector": pick_map[a.scan_pick_id].sector if a.scan_pick_id in pick_map else None,
        }
        for a in deep_analyses
    ]

    # Closed picks with outcomes
    closed_outcomes = [
        {"symbol": p.symbol, "scan_result": p.scan_result, "sector": p.sector}
        for p in picks if p.scan_result
    ]

    # Market context
    note_row = db.query(MarketNoteDaily).order_by(MarketNoteDaily.date.desc()).first()
    market_note = note_row.note[:400] if note_row and note_row.note else None
    snap = db.query(MarketSnapshotDaily).order_by(MarketSnapshotDaily.date.desc()).first()
    breadth = snap.breadth_json if snap else {}

    result = await wr_prompt.run(picks_verdicts, closed_outcomes, market_note, breadth)
    if result is None:
        raise HTTPException(status_code=503, detail="LLM unavailable")

    # Upsert ScanReview kind='weekend'
    review = db.query(ScanReview).filter(
        ScanReview.scan_run_id == run_id, ScanReview.kind == "weekend",
    ).first()
    if review is None:
        review = ScanReview(scan_run_id=run_id, kind="weekend")
        db.add(review)

    review.summary = result.get("summary")
    review.themes_json = {k: result[k] for k in result if k not in ("model_used", "provider", "summary")}
    review.model_used = result.get("model_used")
    review.generated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(review)

    # Push the weekend-lab analysis to Telegram (as-is) once generated.
    try:
        from services.alert_service import telegram_enabled
        from services.telegram_service import send_telegram
        if telegram_enabled(db, user_id):
            lines = [f"🧪 Weekend Lab — {run.scanned_at:%b %Y} basket", ""]
            if review.summary:
                lines.append(review.summary)
            themes = review.themes_json or {}
            if isinstance(themes, dict):
                for v in themes.values():
                    if isinstance(v, list):
                        lines += [f"• {i}" for i in v if isinstance(i, str)]
                    elif isinstance(v, str):
                        lines.append(f"• {v}")
            if review.model_used:
                lines += ["", f"— {review.model_used}"]
            await send_telegram(user_id, "\n".join(lines)[:4000])
    except Exception:
        import logging
        logging.getLogger(__name__).debug("weekend-lab telegram push failed", exc_info=True)

    return {
        "id": review.id,
        "run_id": run_id,
        "summary": review.summary,
        "themes": review.themes_json,
        "model_used": review.model_used,
        "generated_at": review.generated_at.isoformat(),
    }


@router.post("/retro/{run_id}")
async def retro(run_id: int, request: Request, db: Session = Depends(get_db)):
    """
    Run retro on closed picks of a run: winners get winner_review, losers get failure analysis.
    Idempotent — skips picks that already have outcome_retro analysis.
    """
    from models import ScanRun, ScanPick, PickAnalysis
    from services.llm.prompts import winner_review as wr_prompt, failure as fail_prompt

    user_id = get_current_user_id(request, db)

    run = db.query(ScanRun).filter(ScanRun.id == run_id, ScanRun.user_id == user_id).first()
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    picks = db.query(ScanPick).filter(
        ScanPick.scan_run_id == run_id,
        ScanPick.scan_result.isnot(None),
    ).all()

    already_done = {
        a.scan_pick_id
        for a in db.query(PickAnalysis).filter(
            PickAnalysis.scan_pick_id.in_([p.id for p in picks]),
            PickAnalysis.kind == "outcome_retro",
        ).all()
    } if picks else set()

    processed = 0
    for pick in picks:
        if pick.id in already_done:
            continue

        pick_dict = {
            "symbol": pick.symbol,
            "sector": pick.sector,
            "grade": pick.grade,
            "total_score": pick.total_score,
            "scan_result": pick.scan_result,
            "criteria": pick.criteria,
            "outcomes": [],
        }

        is_winner = pick.scan_result in ("TARGET_HIT", "TARGET_PARTIAL")
        if is_winner:
            result = await wr_prompt.run(pick_dict)
        else:
            result = await fail_prompt.run(pick_dict)

        if result is None:
            continue

        pa = PickAnalysis(
            scan_pick_id=pick.id,
            kind="outcome_retro",
            verdict_short=result.get("verdict_short"),
            verdict_class=result.get("verdict_class"),
            thesis=result.get("thesis"),
            risk_flags_json=result.get("risk_flags"),
            failure_reason=result.get("failure_reason"),
            model_used=result.get("model_used"),
            provider=result.get("provider"),
            generated_at=datetime.now(timezone.utc),
        )
        db.add(pa)
        db.commit()
        processed += 1

    return {"ok": True, "processed": processed, "skipped": len(already_done)}


@router.post("/chat")
async def research_chat(request: Request, db: Session = Depends(get_db)):
    """
    Stateless Q&A on a pick. BYOK-only — 409 if no keys configured.
    Body: {pick_id: int, messages: [{role, content}, ...] (last 6 turns)}
    """
    from models import ScanPick, ScanRun
    from services.llm import chat as llm_chat, NoFreeCapacity
    from services.llm.access import user_has_llm
    from services.llm.context import build_pick_context

    user_id = get_current_user_id(request, db)

    # No hard BYOK gate — the chat tries the user's keys first, then falls back to system (env)
    # keys below, so it works whether or not in-app keys are configured.
    body = await request.json()
    pick_id = body.get("pick_id")
    history = body.get("messages", [])[-6:]

    pick = None
    if pick_id:
        pick = db.query(ScanPick).join(ScanRun).filter(
            ScanPick.id == pick_id, ScanRun.user_id == user_id,
        ).first()

    system_content = (
        "You are a swing-trade analyst assistant helping review a specific stock pick. "
        "Answer concisely and factually. Reference the pick context when relevant."
    )
    if pick:
        pick_ctx = await asyncio.to_thread(build_pick_context, db, pick)
        import json
        system_content += f"\n\nPick context:\n{json.dumps(pick_ctx, default=str)[:3000]}"

    messages = [{"role": "system", "content": system_content}] + history

    # Try the user's own BYOK keys first; fall back to system (env) keys so the chat works
    # even before any in-app keys are configured.
    for _tier in ("user", "system"):
        try:
            result = await llm_chat(
                messages,
                task="research_chat",
                tier=_tier,
                user_id=user_id if _tier == "user" else None,
                db=db if _tier == "user" else None,
                max_tokens=600,
            )
            return {"text": result["text"], "model_used": result["model"]}
        except NoFreeCapacity:
            continue
    raise HTTPException(status_code=409, detail="All LLM tiers exhausted (no keys or rate-limited)")
