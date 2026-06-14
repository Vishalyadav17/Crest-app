"""
Alert jobs: price alerts, price bands, swing exits, entry-band-active.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from jobs import _is_market_hours, _IST

log = logging.getLogger(__name__)


# ── Helper: batch-load LTP map ────────────────────────────────────────────────

def load_ltp_map(db, syms: set[str]) -> dict[str, float]:
    """Single query for all needed symbols; returns {sym: ltp}."""
    from models import PriceSnapshot
    rows = db.query(PriceSnapshot).filter(PriceSnapshot.sym.in_(syms)).all()
    return {r.sym: float(r.ltp) for r in rows if r.ltp is not None}


# ── Job: check price alerts (every 30s, market hours) ────────────────────────

async def job_check_price_alerts() -> None:
    if not _is_market_hours():
        return
    try:
        await asyncio.to_thread(_sync_check_price_alerts)
    except Exception:
        log.exception("job_check_price_alerts failed")


def _sync_check_price_alerts() -> None:
    from database import SessionLocal
    from models import PriceAlert, Notification
    from datetime import timezone as tz

    db = SessionLocal()
    try:
        alerts = db.query(PriceAlert).filter(PriceAlert.is_triggered == False).all()
        if not alerts:
            return

        ltp_map = load_ltp_map(db, {a.sym for a in alerts})

        triggered_pairs: list[tuple] = []  # (alert, ltp) captured before commit
        now = datetime.now(tz.utc)

        for alert in alerts:
            ltp = ltp_map.get(alert.sym)
            if ltp is None:
                continue
            target = float(alert.target_price) if alert.target_price is not None else None
            if target is None:
                continue

            condition_met = (
                (alert.condition == "above" and ltp >= target)
                or (alert.condition == "below" and ltp <= target)
            )
            if not condition_met:
                continue

            alert.is_triggered = True
            alert.triggered_at = now
            db.add(Notification(
                user_id=alert.user_id,
                type="price_alert",
                title=f"{alert.sym} {alert.condition} ₹{target:,.2f}",
                body=f"LTP ₹{ltp:,.2f} — {alert.note or ''}".strip(" —"),
                related_sym=alert.sym,
                created_at=now,
            ))
            triggered_pairs.append((alert, ltp))

        if triggered_pairs:
            db.commit()
            log.info("price alerts triggered: %d", len(triggered_pairs))
            from services.alert_service import telegram_enabled
            from services.telegram_service import send_telegram_sync
            for alert, ltp in triggered_pairs:
                if telegram_enabled(db, alert.user_id):
                    send_telegram_sync(
                        alert.user_id,
                        f"<b>Price Alert</b>: {alert.sym} {alert.condition} "
                        f"&#8377;{float(alert.target_price):,.2f}\nLTP &#8377;{ltp:,.2f}",
                    )
    finally:
        db.close()


# ── Helpers: price band zone classification ───────────────────────────────────

def _band_zone(b, ltp: float) -> str | None:
    """Priority: sl > target > ideal > acceptable."""
    def f(x):
        return float(x) if x is not None else None
    sl, target = f(b.sl), f(b.target)
    ilo, ihi = f(b.ideal_lo), f(b.ideal_hi)
    alo, ahi = f(b.accept_lo), f(b.accept_hi)
    if sl is not None and ltp <= sl:
        return "sl"
    if target is not None and ltp >= target:
        return "target"
    if ilo is not None and ihi is not None and ilo <= ltp <= ihi:
        return "ideal"
    if alo is not None and ahi is not None and alo <= ltp <= ahi:
        return "acceptable"
    return None


def _band_msg(b, ltp: float, zone: str) -> str:
    px = f"&#8377;{ltp:,.2f}"
    head = {
        "sl":         f"🔴 <b>SL hit</b>: {b.sym}",
        "target":     f"🎯 <b>Target hit</b>: {b.sym}",
        "ideal":      f"🟢 <b>Ideal entry zone</b>: {b.sym}",
        "acceptable": f"🟡 <b>Acceptable entry zone</b>: {b.sym}",
    }[zone]
    lines = [head, f"LTP {px}"]
    if zone in ("ideal", "acceptable") and b.ideal_lo is not None and b.ideal_hi is not None:
        lines.append(f"Ideal &#8377;{float(b.ideal_lo):,.0f}–{float(b.ideal_hi):,.0f}")
    if b.note:
        lines.append(f"<i>{b.note}</i>")
    return "\n".join(lines)


# ── Job: scan price bands (hourly, market hours) ─────────────────────────────

async def job_scan_price_bands() -> None:
    if not _is_market_hours():
        return
    try:
        await asyncio.to_thread(_sync_scan_price_bands)
    except Exception:
        log.exception("job_scan_price_bands failed")


def _sync_scan_price_bands() -> None:
    from database import SessionLocal
    from models import User
    from crud.price_bands import list_active
    from services.alert_service import dispatch_alert

    today = datetime.now(_IST).date().isoformat()
    db = SessionLocal()
    try:
        for u in db.query(User).all():
            bands = list_active(db, u.id)
            if not bands:
                continue
            ltp_map = load_ltp_map(db, {b.sym for b in bands})
            for b in bands:
                ltp = ltp_map.get(b.sym)
                if ltp is None:
                    continue
                zone = _band_zone(b, ltp)
                if zone is None:
                    if b.last_alert_zone is not None:
                        b.last_alert_zone = None  # left all zones — re-arm
                    continue
                if b.last_alert_zone == zone and b.last_alerted_date == today:
                    continue
                dispatch_alert(
                    db, u.id,
                    title=f"{b.sym} {zone} @ {ltp:,.2f}",
                    telegram_text=_band_msg(b, ltp, zone),
                    notif_type="price_band",
                    related_sym=b.sym,
                )
                b.last_alert_zone = zone
                b.last_alerted_date = today
            db.commit()
    finally:
        db.close()


# ── Job: check swing exits — SL + target (every 60s, market hours) ───────────

async def job_check_swing_exits() -> None:
    if not _is_market_hours():
        return
    try:
        await asyncio.to_thread(_sync_check_swing_exits)
    except Exception:
        log.exception("job_check_swing_exits failed")


def _sync_check_swing_exits() -> None:
    from database import SessionLocal
    from models import SwingTrade, ScanPick, ScanRun, Notification
    from services.alert_service import dispatch_alert

    today_ist = datetime.now(_IST).date().isoformat()
    db = SessionLocal()
    try:
        # ── SwingTrade SL/target ──────────────────────────────────────────────
        trades = db.query(SwingTrade).filter(SwingTrade.status == "active").all()
        trade_ltp_map = load_ltp_map(db, {t.sym for t in trades}) if trades else {}

        for t in trades:
            ltp = trade_ltp_map.get(t.sym)
            if ltp is None:
                continue
            sl = float(t.sl) if t.sl is not None else None
            target = float(t.target) if t.target is not None else None

            hit = None
            if sl is not None and ltp <= sl:
                hit = ("swing_sl", "🔴 <b>SL hit</b>", sl)
            elif target is not None and ltp >= target:
                hit = ("swing_target", "🎯 <b>Target hit</b>", target)
            if hit is None:
                continue

            ntype, head, level = hit
            already = db.query(Notification).filter(
                Notification.user_id == t.user_id,
                Notification.type == ntype,
                Notification.related_sym == t.sym,
            ).first()
            if already:
                continue

            dispatch_alert(
                db, t.user_id,
                title=f"{t.sym} {ntype.replace('swing_', '')} @ {level:,.2f}",
                telegram_text=f"{head}: {t.sym}\nLTP &#8377;{ltp:,.2f} · Level &#8377;{level:,.2f}",
                notif_type=ntype,
                related_sym=t.sym,
            )
            t.status = "sl_hit" if ntype == "swing_sl" else "target_hit"
            t.exit_price = ltp
            t.exit_date = today_ist
        db.commit()

        # ── ScanPick levels SL/target ─────────────────────────────────────────
        open_picks = (
            db.query(ScanPick, ScanRun.user_id)
            .join(ScanRun, ScanPick.scan_run_id == ScanRun.id)
            .filter(ScanPick.scan_result.is_(None), ScanPick.levels.isnot(None))
            .all()
        )
        pick_ltp_map = load_ltp_map(db, {p.symbol for p, _ in open_picks}) if open_picks else {}

        for pick, user_id in open_picks:
            lvl = pick.levels or {}
            sl_val = lvl.get("sl")
            tgt_val = lvl.get("target")
            if not sl_val and not tgt_val:
                continue
            ltp = pick_ltp_map.get(pick.symbol)
            if ltp is None:
                continue

            hit = None
            if sl_val is not None and ltp <= float(sl_val):
                hit = ("scan_sl", "🔴 <b>Scanner SL hit</b>", float(sl_val))
            elif tgt_val is not None and ltp >= float(tgt_val):
                hit = ("scan_target", "🎯 <b>Scanner target hit</b>", float(tgt_val))
            if hit is None:
                continue

            ntype, head, level = hit
            already = db.query(Notification).filter(
                Notification.user_id == user_id,
                Notification.type == ntype,
                Notification.related_sym == pick.symbol,
            ).first()
            if already:
                continue

            dispatch_alert(
                db, user_id,
                title=f"{pick.symbol} scanner {ntype.replace('scan_', '')} @ {level:,.2f}",
                telegram_text=f"{head}: {pick.symbol}\nLTP &#8377;{ltp:,.2f} · Level &#8377;{level:,.2f}",
                notif_type=ntype,
                related_sym=pick.symbol,
            )
            pick.scan_result = "SL_HIT" if ntype == "scan_sl" else "TARGET_HIT"
        db.commit()
    finally:
        db.close()


# ── Job: entry-band-active alerts (every 15 min, market hours) ────────────────

async def job_check_entry_active() -> None:
    if not _is_market_hours():
        return
    try:
        await asyncio.to_thread(_sync_check_entry_active)
    except Exception:
        log.exception("job_check_entry_active failed")


def _sync_check_entry_active() -> None:
    from database import SessionLocal
    from models import User, ScanRun, ScanPick, Notification
    from services.alert_service import dispatch_alert

    db = SessionLocal()
    try:
        for u in db.query(User).all():
            run = (db.query(ScanRun).filter(ScanRun.user_id == u.id)
                   .order_by(ScanRun.id.desc()).first())
            if not run:
                continue
            picks = (db.query(ScanPick)
                     .filter(ScanPick.scan_run_id == run.id,
                             ScanPick.scan_result.is_(None),
                             ScanPick.levels.isnot(None)).all())
            if not picks:
                continue

            ltp_map = load_ltp_map(db, {p.symbol for p in picks})

            for pick in picks:
                lvl = pick.levels or {}
                lo, hi = lvl.get("entry_lo"), lvl.get("entry_hi")
                if not lo or not hi:
                    continue
                ltp = ltp_map.get(pick.symbol)
                if ltp is None:
                    continue
                if not (float(lo) <= ltp <= float(hi)):
                    continue
                already = db.query(Notification).filter(
                    Notification.user_id == u.id,
                    Notification.type == "scan_entry_active",
                    Notification.related_sym == pick.symbol).first()
                if already:
                    continue
                ipo = " (IPO)" if pick.is_ipo_pick else ""
                dispatch_alert(
                    db, u.id,
                    title=f"{pick.symbol} in entry band ₹{float(lo):,.2f}–{float(hi):,.2f}",
                    telegram_text=(f"🟢 <b>Entry active</b>: {pick.symbol}{ipo}\n"
                                   f"LTP &#8377;{ltp:,.2f} in zone &#8377;{float(lo):,.2f}–{float(hi):,.2f}\n"
                                   f"SL &#8377;{float(lvl.get('sl', 0)):,.2f} · "
                                   f"Tgt &#8377;{float(lvl.get('target', 0)):,.2f} · 1:{lvl.get('rr', '–')}"),
                    notif_type="scan_entry_active",
                    related_sym=pick.symbol,
                )
    finally:
        db.close()
