"""
Module 3 — Swing Detector / Alpha Scanner API routes.
Scan results are persisted to DB (scan_runs + scan_picks).
JSON files kept as safety backup during scan runs.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, Request, Query
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from deps import get_current_user_id
from crud.scan import save_scan_run, get_latest_scan, list_scan_history, get_scan_run, save_scan_outcome, get_all_trades, update_pick_result
from crud.swings import get_swing_trades, get_swing_budget

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/swing", tags=["swing_detector"])

_IST = timezone(timedelta(hours=5, minutes=30))
_scan_running = False


def _is_weekend_window() -> bool:
    now = datetime.now(_IST)
    day = now.weekday()
    t   = now.hour * 60 + now.minute
    if day in (5, 6):          return True
    if day == 4 and t >= 960:  return True
    if day == 0 and t < 540:   return True
    return False


def _is_market_hours() -> bool:
    now = datetime.now(_IST)
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return 555 <= t <= 930   # 09:15–15:30 IST


@router.get("/last-picks")
async def last_picks(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request, db)
    result = get_latest_scan(db, user_id)
    if not result:
        return {"status": "no_scan_yet", "picks": [], "market_summary": {}}
    return result


@router.post("/run-dry")
async def run_dry(request: Request, db: Session = Depends(get_db)):
    raise HTTPException(
        status_code=403,
        detail="Manual scans are disabled. The scanner runs automatically every day at 9 PM IST.",
    )


@router.get("/scan-status")
async def scan_status():
    return {"running": _scan_running, "weekend_window": _is_weekend_window()}


# ── Scan Vault endpoints ───────────────────────────────────────────────────────

@router.get("/vault")
async def scan_vault(
    request: Request,
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """List past scan runs (Scan Vault grid). Paginated."""
    user_id = get_current_user_id(request, db)
    return {"weeks": list_scan_history(db, user_id, limit=limit, offset=offset)}


@router.get("/vault/{run_id}")
async def scan_vault_entry(run_id: int, request: Request, db: Session = Depends(get_db)):
    """Full picks for a specific scan run."""
    user_id = get_current_user_id(request, db)
    # NOTE: breach detection runs in the nightly job (services.breach_sweep.sweep_user_open_runs),
    # not here — a per-open yfinance sweep made folder-open block for seconds.
    result = get_scan_run(db, user_id, run_id)
    if not result:
        raise HTTPException(status_code=404, detail="Scan run not found")
    return result


@router.post("/vault/{pick_id}/outcome")
async def record_outcome(pick_id: int, request: Request, db: Session = Depends(get_db)):
    """Record trade outcome for a scan pick (powers Scan Vault outcome tracking)."""
    user_id = get_current_user_id(request, db)
    data = await request.json()
    result = save_scan_outcome(db, user_id, pick_id, data)
    if not result:
        raise HTTPException(status_code=404, detail="Pick not found")
    return result


@router.post("/vault/{pick_id}/scan-result")
async def record_scan_result(pick_id: int, request: Request, db: Session = Depends(get_db)):
    """Mark a pick as SL_HIT or TARGET_HIT regardless of whether the user traded it."""
    data = await request.json()
    result = data.get("result")
    if result not in ("SL_HIT", "TARGET_HIT"):
        raise HTTPException(status_code=422, detail="result must be SL_HIT or TARGET_HIT")
    ok = update_pick_result(db, pick_id, result)
    if not ok:
        raise HTTPException(status_code=404, detail="Pick not found")
    return {"ok": True}


@router.get("/trades")
async def trades(
    request: Request,
    status: str | None = Query(None, pattern="^(open|closed)$"),
    limit: int = Query(20, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
):
    """Paginated scanner trades. status=open|closed filters; omit for all."""
    user_id = get_current_user_id(request, db)
    # breach detection happens in the nightly sweep + picks/cmp, not on this request path.
    return get_all_trades(db, user_id, limit=limit, offset=offset, status=status)


def _compute_unrealised_pnl(db: Session, user_id: int, active_swings: list) -> float:
    """Compute total unrealised P&L for active swings from price_snapshots."""
    trades = [s for s in active_swings if s.get("avg") and s.get("qty")]
    if not trades:
        return 0.0
    from models import PriceSnapshot
    syms = {t["sym"] for t in trades}
    snaps = {
        r.sym: float(r.ltp)
        for r in db.query(PriceSnapshot).filter(PriceSnapshot.sym.in_(syms)).all()
        if r.ltp
    }
    total = 0.0
    for t in trades:
        ltp = snaps.get(t["sym"])
        if ltp:
            total += (ltp - float(t["avg"])) * float(t["qty"])
    return total


@router.get("/combined-summary")
async def combined_summary(request: Request, db: Session = Depends(get_db)):
    """Combined KPI across scanner picks + manual swings. Frontend reads this directly."""
    user_id = get_current_user_id(request, db)
    scan  = get_all_trades(db, user_id)
    swing = get_swing_trades(db, user_id)

    ss = scan["summary"]
    ws = swing["summary"]

    total_invested = (ss["total_invested"] or 0) + (ws["total_invested"] or 0)
    closed_pl      = (ss["closed_pl"] or 0)      + (ws["closed_pl"] or 0)

    scan_wins  = round((ss["win_rate"] or 0) / 100 * (ss["closed_count"] or 0))
    swing_wins = round((ws["win_rate"] or 0) / 100 * (ws["closed_count"] or 0))
    total_closed = (ss["closed_count"] or 0) + (ws["closed_count"] or 0)
    win_rate = round((scan_wins + swing_wins) / total_closed * 100) if total_closed else None
    win_rate_class = ("green" if (win_rate or 0) >= 60 else "gold-c" if (win_rate or 0) > 0 else "")

    unrealised_pnl = _compute_unrealised_pnl(db, user_id, swing.get("active", []))
    unrealised_pct = round(unrealised_pnl / total_invested * 100, 2) if total_invested else None

    _bt = get_swing_budget(db, user_id)
    budget = {
        "total":        _bt,
        "deployed":     round(total_invested, 2),
        "free":         round(_bt - total_invested, 2),
        "pct_deployed": round(total_invested / _bt * 100, 1) if _bt else 0,
        "over":         total_invested > _bt,
    }

    return {
        "budget":                    budget,
        "total_invested":            round(total_invested, 2),
        "closed_pl":                 round(closed_pl, 2),
        "win_rate":                  win_rate,
        "win_rate_class":            win_rate_class,
        "open_count":                (ss["open_count"] or 0) + (ws["open_count"] or 0),
        "closed_count":              total_closed,
        "unrealised_pnl":            round(unrealised_pnl, 2),
        "unrealised_pct_on_deployed": unrealised_pct,
    }


@router.get("/dashboard")
async def swing_dashboard(request: Request, db: Session = Depends(get_db)):
    """
    Single batched endpoint for Alpha Scanner (M3).
    Replaces 3 separate calls: /trades + /api/portfolio/swings + /combined-summary.
    """
    user_id = get_current_user_id(request, db)
    return _dashboard_payload(user_id, db)


@router.patch("/trades/{trade_id}/type")
async def set_trade_type(trade_id: int, request: Request, db: Session = Depends(get_db)):
    """Toggle a trade between scanner pick and manual (manual = excluded from scan win-rate)."""
    user_id = get_current_user_id(request, db)
    data = await request.json()
    new_type = data.get("trade_type")
    if new_type not in ("scanner", "manual"):
        return JSONResponse({"error": "trade_type must be 'scanner' or 'manual'"}, status_code=422)
    from models import SwingTrade
    trade = db.query(SwingTrade).filter(SwingTrade.id == trade_id, SwingTrade.user_id == user_id).first()
    if not trade:
        return JSONResponse({"error": "not_found"}, status_code=404)
    trade.trade_type = new_type
    trade.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "id": trade_id, "trade_type": new_type}


@router.post("/reconcile")
async def reconcile(request: Request, db: Session = Depends(get_db)):
    """Refresh button: pull live Kite holdings + positions + trades, then reconcile
    them onto My Trades (auto-create held scanner picks, refresh active, close sold)."""
    user_id = get_current_user_id(request, db)

    from modules.kite.routes import _get_sid, _persist
    from services.kite_mcp.client import call_tool

    sid = _get_sid(db, user_id)
    if not sid:
        return JSONResponse(
            {"error": "Kite not connected — connect in Settings → Connections first."},
            status_code=400,
        )

    fetched = {}
    for tool in ("get_holdings", "get_positions", "get_trades"):
        try:
            result = await call_tool(sid, tool)
            _persist(tool, result, user_id, db)
            fetched[tool] = "ok"
        except Exception as e:
            log.warning("reconcile fetch %s failed: %s", tool, e)
            fetched[tool] = f"error: {e}"

    # Only auto-close on a trustworthy snapshot — a failed holdings fetch must not
    # wipe active trades (would mass-false-close).
    allow_close = fetched.get("get_holdings") == "ok"

    from services.kite_reconcile import reconcile_trades
    changes = await asyncio.to_thread(reconcile_trades, user_id, db, allow_close)

    return {"fetched": fetched, "changes": changes, "dashboard": _dashboard_payload(user_id, db)}


def _dashboard_payload(user_id: int, db: Session) -> dict:
    scanner = get_all_trades(db, user_id)
    swings = get_swing_trades(db, user_id)
    ss, ws = scanner["summary"], swings["summary"]
    total_invested = (ss["total_invested"] or 0) + (ws["total_invested"] or 0)
    closed_pl = (ss["closed_pl"] or 0) + (ws["closed_pl"] or 0)
    scan_wins = round((ss["win_rate"] or 0) / 100 * (ss["closed_count"] or 0))
    swing_wins = round((ws["win_rate"] or 0) / 100 * (ws["closed_count"] or 0))
    total_closed = (ss["closed_count"] or 0) + (ws["closed_count"] or 0)
    win_rate = round((scan_wins + swing_wins) / total_closed * 100) if total_closed else None
    win_rate_class = ("green" if (win_rate or 0) >= 60 else "gold-c" if (win_rate or 0) > 0 else "")
    _bt = get_swing_budget(db, user_id)
    return {
        "scanner_trades": {"open": scanner["open"], "closed": scanner["closed"], "summary": ss},
        "manual_swings": {"active": swings["active"], "closed": swings["closed"], "budget": swings["budget"], "summary": ws},
        "budget": {
            "total": _bt, "deployed": round(total_invested, 2),
            "free": round(_bt - total_invested, 2),
            "pct_deployed": round(total_invested / _bt * 100, 1) if _bt else 0,
            "over": total_invested > _bt,
        },
        "combined": {
            "total_invested": round(total_invested, 2),
            "closed_pl": round(closed_pl, 2),
            "win_rate": win_rate,
            "win_rate_class": win_rate_class,
            "open_count": (ss["open_count"] or 0) + (ws["open_count"] or 0),
            "closed_count": total_closed,
        },
    }


@router.get("/picks/cmp")
async def picks_cmp(request: Request, db: Session = Depends(get_db)):
    """
    Fetch live CMP for all current picks, compute labels server-side, freeze breached picks in DB.
    Returns {prices, ohlc, states} — frontend renders states directly, no client-side calculations.
    """
    import math
    from datetime import date
    from sqlalchemy.orm import joinedload
    from models import ScanRun, ScanPick, ScanOutcome

    user_id = get_current_user_id(request, db)

    # Load latest scan run + all picks with their outcomes in one query
    run = (
        db.query(ScanRun)
        .filter(ScanRun.user_id == user_id)
        .order_by(ScanRun.scanned_at.desc())
        .first()
    )
    if not run:
        return {"prices": {}, "ohlc": {}, "states": {}}

    picks = (
        db.query(ScanPick)
        .filter(ScanPick.scan_run_id == run.id)
        .options(joinedload(ScanPick.outcomes))
        .all()
    )
    if not picks:
        return {"prices": {}, "ohlc": {}, "states": {}}

    # ── Batch CMP fetch — prefer price_snapshots, fall back to yfinance ──────────
    symbols    = [p.symbol for p in picks]
    ns_symbols = [s + ".NS" for s in symbols]
    sym_map    = {ns: orig for orig, ns in zip(symbols, ns_symbols)}

    def _safe(val):
        try:
            v = float(val)
            return round(v, 2) if math.isfinite(v) else None
        except Exception:
            return None

    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    from models import PriceSnapshot

    _IST = _tz(timedelta(hours=5, minutes=30))

    def _is_mkt() -> bool:
        now = _dt.now(_IST)
        t = now.hour * 60 + now.minute
        return now.weekday() < 5 and 555 <= t <= 930

    def _snapshots_fresh(syms: list[str]) -> tuple[bool, dict]:
        now_utc = _dt.now(_tz.utc)
        rows = db.query(PriceSnapshot).filter(PriceSnapshot.sym.in_(syms)).all()
        snap_map = {r.sym: r for r in rows}
        if len(snap_map) < len(syms):
            return False, snap_map
        market_hours = _is_mkt()
        if market_hours:
            for s in syms:
                r = snap_map[s]
                if r.fetched_at is None:
                    return False, snap_map
                fa = r.fetched_at if r.fetched_at.tzinfo else r.fetched_at.replace(tzinfo=_tz.utc)
                if (now_utc - fa).total_seconds() > 120:
                    return False, snap_map
        else:
            now_ist = now_utc.astimezone(_IST)
            last_close = now_ist.replace(hour=15, minute=30, second=0, microsecond=0)
            if now_ist < last_close:
                last_close -= _td(days=1)
            last_close_utc = last_close.astimezone(_tz.utc)
            for s in syms:
                r = snap_map[s]
                if r.fetched_at is None:
                    return False, snap_map
                fa = r.fetched_at if r.fetched_at.tzinfo else r.fetched_at.replace(tzinfo=_tz.utc)
                if fa < last_close_utc:
                    return False, snap_map
        return True, snap_map

    prices: dict[str, float] = {}
    ohlc:   dict[str, dict]  = {}

    fresh, snap_map = _snapshots_fresh(symbols)
    if fresh:
        for sym in symbols:
            r = snap_map[sym]
            ltp = _safe(r.ltp)
            if ltp is not None:
                prices[sym] = ltp
                ohlc[sym] = {"high": _safe(r.day_high), "low": _safe(r.day_low)}
    else:
        # Fall back to yfinance 5m intraday + write-back into price_snapshots
        def _download():
            import yfinance as yf
            return yf.download(ns_symbols, period="1d", interval="5m",
                               auto_adjust=True, progress=False, timeout=30, group_by="ticker")

        try:
            raw = await asyncio.to_thread(_download)
        except Exception as e:
            log.error("picks_cmp yfinance fallback failed: %s", e)
            return {"prices": {}, "ohlc": {}, "states": {}}

        now_utc = _dt.now(_tz.utc)

        if len(ns_symbols) == 1 and not raw.empty and hasattr(raw.columns, "levels"):
            raw.columns = [col[0] for col in raw.columns]

        if len(ns_symbols) == 1:
            ns = ns_symbols[0]
            orig = sym_map[ns]
            if not raw.empty:
                close_col = raw["Close"].dropna()
                price = _safe(close_col.iloc[-1]) if not close_col.empty else None
                if price is not None:
                    dh = _safe(raw["High"].dropna().iloc[-1]) if not raw["High"].dropna().empty else None
                    dl = _safe(raw["Low"].dropna().iloc[-1])  if not raw["Low"].dropna().empty  else None
                    prices[orig] = price
                    ohlc[orig] = {"high": dh, "low": dl}
        else:
            for ns in ns_symbols:
                orig = sym_map[ns]
                try:
                    sym_df = raw[ns]
                    price  = _safe(sym_df["Close"].dropna().iloc[-1])
                    if price is not None:
                        dh = _safe(sym_df["High"].dropna().iloc[-1])
                        dl = _safe(sym_df["Low"].dropna().iloc[-1])
                        prices[orig] = price
                        ohlc[orig] = {"high": dh, "low": dl}
                except (KeyError, IndexError):
                    pass

        # Write fetched prices back into price_snapshots for next caller
        for sym, ltp in prices.items():
            row = db.query(PriceSnapshot).filter(PriceSnapshot.sym == sym).first()
            if row is None:
                row = PriceSnapshot(sym=sym)
                db.add(row)
            row.ltp = ltp
            row.fetched_at = now_utc
            h = ohlc.get(sym, {})
            if h.get("high") is not None:
                row.day_high = h["high"]
            if h.get("low") is not None:
                row.day_low = h["low"]
        if prices:
            db.commit()

    # ── Kite LTP override — accurate source of truth when a session exists ───────
    # yfinance can be stale/split-adjusted (e.g. GVT&D showed 4900 vs Kite's real 4942).
    try:
        from crud.prefs import get_pref
        sid = get_pref(db, user_id, "kite_session_id")
        if sid:
            from services.kite_mcp.client import get_ltps
            kite_ltps = await get_ltps(sid, symbols)
            for s, p in kite_ltps.items():
                prices[s] = p
                # persist so portfolio / other surfaces get the accurate Kite price too
                row = db.query(PriceSnapshot).filter(PriceSnapshot.sym == s).first()
                if row is None:
                    row = PriceSnapshot(sym=s)
                    db.add(row)
                row.ltp = p
                row.fetched_at = _dt.now(_tz.utc)
            if kite_ltps:
                db.commit()
                log.debug("kite LTP override applied + persisted for %d symbols", len(kite_ltps))
    except Exception as e:
        log.debug("kite ltp override skipped: %s", e)

    # ── Compute label for each pick ────────────────────────────────────────────
    states: dict[str, dict] = {}
    db_dirty = False

    for pick in picks:
        sym   = pick.symbol
        cmp   = prices.get(sym)
        if cmp is None:
            continue

        h = ohlc.get(sym, {})
        day_high = h.get("high")
        day_low  = h.get("low")

        levels: dict = {}
        try:
            lv = pick.levels
            if isinstance(lv, dict):
                levels = lv
            elif isinstance(lv, str):
                import json as _json
                levels = _json.loads(lv)
        except (ValueError, TypeError):
            pass

        sl        = levels.get("sl")
        target    = levels.get("target")
        entry_lo  = levels.get("entry_lo")
        entry_hi  = levels.get("entry_hi")

        # Find open trade (user set position, not yet closed)
        open_outcome  = next((o for o in pick.outcomes if o.was_traded and not o.exit_price), None)
        closed_outcome = next((o for o in pick.outcomes if o.exit_price), None)

        def _fmt_inr(n):
            return f"₹{abs(int(n)):,}".replace(",", ",")

        def _closed_label(rp, entry, exit_p, qty):
            rp, entry, exit_p = float(rp), float(entry), float(exit_p)
            qty = float(qty) if qty is not None else None
            retStr = f" {'+' if rp >= 0 else ''}{rp:.1f}%"
            rs = round((exit_p - entry) * qty) if qty else None
            rsStr = f" · {'+' if rs >= 0 else ''}₹{abs(rs):,}" if rs is not None else ""
            cls = "target-hit" if rp >= 0 else "sl-hit"
            return f"CLOSED{retStr}{rsStr}", cls

        # ── Already frozen ─────────────────────────────────────────────────────
        if closed_outcome:
            rp = float(closed_outcome.return_pct or 0)
            label, cls = _closed_label(rp, closed_outcome.entry_price,
                                        closed_outcome.exit_price, closed_outcome.qty)
            states[sym] = {"cmp": cmp, "frozen": True, "newly_frozen": False,
                           "label": label, "label_class": cls}
            continue

        if pick.scan_result == "SL_HIT":
            states[sym] = {"cmp": cmp, "frozen": True, "newly_frozen": False,
                           "label": "SL HIT", "label_class": "sl-hit"}
            continue

        if pick.scan_result == "TARGET_HIT":
            states[sym] = {"cmp": cmp, "frozen": True, "newly_frozen": False,
                           "label": "TARGET HIT", "label_class": "target-hit"}
            continue

        if pick.scan_result == "CHURNED":
            states[sym] = {"cmp": cmp, "frozen": True, "newly_frozen": False,
                           "label": "CHURNED", "label_class": "churned"}
            continue

        # ── Check for new breach ───────────────────────────────────────────────
        sl_breached       = bool(sl     and cmp <= sl)
        tgt_breached      = bool(target and cmp >= target)
        sl_touched_intra  = bool(sl     and not sl_breached  and day_low  is not None and day_low  <= sl)
        tgt_touched_intra = bool(target and not tgt_breached and day_high is not None and day_high >= target)

        if sl_breached or tgt_breached:
            exit_p = sl if sl_breached else target
            if open_outcome and open_outcome.entry_price:
                ep = float(open_outcome.entry_price)
                rp = round((exit_p - ep) / ep * 100, 2)
                open_outcome.exit_price  = exit_p
                open_outcome.exit_date   = str(date.today())
                open_outcome.return_pct  = rp
                db_dirty = True
                label, cls = _closed_label(rp, ep, exit_p, open_outcome.qty)
            else:
                pick.scan_result = "SL_HIT" if sl_breached else "TARGET_HIT"
                db_dirty = True
                label = "SL HIT" if sl_breached else "TARGET HIT"
                cls   = "sl-hit" if sl_breached else "target-hit"
            states[sym] = {"cmp": cmp, "frozen": True, "newly_frozen": True,
                           "label": label, "label_class": cls}

        elif sl_touched_intra:
            states[sym] = {"cmp": cmp, "frozen": False, "newly_frozen": False,
                           "label": f"⚠ SL TOUCHED ₹{day_low:,.2f}", "label_class": "sl-touched"}

        elif tgt_touched_intra:
            if open_outcome and open_outcome.entry_price:
                ep = float(open_outcome.entry_price)
                gain = (day_high - ep) / ep * 100
                lbl = f"TARGET TOUCHED +{gain:.1f}%"
            elif entry_hi and entry_lo:
                lbl = f"TARGET TOUCHED +{(day_high-entry_hi)/entry_hi*100:.1f}% to +{(day_high-entry_lo)/entry_lo*100:.1f}%"
            else:
                lbl = "TARGET TOUCHED"
            states[sym] = {"cmp": cmp, "frozen": False, "newly_frozen": False,
                           "label": lbl, "label_class": "target-touched"}

        else:
            label, cls = "", ""
            if entry_lo and entry_hi:
                if   cmp < entry_lo:                       label, cls = "BELOW",    "below"
                elif cmp <= entry_hi:                      label, cls = "IN RANGE", "in-range"
                else:                                      label, cls = "ABOVE",    "above"

            unrealised_pl  = None
            unrealised_pct = None
            if open_outcome and open_outcome.entry_price and open_outcome.qty:
                ep  = float(open_outcome.entry_price)
                qty = float(open_outcome.qty)
                unrealised_pl  = round((cmp - ep) * qty, 2)
                unrealised_pct = round((cmp - ep) / ep * 100, 2)

            states[sym] = {"cmp": cmp, "frozen": False, "newly_frozen": False,
                           "label": label, "label_class": cls,
                           "unrealised_pl": unrealised_pl, "unrealised_pct": unrealised_pct}

    if db_dirty:
        db.commit()

    return {"prices": prices, "ohlc": ohlc, "states": states}


# ── Step 6: hold-long-term toggle + promote pick ──────────────────────────────

@router.put("/trades/{swing_id}/hold-long-term")
async def set_hold_long_term(swing_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request, db)
    body = await request.json()
    value = bool(body.get("value", False))
    from crud.swings import set_hold_long_term as _set_lt
    trade = _set_lt(db, user_id, swing_id, value)
    if not trade:
        raise HTTPException(status_code=404, detail="Swing not found")
    return {"ok": True, "id": trade.id, "hold_long_term": trade.hold_long_term}


@router.post("/promote-to-trade")
async def promote_pick_to_trade(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request, db)
    body = await request.json()
    pick_id = int(body.get("pick_id", 0))
    if not pick_id:
        raise HTTPException(status_code=400, detail="pick_id required")
    from crud.swings import promote_pick_to_trade as _promote
    trade = _promote(db, user_id, pick_id)
    if not trade:
        raise HTTPException(status_code=404, detail="Pick not found")
    return {
        "ok": True,
        "trade_id": trade.id,
        "sym": trade.sym,
        "hold_long_term": trade.hold_long_term,
    }


# ── LLM Analysis endpoints (PIECE 4) — read precomputed rows ─────────────────

@router.get("/vault/{pick_id}/analysis")
async def pick_analysis(pick_id: int, request: Request, db: Session = Depends(get_db)):
    """Return PickAnalysis rows (validation + failure) for drawer. Common — no BYOK gate."""
    from models import PickAnalysis
    rows = db.query(PickAnalysis).filter(PickAnalysis.scan_pick_id == pick_id).all()
    if not rows:
        return JSONResponse(status_code=204, content=None)
    return [
        {
            "id": r.id,
            "kind": r.kind,
            "verdict_short": r.verdict_short,
            "verdict_class": r.verdict_class,
            "thesis": r.thesis,
            "risk_flags": r.risk_flags_json,
            "failure_reason": r.failure_reason,
            "model_used": r.model_used,
            "provider": r.provider,
            "generated_at": r.generated_at.isoformat() if r.generated_at else None,
        }
        for r in rows
    ]


@router.get("/vault/scan/{scan_run_id}/review")
async def scan_review(scan_run_id: int, request: Request, db: Session = Depends(get_db)):
    """Return ScanReview for a folder card. Common — no BYOK gate."""
    from models import ScanReview
    row = db.query(ScanReview).filter(ScanReview.scan_run_id == scan_run_id).first()
    if not row:
        return JSONResponse(status_code=204, content=None)
    return {
        "id": row.id,
        "scan_run_id": row.scan_run_id,
        "summary": row.summary,
        "strong_count": row.strong_count,
        "weak_count": row.weak_count,
        "themes": row.themes_json,
        "best_sym": row.best_sym,
        "worst_sym": row.worst_sym,
        "model_used": row.model_used,
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
    }


@router.get("/market-note")
async def market_note(request: Request, db: Session = Depends(get_db)):
    """Return latest MarketNoteDaily. Common — no BYOK gate."""
    from datetime import date, timedelta
    from models import MarketNoteDaily
    row = db.query(MarketNoteDaily).order_by(MarketNoteDaily.date.desc()).first()
    if not row:
        return JSONResponse(status_code=204, content=None)

    # last trading day = most recent weekday on/before today (holiday-agnostic, good enough)
    d = date.today()
    while d.weekday() >= 5:  # Sat/Sun → roll back to Fri
        d -= timedelta(days=1)
    last_trading = d.isoformat()
    stale = (row.date or "") < last_trading
    days_old = None
    try:
        days_old = (date.fromisoformat(last_trading) - date.fromisoformat(row.date)).days
    except Exception:
        pass

    return {
        "id": row.id,
        "date": row.date,
        "note": row.note,
        "context": row.context_json,
        "model_used": row.model_used,
        "generated_at": row.generated_at.isoformat() if row.generated_at else None,
        "stale": stale,
        "last_trading_day": last_trading,
        "days_old": days_old,
    }


# ── Legacy history endpoints (kept for backward compat) ───────────────────────

@router.get("/history")
async def scan_history_legacy(request: Request, db: Session = Depends(get_db)):
    """Alias of /vault — kept for backward compat."""
    user_id = get_current_user_id(request, db)
    return {"weeks": list_scan_history(db, user_id)}


@router.get("/history/{run_id}")
async def scan_history_entry_legacy(run_id: int, request: Request, db: Session = Depends(get_db)):
    """Load a specific run by DB id. Previously used week_key string."""
    user_id = get_current_user_id(request, db)
    result = get_scan_run(db, user_id, run_id)
    if not result:
        raise HTTPException(status_code=404, detail="Scan run not found")
    return result


# ── Scanner v2 surfaces (read-only; all scoring/ranking done backend-side) ──────

@router.get("/sector-ranking")
async def sector_ranking(
    request: Request,
    limit: int = Query(15, ge=1, le=120),
    db: Session = Depends(get_db),
):
    """Ranked sector/industry momentum from the KB (industry_master). DB read only —
    the live MCW + CSV blend was computed during the scan, not here."""
    get_current_user_id(request, db)
    from models import IndustryMaster
    rows = (
        db.query(IndustryMaster)
        .filter(IndustryMaster.sector_momentum_score.isnot(None))
        .order_by(IndustryMaster.sector_momentum_score.desc())
        .limit(limit)
        .all()
    )
    def _f(v):
        return float(v) if v is not None else None
    return {"sectors": [{
        "name": r.name,
        "kind": r.kind,
        "score": _f(r.sector_momentum_score),
        "rrg_quadrant": r.rrg_quadrant,
        "perf_1m": _f(r.perf_1m),
        "perf_3m": _f(r.perf_3m),
        "pct_from_52wh": _f(r.pct_from_52wh),
        "breadth_above_ema50": _f(r.breadth_above_ema50),
        "ema200_rising": r.ema200_rising,
        "num_stocks": r.num_stocks,
    } for r in rows]}


@router.get("/validation")
async def validation_stats(request: Request, db: Session = Depends(get_db)):
    """Latest forward-track (trusted) + indicative backtest reports from disk."""
    get_current_user_id(request, db)
    import json
    from pathlib import Path
    vdir = Path(__file__).parent.parent.parent / "data" / "validation"

    def _latest(prefix: str) -> dict | None:
        if not vdir.exists():
            return None
        files = sorted(vdir.glob(f"{prefix}_*.json"))
        if not files:
            return None
        try:
            return json.loads(files[-1].read_text())
        except Exception:
            return None

    fwd = _latest("forward_track")
    bt = _latest("backtest")
    attr = _latest("attribution")
    forward = None
    if fwd:
        forward = {  # drop the heavy per-pick items list; FE wants aggregates
            "generated_at": fwd.get("generated_at"),
            "picks_tracked": fwd.get("picks_tracked"),
            "horizons": fwd.get("horizons"),
            "overall": fwd.get("overall"),
            "by_score_bucket": fwd.get("by_score_bucket"),
            "by_sector": fwd.get("by_sector"),
            "by_pass": fwd.get("by_pass"),
            "attribution": attr.get("attribution") if attr else None,
        }
    backtest = None
    if bt:
        backtest = {
            "generated_at": bt.get("generated_at"),
            "INDICATIVE_ONLY": bt.get("INDICATIVE_ONLY"),
            "params": bt.get("params"),
            "overall": bt.get("overall"),
            "rebalances": bt.get("rebalances"),
        }
    return {"forward_track": forward, "backtest": backtest}
