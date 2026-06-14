"""
Scan jobs: nightly basket track, weekly basket establish, LLM post-scan,
market note, failure analysis, trade pruner.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from jobs import _IST

log = logging.getLogger(__name__)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _month_key(dt: datetime) -> str:
    """Month anchor (basket = one folder per calendar month, established on the
    month's 1st trading day; daily scans churn into it)."""
    return dt.astimezone(_IST).strftime("%Y-%m")


def _ensure_basket(db, user_id: int, force_establish: bool):
    """Return (ScanRun, kind). Establish a fresh scanner_v2 basket when forced or
    when no basket exists for the current month; otherwise reuse + track it.
    The daily 21:00 job auto-establishes on the month's first run (= 1st trading day)."""
    from models import ScanRun

    latest = (db.query(ScanRun)
              .filter(ScanRun.user_id == user_id)
              .order_by(ScanRun.id.desc()).first())
    this_month = _month_key(datetime.now(_IST))
    current = latest and latest.scanned_at and _month_key(latest.scanned_at) == this_month

    if force_establish or not current:
        from modules.swing_detector.scanner_v2 import run_scan_v2
        result = run_scan_v2(db, persist=True, user_id=user_id)
        run_id = result.get("run_id")
        run = db.query(ScanRun).filter(ScanRun.id == run_id).first() if run_id else None
        log.info("established fresh basket run=%s for user %d", run_id, user_id)
        return run, "establish"
    return latest, "track"


_HOLD_HORIZON_DAYS = 21   # default holding clock (~1 month) before a flat trade is flagged stale
_STALE_FLAT_PCT    = 3.0  # |return| under this after the horizon = "hasn't moved much"


def _alert_tracked(db, user_id: int) -> None:
    """For every ENTERED/held open pick across ALL the user's baskets (so holds carry across
    month rollover): (1) weakening alert when composite drops, (2) stale alert when the holding
    period elapsed and the trade is flat. Edge-triggered via tracking_json flags (no nightly spam)."""
    from sqlalchemy.orm import joinedload
    from datetime import datetime, timezone
    from models import ScanPick, ScanRun
    from services.alert_service import dispatch_alert

    now = datetime.now(timezone.utc)
    picks = (db.query(ScanPick)
             .join(ScanRun, ScanRun.id == ScanPick.scan_run_id)
             .options(joinedload(ScanPick.outcomes))
             .filter(ScanRun.user_id == user_id, ScanPick.scan_result.is_(None)).all())

    for p in picks:
        oc = next((o for o in (p.outcomes or []) if o.was_traded and not o.exit_price), None)
        if oc is None and not p.is_holding:
            continue
        tr = dict(p.tracking_json or {})

        # 1) weakening
        weak = tr.get("strength_status") == "weak"
        if weak and not tr.get("weak_alerted"):
            dispatch_alert(db, user_id, title=f"{p.symbol} weakening",
                           telegram_text=(f"⚠️ <b>{p.symbol} weakening</b> — composite dropped. "
                                          f"You hold this — consider tightening your stop-loss."),
                           notif_type="pick_weakening", related_sym=p.symbol,
                           notif_body="Composite dropped below threshold — tighten SL.")
            tr["weak_alerted"] = True
        elif not weak and tr.get("weak_alerted"):
            tr["weak_alerted"] = False

        # 2) stale (holding period elapsed + flat)
        if oc is not None and oc.entry_price and getattr(oc, "created_at", None):
            ca = oc.created_at if oc.created_at.tzinfo else oc.created_at.replace(tzinfo=timezone.utc)
            days = (now - ca).days
            cmp = tr.get("cmp")
            entry = float(oc.entry_price)
            ret = ((cmp - entry) / entry * 100) if (cmp and entry) else None
            stale = days >= _HOLD_HORIZON_DAYS and ret is not None and abs(ret) < _STALE_FLAT_PCT
            if stale and not tr.get("stale_alerted"):
                dispatch_alert(db, user_id, title=f"{p.symbol} holding period elapsed",
                               telegram_text=(f"⏱ <b>{p.symbol}</b> held {days}d and flat ({ret:+.1f}%). "
                                              f"Holding period elapsed — review: tighten SL / exit for a better-scored pick."),
                               notif_type="pick_stale", related_sym=p.symbol,
                               notif_body=f"Held {days}d, {ret:+.1f}% — review/close.")
                tr["stale_alerted"] = True
            elif not stale and tr.get("stale_alerted"):
                tr["stale_alerted"] = False

        p.tracking_json = tr
    db.commit()


def _sync_run_nightly(force_establish: bool = False) -> bool:
    """Nightly orchestrator: net-guard → establish-or-track basket → recheck → report.
    Returns True if a fresh basket was established for any user (caller runs LLM analysis)."""
    from shared.net_guard import has_internet
    if not has_internet():
        log.warning("nightly: offline — scan skipped for tonight")
        return False
    established_any = False

    from database import SessionLocal
    from models import User, ScanPick
    from services.alert_service import telegram_enabled
    from services.telegram_service import send_telegram_sync
    from shared.strength_recheck import recheck_basket
    from services.scan_report import build_caption, build_report
    from services.scan_image import render_basket_image

    db = SessionLocal()
    try:
        for u in db.query(User).all():
            try:
                run, kind = _ensure_basket(db, u.id, force_establish)
                if run is None:
                    continue
                if kind == "establish":
                    established_any = True
                picks = db.query(ScanPick).filter(ScanPick.scan_run_id == run.id).all()
                if not picks:
                    continue
                groups = recheck_basket(db, run, picks)

                # Survival-of-fittest daily merge (track only; establish already scanned fresh).
                # recheck above froze SL/target hits + refreshed live composites first, so the
                # merge pool ranks open picks (live) against tonight's fresh candidates.
                if kind == "track":
                    try:
                        from modules.swing_detector.scanner_v2 import run_scan_v2
                        from crud.scan import merge_basket
                        fresh = run_scan_v2(db, persist=False, user_id=u.id)
                        merged = merge_basket(db, run, fresh.get("picks", []),
                                              fresh.get("top_n", 10))
                        if merged["added"] or merged["churned"]:
                            picks = db.query(ScanPick).filter(ScanPick.scan_run_id == run.id).all()
                            groups = recheck_basket(db, run, picks)
                    except Exception:
                        log.exception("nightly merge failed for user %d", u.id)

                # Sweep SL/target breaches across the user's OTHER open runs (older vault folders);
                # the current basket was just handled by recheck_basket above.
                try:
                    from services.breach_sweep import sweep_user_open_runs
                    sweep_user_open_runs(db, u.id, exclude_run_id=run.id)
                except Exception:
                    log.exception("nightly breach sweep failed for user %d", u.id)

                try:
                    _alert_tracked(db, u.id)
                except Exception:
                    log.exception("nightly tracked-pick alerts failed for user %d", u.id)

                basket_date = run.scanned_at.astimezone(_IST).strftime("%-d %b") if run.scanned_at else None
                day_n = ((datetime.now(_IST).date() - run.scanned_at.astimezone(_IST).date()).days + 1
                         if run.scanned_at else None)

                if telegram_enabled(db, u.id):
                    caption = build_caption(run, groups, basket_date=basket_date,
                                            day_n=day_n, kind=kind)
                    try:
                        img = render_basket_image(run, groups, basket_date=basket_date,
                                                  day_n=day_n, kind=kind)
                        send_telegram_sync(u.id, caption, image_path=img)
                    except Exception:
                        log.exception("image render failed — falling back to text table")
                        send_telegram_sync(u.id, build_report(
                            run, groups, basket_date=basket_date, day_n=day_n, kind=kind))
                log.info("nightly %s done for user %d (%s)", kind, u.id, groups.get("counts"))
            except Exception:
                log.exception("nightly failed for user %d", u.id)
                continue
    finally:
        db.close()
    return established_any


# ── Job: nightly basket track (21:00 IST) ────────────────────────────────────

async def job_run_weekly_scan() -> None:
    """Nightly 21:00 IST — track the current month's basket (churn/merge) + push report.
    On the month's first run it auto-establishes a fresh basket; run LLM analysis then too."""
    try:
        established = await asyncio.to_thread(_sync_run_nightly, False)
        if established:
            await _async_llm_post_scan()
    except Exception:
        log.exception("job_run_weekly_scan (track) failed")


# ── Job: monthly basket establish (1st of month, 12:00 IST) ──────────────────

async def job_monthly_basket() -> None:
    """1st of month 12:00 IST — establish a fresh basket (10-12 + 1-2 IPO) + report + LLM."""
    try:
        await asyncio.to_thread(_sync_run_nightly, True)
        await _async_llm_post_scan()
    except Exception:
        log.exception("job_monthly_basket (establish) failed")


async def _async_llm_post_scan() -> None:
    """Generate validation + batch_review for the latest scan run (system keys, common)."""
    try:
        from database import SessionLocal
        from models import ScanRun, ScanPick, PickAnalysis, ScanReview

        db = SessionLocal()
        try:
            run = db.query(ScanRun).order_by(ScanRun.id.desc()).first()
            if not run:
                return

            picks = db.query(ScanPick).filter(ScanPick.scan_run_id == run.id).all()
            if not picks:
                return

            from services.llm.prompts.validation import run as run_validation
            from services.llm.prompts.batch_review import run as run_review

            picks_data = [
                {"symbol": p.symbol, "sector": p.sector, "grade": p.grade,
                 "total_score": p.total_score, "criteria": p.criteria, "mcap_cr": p.mcap_cr}
                for p in picks
            ]

            for i, pick in enumerate(picks):
                exists = db.query(PickAnalysis).filter(
                    PickAnalysis.scan_pick_id == pick.id,
                    PickAnalysis.kind == "validation",
                ).first()
                if exists:
                    continue
                result = await run_validation(picks_data[i])
                if result:
                    row = PickAnalysis(
                        scan_pick_id=pick.id,
                        kind="validation",
                        verdict_short=result.get("verdict_short"),
                        verdict_class=result.get("verdict_class"),
                        thesis=result.get("thesis"),
                        risk_flags_json=result.get("risk_flags", []),
                        model_used=result.get("model_used"),
                        provider=result.get("provider"),
                    )
                    db.add(row)
                    db.commit()

            review_exists = db.query(ScanReview).filter(ScanReview.scan_run_id == run.id).first()
            if not review_exists:
                review = await run_review(picks_data)
                if review:
                    row = ScanReview(
                        scan_run_id=run.id,
                        summary=review.get("summary"),
                        strong_count=review.get("strong_count"),
                        weak_count=review.get("weak_count"),
                        themes_json=review.get("themes", []),
                        best_sym=review.get("best_sym"),
                        worst_sym=review.get("worst_sym"),
                        model_used=review.get("model_used"),
                    )
                    db.add(row)
                    db.commit()
            log.info("LLM post-scan analysis complete for run %d", run.id)
        finally:
            db.close()
    except Exception:
        log.exception("_async_llm_post_scan failed")


# ── Job: nightly trade pruning (21:30 IST) ───────────────────────────────────

async def job_prune_open_recommendations() -> None:
    try:
        await asyncio.to_thread(_sync_prune_open_recommendations)
    except Exception:
        log.exception("job_prune_open_recommendations failed")


def _sync_prune_open_recommendations() -> None:
    from database import SessionLocal
    from models import User
    from crud.prefs import get_pref
    from services.trade_pruner import prune_open_recommendations
    from services.telegram_service import send_telegram_sync
    from services.alert_service import telegram_enabled

    db = SessionLocal()
    try:
        users = db.query(User).all()
        for u in users:
            if get_pref(db, u.id, "auto_prune_enabled", "1") != "1":
                continue
            pruned = prune_open_recommendations(u.id)
            if not (pruned and telegram_enabled(db, u.id)):
                continue
            for item in pruned:
                send_telegram_sync(
                    u.id,
                    f"<b>Pick pruned</b>: {item['sym']} — {item['reason'].replace('_', ' ')}",
                )
    finally:
        db.close()


# ── Job: LLM daily market note (post-close 16:15 IST) ────────────────────────

async def job_llm_market_note() -> None:
    try:
        from database import SessionLocal
        from models import MarketNoteDaily, MarketSnapshotDaily

        db = SessionLocal()
        try:
            # Only build a note from a snapshot that actually has breadth AND indices — otherwise
            # the model invents direction ("NIFTY down") from empty data. Target the freshest such
            # day, not strictly today, so a missed EOD (e.g. server offline) self-heals next run.
            snap = (
                db.query(MarketSnapshotDaily)
                .filter(MarketSnapshotDaily.breadth_json.isnot(None),
                        MarketSnapshotDaily.indices_json.isnot(None))
                .order_by(MarketSnapshotDaily.date.desc())
                .first()
            )
            if not snap or not snap.breadth_json or not snap.indices_json:
                log.info("market_note: no snapshot with real breadth+indices — skip (no misleading note)")
                return
            today = snap.date

            exists = db.query(MarketNoteDaily).filter(MarketNoteDaily.date == today).first()
            if exists:
                return

            context = {
                "date": today,
                "breadth": snap.breadth_json if snap else {},
                "indices": snap.indices_json if snap else {},
                "sector_heatmap": {
                    s["name"]: s.get("chg_pct", 0)
                    for s in (snap.sector_heatmap_json or {}).get("sectors", [])
                } if snap and snap.sector_heatmap_json else {},
            }
            from services.llm.prompts.market_note import run as run_note
            result = await run_note(context)
            if result:
                row = MarketNoteDaily(
                    date=today,
                    note=result.get("note"),
                    context_json=context,
                    model_used=result.get("model_used"),
                )
                db.add(row)
                db.commit()
                log.info("LLM market note generated: %s", today)
        finally:
            db.close()
    except Exception:
        log.exception("job_llm_market_note failed")


# ── Job: LLM failure analysis (daily 17:00) ───────────────────────────────────

async def job_llm_failure_analysis() -> None:
    """Reconcile outcome verdicts (winner/failure) + outcome-aware review for every run whose
    picks have closed since the last pass. Replaces the old SL-only failure pass so a stopped-out
    pick never keeps its entry-time 'high conviction' verdict and best/worst track real returns."""
    try:
        from database import SessionLocal
        from models import ScanRun
        from services.verdict_reconcile import reconcile_run

        db = SessionLocal()
        try:
            total = {"winner": 0, "failure": 0, "reviews": 0}
            for run in db.query(ScanRun).all():
                counts = await reconcile_run(db, run)
                total["winner"] += counts.get("winner", 0)
                total["failure"] += counts.get("failure", 0)
                total["reviews"] += 1 if counts.get("review") else 0
            log.info("LLM verdict reconcile: %s", total)
        finally:
            db.close()
    except Exception:
        log.exception("job_llm_failure_analysis failed")


# ── Job: fill deep-dive analysis for current basket (→ holding horizon) ───────

async def job_fill_deep_analysis() -> None:
    """Ensure every pick in each user's CURRENT-month basket has a deep-dive analysis, so the
    suggested holding horizon (hold_horizon_days) is populated and in sync across scanner/vault/
    forward-track. Idempotent — skips picks already analysed; new churned-in picks get it next run."""
    try:
        from datetime import datetime as _dt, timezone
        from database import SessionLocal
        from models import ScanRun, ScanPick, PickAnalysis, User
        from services.llm.context import build_pick_context
        from services.llm.prompts import deep_dive_agentic as dd_prompt

        db = SessionLocal()
        try:
            this_month = _month_key(datetime.now(_IST))
            filled = 0
            for u in db.query(User).all():
                run = (db.query(ScanRun)
                       .filter(ScanRun.user_id == u.id)
                       .order_by(ScanRun.id.desc()).first())
                if not run or not run.scanned_at or _month_key(run.scanned_at) != this_month:
                    continue
                for pick in db.query(ScanPick).filter(ScanPick.scan_run_id == run.id).all():
                    if pick.scan_result:  # closed picks don't need a forward holding horizon
                        continue
                    exists = db.query(PickAnalysis).filter(
                        PickAnalysis.scan_pick_id == pick.id, PickAnalysis.kind == "deep",
                    ).first()
                    if exists:
                        continue
                    try:
                        ctx = build_pick_context(db, pick)
                        result = await dd_prompt.run(ctx, tier="system", db=db)
                    except Exception as e:
                        log.debug("deep fill failed for %s: %s", pick.symbol, e)
                        continue
                    if not result:
                        continue
                    db.add(PickAnalysis(
                        scan_pick_id=pick.id,
                        kind="deep",
                        verdict_short=result.get("verdict_short"),
                        verdict_class=result.get("verdict_class"),
                        conviction_score=int(result["conviction"]) if result.get("conviction") else None,
                        thesis=result.get("thesis"),
                        risk_flags_json=result.get("risk_flags"),
                        detail_json={k: result[k] for k in result if k not in ("model_used", "provider")},
                        model_used=result.get("model_used"),
                        provider=result.get("provider"),
                        generated_at=_dt.now(timezone.utc),
                    ))
                    db.commit()
                    filled += 1
            log.info("deep-dive fill: %d picks analysed", filled)
        finally:
            db.close()
    except Exception:
        log.exception("job_fill_deep_analysis failed")


# ── Job: holding advisory for open held positions (daily 17:15) ───────────────

async def job_holding_advisory() -> None:
    """For every pick the user is HOLDING (open traded outcome), generate a live action advisory
    (hold / tighten SL / weakening / exit at target). Upserted as PickAnalysis kind='advisory'."""
    try:
        from datetime import datetime as _dt, date as _date, timezone
        from database import SessionLocal
        from models import ScanRun, ScanPick, ScanOutcome, PickAnalysis, User
        from services.llm.prompts import holding_advisory as adv

        db = SessionLocal()
        try:
            done = 0
            for u in db.query(User).all():
                held_ids = [r[0] for r in (
                        db.query(ScanPick.id)
                        .join(ScanOutcome, ScanOutcome.scan_pick_id == ScanPick.id)
                        .join(ScanRun, ScanRun.id == ScanPick.scan_run_id)
                        .filter(ScanRun.user_id == u.id, ScanOutcome.user_id == u.id,
                                ScanOutcome.was_traded.is_(True), ScanOutcome.exit_price.is_(None),
                                ScanPick.scan_result.is_(None))
                        .distinct().all())]
                held = db.query(ScanPick).filter(ScanPick.id.in_(held_ids)).all() if held_ids else []
                for pick in held:
                    oc = next((o for o in pick.outcomes if o.was_traded and o.exit_price is None), None)
                    lvl = pick.levels or {}
                    entry = float(oc.entry_price) if oc and oc.entry_price else (lvl.get("entry_lo") or lvl.get("entry"))
                    price = lvl.get("price")
                    ret = round((float(price) - float(entry)) / float(entry) * 100, 2) if entry and price else None
                    days_held = None
                    base = getattr(pick, "added_at", None) or pick.scan_run.scanned_at
                    if base:
                        days_held = (_date.today() - base.astimezone(_IST).date()).days
                    hh = None
                    da = db.query(PickAnalysis).filter(
                        PickAnalysis.scan_pick_id == pick.id, PickAnalysis.kind == "deep").first()
                    if da and da.detail_json:
                        hh = da.detail_json.get("hold_horizon_days")
                    ctx = {
                        "symbol": pick.symbol, "sector": pick.sector,
                        "entry_price": entry, "current_price": price,
                        "stop_loss": lvl.get("sl"), "target": lvl.get("target"),
                        "return_pct_so_far": ret, "days_held": days_held,
                        "suggested_hold_horizon_days": hh,
                        "composite_score": pick.composite_score,
                        "strength_status": (pick.tracking_json or {}).get("strength_status"),
                        "band_state": (pick.tracking_json or {}).get("band_state"),
                    }
                    result = await adv.run(ctx)
                    if not result:
                        continue
                    existing = db.query(PickAnalysis).filter(
                        PickAnalysis.scan_pick_id == pick.id, PickAnalysis.kind == "advisory").first()
                    if existing:
                        db.delete(existing)
                        db.flush()
                    db.add(PickAnalysis(
                        scan_pick_id=pick.id, kind="advisory",
                        verdict_short=result.get("verdict_short"),
                        verdict_class=result.get("verdict_class"),
                        thesis=result.get("reason"),
                        detail_json={"action": result.get("action")},
                        model_used=result.get("model_used"), provider=result.get("provider"),
                        generated_at=_dt.now(timezone.utc),
                    ))
                    db.commit()
                    done += 1
            log.info("holding advisory: %d held picks advised", done)
        finally:
            db.close()
    except Exception:
        log.exception("job_holding_advisory failed")


# ── Job: Weekend Lab nudge (Sat 09:00 IST) ────────────────────────────────────

async def job_weekend_lab_nudge() -> None:
    """
    Sat 09:00 IST: if latest basket has picks lacking deep analysis AND user has
    telegram linked AND pref weekend_lab_nudge != "0" → send nudge.
    """
    try:
        from database import SessionLocal
        from crud.prefs import get_pref
        from models import User, ScanRun, ScanPick, PickAnalysis

        db = SessionLocal()
        try:
            users = db.query(User).all()
            for u in users:
                nudge_pref = get_pref(db, u.id, "weekend_lab_nudge") or "1"
                if nudge_pref == "0":
                    continue

                run = (
                    db.query(ScanRun)
                    .filter(ScanRun.user_id == u.id)
                    .order_by(ScanRun.scanned_at.desc())
                    .first()
                )
                if not run:
                    continue

                picks = db.query(ScanPick).filter(ScanPick.scan_run_id == run.id).all()
                pick_ids = [p.id for p in picks]
                analyzed_ids = {
                    a.scan_pick_id
                    for a in db.query(PickAnalysis).filter(
                        PickAnalysis.scan_pick_id.in_(pick_ids),
                        PickAnalysis.kind == "deep",
                    ).all()
                } if pick_ids else set()

                pending = len(pick_ids) - len(analyzed_ids)
                if pending <= 0:
                    continue

                from services.telegram_service import send_telegram_sync
                send_telegram_sync(
                    u.id,
                    f"Weekend Lab ready — {pending} picks await deep analysis. Open Crest → Alpha Scanner → Weekend Lab."
                )
                log.info("weekend_lab_nudge sent to user %d (%d picks pending)", u.id, pending)
        finally:
            db.close()
    except Exception:
        log.exception("job_weekend_lab_nudge failed")


# ── Job: weekly KB v2 refresh (Sat 09:00 IST) ────────────────────────────────

async def job_refresh_kb() -> None:
    """
    Sat 09:00 IST: recompute self-maintained KB metrics:
      - industry_master: perf_1w/1m/3m, rank_1w/1m/3m, rrg_quadrant, rrg_history, kb_as_of
      - stock_master:    rs_rating (IBD-style percentile), pct_from_52wh, ret_1m, ret_3m
    Also re-runs ingest_nse_indices for fresh membership data.
    """
    try:
        await asyncio.to_thread(_sync_refresh_kb)
    except Exception:
        log.exception("job_refresh_kb failed")


def _sync_refresh_kb() -> None:
    """Synchronous KB refresh — runs inside a threadpool worker."""
    from shared.net_guard import has_internet
    if not has_internet():
        log.warning("refresh_kb: offline — skipped")
        return

    log.info("KB v2 refresh started")

    # 1. Re-ingest NSE index memberships (network-guarded above)
    try:
        from scripts.kb.ingest_nse_indices import main as ingest_nse
        ingest_nse()
        log.info("refresh_kb: NSE memberships refreshed")
    except Exception:
        log.exception("refresh_kb: ingest_nse_indices failed (non-fatal)")

    # 2. Rebuild industry perf/rank/RRG from bhavcopy_daily
    from database import SessionLocal
    from models import IndustryMaster, IndexMembership, StockMaster
    from shared.mcw_index import compute_mcw_index
    from shared.rrg import compute_rrg_point, compute_rrg_trail
    from shared.tickers import nse
    from shared.yfinance_client import get_bulk_daily
    from scripts.kb.common import now_utc
    import pandas as pd

    db = SessionLocal()
    try:
        industries = db.query(IndustryMaster).filter(
            IndustryMaster.kind.in_(["basic_industry", "sector"])
        ).all()

        if not industries:
            log.warning("refresh_kb: no industries in DB")
            return

        # Compute MCW index series for all industries + benchmark
        log.info("refresh_kb: computing MCW series for %d industries", len(industries))

        # Benchmark: N500 or N50 close series
        bench_close: pd.Series | None = None
        try:
            import yfinance as yf
            for tk in ("^CRSLDX", "^NSEI"):
                df = yf.download(tk, period="1y", interval="1d",
                                 auto_adjust=True, progress=False, timeout=20)
                if df is not None and not df.empty:
                    if isinstance(df.columns, pd.MultiIndex):
                        df.columns = [c[0] for c in df.columns]
                    c = df["Close"].dropna()
                    if len(c) >= 100:
                        bench_close = c
                        break
        except Exception as e:
            log.warning("refresh_kb: benchmark fetch failed: %s", e)

        # For perf ranking we need index series per industry
        industry_series: dict[str, pd.Series] = {}
        for row in industries:
            try:
                # Use existing MCW compute (force fresh, no cache)
                sig = compute_mcw_index(row.name, row.kind, db, use_cache=False)
                if sig is None:
                    continue
                # We need the actual index series for RRG — fetch constituents manually
                from shared.mcw_index import _constituents, _weights
                from shared import data_quality as dq
                syms = _constituents(db, row.name, row.kind)
                if not syms:
                    continue
                weights = _weights(db, syms)
                bulk = get_bulk_daily([nse(s) for s in syms], period="1y")
                closes = {}
                valid_w = {}
                for s in syms:
                    df_s = bulk.get(nse(s))
                    ok, _ = dq.check_series(df_s, min_rows=60)
                    if not ok:
                        continue
                    closes[s] = df_s["Close"].dropna()
                    valid_w[s] = weights.get(s, 1.0)
                if len(closes) < 2:
                    continue
                frame = pd.DataFrame(closes).sort_index().ffill().dropna()
                if len(frame) < 63:
                    continue
                rebased = frame / frame.iloc[0] * 100.0
                wvec = pd.Series({c2: valid_w[c2] for c2 in frame.columns})
                wvec = wvec / wvec.sum()
                idx_series = (rebased * wvec).sum(axis=1)
                industry_series[row.name] = idx_series
            except Exception as e:
                log.warning("refresh_kb: MCW series for %s failed: %s", row.name, e)
                continue

        # Compute perf for each industry
        def _perf(series: pd.Series, days: int) -> float | None:
            s = series.dropna()
            if len(s) < days:
                return None
            return round(float((s.iloc[-1] - s.iloc[-days]) / s.iloc[-days] * 100), 2)

        perf_data: dict[str, dict] = {}
        for name, series in industry_series.items():
            perf_data[name] = {
                "perf_1w": _perf(series, 5),
                "perf_1m": _perf(series, 21),
                "perf_3m": _perf(series, 63),
            }

        # Rank across all industries
        def _rank(key: str) -> dict[str, int]:
            scored = [(n, d[key]) for n, d in perf_data.items() if d.get(key) is not None]
            scored.sort(key=lambda x: x[1], reverse=True)
            return {n: i + 1 for i, (n, _) in enumerate(scored)}

        rank_1w = _rank("perf_1w")
        rank_1m = _rank("perf_1m")
        rank_3m = _rank("perf_3m")

        now = now_utc()
        for row in industries:
            if row.name not in perf_data:
                continue
            p = perf_data[row.name]
            row.perf_1w = p["perf_1w"]
            row.perf_1m = p["perf_1m"]
            row.perf_3m = p["perf_3m"]
            if row.name in rank_1w:
                row.rank_1w = rank_1w[row.name]
            if row.name in rank_1m:
                row.rank_1m = rank_1m[row.name]
            if row.name in rank_3m:
                row.rank_3m = rank_3m[row.name]
            row.kb_as_of = now

            # RRG
            if bench_close is not None and row.name in industry_series:
                try:
                    pt = compute_rrg_point(industry_series[row.name], bench_close)
                    if pt:
                        row.rrg_quadrant = pt["quadrant"]
                        trail = compute_rrg_trail(industry_series[row.name], bench_close)
                        row.rrg_history = trail
                except Exception as e:
                    log.debug("refresh_kb: RRG for %s failed: %s", row.name, e)

        db.commit()
        log.info("refresh_kb: %d industries updated (perf/rank/RRG)", len(industry_series))

        # 3. RS Rating for all stocks in stock_master (IBD-style percentile)
        # weighted: 3m×50% + 6m×30% + 12m×20% vs full stock_master universe
        log.info("refresh_kb: computing RS ratings for all stocks")
        stock_rows = db.query(StockMaster.sym).all()
        all_syms = [r[0] for r in stock_rows]
        if not all_syms:
            log.warning("refresh_kb: no stocks in stock_master")
            return

        # Download in chunks of 50 per yfinance rate-limit discipline
        import time
        chunk_size = 50
        all_closes: dict[str, pd.Series] = {}
        for i in range(0, len(all_syms), chunk_size):
            chunk = all_syms[i: i + chunk_size]
            try:
                bulk = get_bulk_daily([nse(s) for s in chunk], period="1y")
                for s in chunk:
                    df_s = bulk.get(nse(s))
                    if df_s is not None and not df_s.empty and "Close" in df_s.columns:
                        c = df_s["Close"].dropna()
                        if len(c) >= 63:
                            all_closes[s] = c
            except Exception as e:
                log.warning("refresh_kb: chunk %d-%d failed: %s", i, i + chunk_size, e)
            time.sleep(1)

        def _ret(close: pd.Series, days: int) -> float:
            c = close.dropna()
            if len(c) < days:
                return 0.0
            a, b = float(c.iloc[-days]), float(c.iloc[-1])
            return (b - a) / a * 100.0 if a else 0.0

        raw_scores: dict[str, float] = {
            s: 0.5 * _ret(c, 63) + 0.3 * _ret(c, 126) + 0.2 * _ret(c, 252)
            for s, c in all_closes.items()
        }
        if raw_scores:
            series = pd.Series(raw_scores)
            pct_ranks = (series.rank(pct=True) * 100).round(1)
            for s, rating in pct_ranks.items():
                row = db.query(StockMaster).filter(StockMaster.sym == s).first()
                if row:
                    row.rs_rating = float(rating)
            db.commit()
            log.info("refresh_kb: RS ratings updated for %d stocks", len(pct_ranks))

        # 4. Quarterly revenue + next earnings date for tracked symbols only
        try:
            from services.earnings_setup import get_tracked_syms
            tracked = get_tracked_syms(db)
            log.info("refresh_kb: fetching quarterly revenue for %d tracked symbols", len(tracked))
            import yfinance as yf
            rev_updated = 0
            for sym in tracked:
                try:
                    ticker = yf.Ticker(f"{sym}.NS")
                    stmt = ticker.quarterly_income_stmt
                    if stmt is not None and not stmt.empty:
                        rev_row = stmt.loc[[c for c in stmt.index if "Total Revenue" in str(c) or "Revenue" in str(c)], :].head(1)
                        if not rev_row.empty:
                            latest_col = rev_row.columns[0]
                            rev_val = float(rev_row.iloc[0, 0])
                            rev_cr = round(rev_val / 1e7, 4)  # rupees → crore
                            q_date = str(latest_col)[:10]
                            sm_row = db.query(StockMaster).filter(StockMaster.sym == sym).first()
                            if sm_row:
                                sm_row.last_q_revenue_cr = rev_cr
                                sm_row.last_q_date = q_date
                                rev_updated += 1
                    # next earnings date
                    from shared.earnings_calendar import get_next_earnings
                    ned = get_next_earnings(sym, db)
                    if ned:
                        sm_row2 = db.query(StockMaster).filter(StockMaster.sym == sym).first()
                        if sm_row2:
                            sm_row2.next_earnings_date = ned.isoformat()
                    time.sleep(0.5)
                except Exception as e:
                    log.debug("refresh_kb: quarterly rev %s: %s", sym, e)
            db.commit()
            log.info("refresh_kb: quarterly revenue updated for %d symbols", rev_updated)
        except Exception:
            log.exception("refresh_kb: quarterly revenue refresh failed (non-fatal)")

    except Exception:
        db.rollback()
        log.exception("refresh_kb: DB update failed")
    finally:
        db.close()


# ── Job: poll NSE order announcements (10:30 + 17:30 IST) ────────────────────

async def job_poll_order_announcements() -> None:
    try:
        await asyncio.to_thread(_sync_poll_order_announcements)
    except Exception:
        log.exception("job_poll_order_announcements failed")


def _sync_poll_order_announcements() -> None:
    from shared.net_guard import has_internet
    if not has_internet():
        log.warning("poll_order_ann: offline — skipped")
        return

    from database import SessionLocal
    from models import OrderAnnouncement, StockMaster, User
    from shared.cache import cache_get, cache_set
    from shared.nse_announcements import fetch_announcements, parse_order_wins
    from services.earnings_setup import get_tracked_syms, invalidate_setup_cache
    from services.alert_service import dispatch_alert, telegram_enabled

    db = SessionLocal()
    try:
        syms = get_tracked_syms(db)
        if not syms:
            log.info("poll_order_ann: no tracked symbols")
            return

        today = date.today()
        # Fetch since the start of the current quarter to catch new wins
        from services.earnings_setup import _current_quarter_start
        q_start = _current_quarter_start(today)

        log.info("poll_order_ann: polling %d symbols from %s", len(syms), q_start)
        new_total = 0
        large_orders: list[dict] = []

        for sym in syms:
            try:
                raw = fetch_announcements(sym, from_date=q_start, to_date=today)
                wins = parse_order_wins(raw)
                if not wins:
                    continue
                for w in wins:
                    # upsert — skip if exists
                    exists = db.query(OrderAnnouncement).filter(
                        OrderAnnouncement.sym == sym,
                        OrderAnnouncement.ann_date == w["ann_date"],
                        OrderAnnouncement.headline == w["headline"],
                    ).first()
                    if exists:
                        continue

                    # LLM fallback if regex found nothing but keywords present
                    if w["value_cr"] is None and w["body_excerpt"]:
                        try:
                            llm_val = _llm_extract_value(w["body_excerpt"])
                            if llm_val is not None:
                                w["value_cr"] = llm_val
                                w["extraction"] = "llm"
                        except Exception as e:
                            log.debug("order_ann LLM extract %s: %s", sym, e)

                    row = OrderAnnouncement(
                        sym=sym,
                        ann_date=w["ann_date"],
                        headline=w["headline"],
                        body_excerpt=w["body_excerpt"],
                        value_cr=w["value_cr"],
                        extraction=w["extraction"],
                        source_url=w["source_url"],
                    )
                    db.add(row)
                    new_total += 1

                    # Flag large orders for alerting
                    if w["value_cr"]:
                        sm = db.query(StockMaster).filter(StockMaster.sym == sym).first()
                        prev_rev = float(sm.last_q_revenue_cr) if sm and sm.last_q_revenue_cr else None
                        is_large = (
                            (prev_rev and w["value_cr"] >= 0.20 * prev_rev)
                            or w["value_cr"] >= 100
                        )
                        if is_large:
                            pct_str = f" = {round(w['value_cr'] / prev_rev * 100)}% of last Q rev" if prev_rev else ""
                            large_orders.append({"sym": sym, "value_cr": w["value_cr"], "pct_str": pct_str})

                db.commit()
                invalidate_setup_cache(sym)
            except Exception as e:
                log.warning("poll_order_ann: %s failed: %s", sym, e)
                db.rollback()
                continue

        log.info("poll_order_ann: %d new announcements; %d large orders", new_total, len(large_orders))

        # Dispatch large-order alerts
        if large_orders:
            users = db.query(User).all()
            for u in users:
                if not telegram_enabled(db, u.id):
                    continue
                for order in large_orders:
                    msg = (
                        f"\U0001f7e2 <b>Large order: {order['sym']}</b> ₹{order['value_cr']:.1f} cr"
                        f"{order['pct_str']}"
                    )
                    dispatch_alert(
                        db, u.id,
                        title=f"Large order: {order['sym']}",
                        telegram_text=msg,
                        notif_type="large_order",
                        related_sym=order["sym"],
                        notif_body=f"₹{order['value_cr']:.1f} cr{order['pct_str']}",
                    )
    finally:
        db.close()


_llm_order_call_count = 0
_LLM_MAX_DAILY = 20


def _llm_extract_value(text: str) -> float | None:
    """LLM fallback for value extraction. Hard-capped at 20 calls/day."""
    global _llm_order_call_count
    if _llm_order_call_count >= _LLM_MAX_DAILY:
        return None
    _llm_order_call_count += 1

    import asyncio
    from services.llm.router import chat, NoFreeCapacity

    messages = [
        {"role": "system", "content": "Extract the order value in crore rupees from the announcement text. Reply with JSON only: {\"value_cr\": <number or null>}. null if no monetary value found."},
        {"role": "user", "content": text[:600]},
    ]
    try:
        import json as _json
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(
            chat(messages, task="order_extract", tier="system", max_tokens=50, json_mode=True)
        )
        loop.close()
        text = result.get("text", "")
        parsed = _json.loads(text)
        val = parsed.get("value_cr")
        if val is not None:
            return float(val)
    except NoFreeCapacity:
        pass
    except Exception as e:
        log.debug("_llm_extract_value: %s", e)
    return None


# ── Job: pre-earnings digest (08:30 IST daily) ───────────────────────────────

async def job_pre_earnings_digest() -> None:
    try:
        await asyncio.to_thread(_sync_pre_earnings_digest)
    except Exception:
        log.exception("job_pre_earnings_digest failed")


def _sync_pre_earnings_digest() -> None:
    from database import SessionLocal
    from models import StockMaster, User
    from services.alert_service import telegram_enabled
    from services.telegram_service import send_telegram_sync
    from services.earnings_setup import get_tracked_syms, get_or_compute_setup, _current_quarter_start
    from shared.earnings_calendar import sessions_until_earnings

    db = SessionLocal()
    try:
        syms = get_tracked_syms(db)
        if not syms:
            return

        today = date.today()
        near_earnings: list[dict] = []

        for sym in syms:
            sm = db.query(StockMaster).filter(StockMaster.sym == sym).first()
            if not sm or not sm.next_earnings_date:
                continue
            try:
                from datetime import date as date_cls
                ned = date_cls.fromisoformat(sm.next_earnings_date)
                sessions = sessions_until_earnings(ned)
                if sessions is None or sessions > 3:
                    continue
                setup = get_or_compute_setup(db, sym)
                near_earnings.append({
                    "sym": sym,
                    "earnings_date": sm.next_earnings_date,
                    "sessions": sessions,
                    "qtd_orders_cr": setup["qtd_orders_cr"],
                    "vs_prev_q": setup["vs_prev_q"],
                    "vs_guidance": setup["vs_guidance"],
                    "score": setup["score"],
                })
            except Exception as e:
                log.debug("pre_earnings_digest %s: %s", sym, e)
                continue

        if not near_earnings:
            return

        lines = ["<b>Pre-Earnings Digest</b>"]
        for e in near_earnings:
            vs_pq = f"{e['vs_prev_q']:.1%}" if e["vs_prev_q"] is not None else "—"
            vs_g  = f"{e['vs_guidance']:.1%}" if e["vs_guidance"] is not None else "—"
            badge = {"strong": "\U0001f7e2", "building": "\U0001f7e1", "neutral": "⚪", "unknown": "⚪"}.get(e["score"], "⚪")
            lines.append(
                f"{badge} <b>{e['sym']}</b> — earnings {e['earnings_date']} ({e['sessions']}s away)\n"
                f"  QTD orders ₹{e['qtd_orders_cr']:.1f} cr | vs prev Q: {vs_pq} | vs guidance: {vs_g} | setup: <b>{e['score']}</b>"
            )

        msg = "\n\n".join(lines)
        users = db.query(User).all()
        for u in users:
            if telegram_enabled(db, u.id):
                send_telegram_sync(u.id, msg)
        log.info("pre_earnings_digest sent for %d symbols", len(near_earnings))
    finally:
        db.close()

    log.info("KB v2 refresh complete")


# ── Backup job (re-exported from backup_service) ──────────────────────────────

def job_backup_data() -> None:
    from services.backup_service import job_backup_data as _run
    _run()
