"""
Email digest service — SMTP (Gmail app-password) + Jinja2 templates.
Gracefully no-ops when SMTP_USER / SMTP_PASS env vars are absent.
"""
from __future__ import annotations

import logging
import os
import smtplib
from datetime import date, datetime, timezone, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

log = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).parent.parent / "templates" / "email"
_jinja = Environment(loader=FileSystemLoader(str(_TEMPLATE_DIR)), autoescape=True)

_IST = timezone(timedelta(hours=5, minutes=30))

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 465


# ── SMTP sender ────────────────────────────────────────────────────────────────

def send_email(to: str, subject: str, html: str) -> bool:
    """Send HTML email. Returns True on success, False on any failure or missing creds."""
    smtp_user = os.environ.get("SMTP_USER", "").strip()
    smtp_pass = os.environ.get("SMTP_PASS", "").strip()

    if not smtp_user or not smtp_pass:
        log.info("send_email: SMTP_USER/SMTP_PASS not set — skipping send to %s", to)
        return False

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = smtp_user
    msg["To"]      = to
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT) as server:
            server.login(smtp_user, smtp_pass)
            server.sendmail(smtp_user, to, msg.as_string())
        log.info("email sent to %s: %s", to, subject)
        return True
    except Exception as e:
        log.error("send_email failed to %s: %s", to, e)
        return False


# ── Digest renderers ───────────────────────────────────────────────────────────

def _fmt_inr(val) -> str:
    if val is None:
        return "—"
    try:
        n = float(val)
        if abs(n) >= 1e7:
            return f"₹{n/1e7:.2f} Cr"
        if abs(n) >= 1e5:
            return f"₹{n/1e5:.2f} L"
        return f"₹{n:,.0f}"
    except Exception:
        return str(val)


def _fmt_pct(val) -> str:
    if val is None:
        return "—"
    try:
        return f"{float(val):+.2f}%"
    except Exception:
        return str(val)


def render_morning_digest(user_id: int) -> str:
    from database import SessionLocal
    from models import PortfolioSnapshot, SwingTrade, PriceAlert, ScanPick, ScanRun

    db = SessionLocal()
    try:
        snap = db.query(PortfolioSnapshot).filter(PortfolioSnapshot.user_id == user_id).first()

        total_wealth = _fmt_inr(snap.total_wealth if snap else None)
        total_pnl    = _fmt_inr(snap.total_pnl if snap else None)
        pnl_positive = snap and snap.total_pnl is not None and float(snap.total_pnl) >= 0
        cagr         = _fmt_pct(snap.cagr if snap else None)
        cagr_positive = snap and snap.cagr is not None and float(snap.cagr) >= 0

        open_swings = db.query(SwingTrade).filter(
            SwingTrade.user_id == user_id,
            SwingTrade.status == "active",
        ).order_by(SwingTrade.created_at.desc()).limit(10).all()

        pending_alerts = db.query(PriceAlert).filter(
            PriceAlert.user_id == user_id,
            PriceAlert.is_triggered == False,
        ).limit(10).all()

        open_picks = (
            db.query(ScanPick)
            .join(ScanRun, ScanPick.scan_run_id == ScanRun.id)
            .filter(ScanRun.user_id == user_id, ScanPick.scan_result.is_(None))
            .order_by(ScanPick.id.desc())
            .limit(5)
            .all()
        )

        tmpl = _jinja.get_template("morning_digest.html")
        return tmpl.render(
            date=datetime.now(_IST).strftime("%A, %d %b %Y"),
            total_wealth=total_wealth,
            total_pnl=total_pnl,
            pnl_positive=pnl_positive,
            cagr=cagr,
            cagr_positive=cagr_positive,
            open_swings=open_swings,
            open_swings_count=len(open_swings),
            pending_alerts=pending_alerts,
            pending_alerts_count=len(pending_alerts),
            top_scan_picks=open_picks,
            scan_picks_count=len(open_picks),
        )
    finally:
        db.close()


def render_eod_digest(user_id: int) -> str:
    from database import SessionLocal
    from models import PortfolioSnapshot, PriceAlert, ScanPick, ScanRun
    from datetime import timezone as tz

    db = SessionLocal()
    today_str = date.today().isoformat()
    try:
        snap = db.query(PortfolioSnapshot).filter(PortfolioSnapshot.user_id == user_id).first()

        total_wealth = _fmt_inr(snap.total_wealth if snap else None)
        total_pnl    = _fmt_inr(snap.total_pnl if snap else None)
        pnl_positive = snap and snap.total_pnl is not None and float(snap.total_pnl) >= 0

        today_start = datetime.fromisoformat(today_str).replace(tzinfo=tz.utc)
        triggered_alerts = db.query(PriceAlert).filter(
            PriceAlert.user_id == user_id,
            PriceAlert.is_triggered == True,
            PriceAlert.triggered_at >= today_start,
        ).all()

        today_picks = (
            db.query(ScanPick)
            .join(ScanRun, ScanPick.scan_run_id == ScanRun.id)
            .filter(
                ScanRun.user_id == user_id,
                ScanRun.created_at >= today_start,
            )
            .limit(10)
            .all()
        )

        pruned_picks = (
            db.query(ScanPick)
            .join(ScanRun, ScanPick.scan_run_id == ScanRun.id)
            .filter(
                ScanRun.user_id == user_id,
                ScanPick.scan_result.in_(["pruned_macro", "pruned_earnings", "pruned_news"]),
            )
            .order_by(ScanPick.id.desc())
            .limit(10)
            .all()
        )

        tmpl = _jinja.get_template("eod_digest.html")
        return tmpl.render(
            date=datetime.now(_IST).strftime("%A, %d %b %Y"),
            total_wealth=total_wealth,
            total_pnl=total_pnl,
            pnl_positive=pnl_positive,
            triggered_alerts=triggered_alerts,
            new_scan_picks=today_picks,
            pruned_picks=[{"sym": p.symbol, "reason": p.scan_result} for p in pruned_picks],
        )
    finally:
        db.close()


def render_eod_telegram(user_id: int) -> str:
    """Compact plain/HTML text EOD summary for Telegram (₹ as &#8377;)."""
    from database import SessionLocal
    from models import PortfolioSnapshot, PriceAlert, ScanPick, ScanRun
    from datetime import timezone as tz

    db = SessionLocal()
    today_str = date.today().isoformat()
    try:
        snap = db.query(PortfolioSnapshot).filter(PortfolioSnapshot.user_id == user_id).first()
        wealth = _fmt_inr(snap.total_wealth if snap else None).replace("₹", "&#8377;")
        pnl    = _fmt_inr(snap.total_pnl if snap else None).replace("₹", "&#8377;")
        sign   = "🟢" if (snap and snap.total_pnl is not None and float(snap.total_pnl) >= 0) else "🔴"

        today_start = datetime.fromisoformat(today_str).replace(tzinfo=tz.utc)
        triggered = db.query(PriceAlert).filter(
            PriceAlert.user_id == user_id,
            PriceAlert.is_triggered == True,
            PriceAlert.triggered_at >= today_start,
        ).count()
        new_picks = (
            db.query(ScanPick)
            .join(ScanRun, ScanPick.scan_run_id == ScanRun.id)
            .filter(ScanRun.user_id == user_id, ScanRun.created_at >= today_start)
            .count()
        )

        d = datetime.now(_IST).strftime("%a, %d %b %Y")
        return (
            f"<b>Crest EOD — {d}</b>\n"
            f"{sign} Wealth {wealth} · P&amp;L {pnl}\n"
            f"Alerts today: {triggered} · New picks: {new_picks}"
        )
    finally:
        db.close()
