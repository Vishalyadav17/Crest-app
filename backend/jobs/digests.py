"""
Digest jobs: morning digest, EOD digest, Telegram long-poll.
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)


# ── Job: send morning digest (07:30 IST) ─────────────────────────────────────

async def job_send_morning_digests() -> None:
    try:
        await asyncio.to_thread(_sync_send_morning_digests)
    except Exception:
        log.exception("job_send_morning_digests failed")


def _sync_send_morning_digests() -> None:
    from database import SessionLocal
    from models import User
    from crud.prefs import get_pref
    from services.email_service import render_morning_digest, send_email
    from services.alert_service import email_enabled

    db = SessionLocal()
    try:
        users = db.query(User).all()
        for u in users:
            if get_pref(db, u.id, "digest_morning_opt_in", "0") != "1":
                continue
            if not email_enabled(db, u.id):
                continue
            try:
                html = render_morning_digest(u.id)
                send_email(u.email, "Crest Morning Digest", html)
            except Exception:
                log.exception("morning digest failed for user %d", u.id)
    finally:
        db.close()


# ── Job: send EOD digest (16:30 IST) ─────────────────────────────────────────

async def job_send_eod_digests() -> None:
    try:
        await asyncio.to_thread(_sync_send_eod_digests)
    except Exception:
        log.exception("job_send_eod_digests failed")


def _sync_send_eod_digests() -> None:
    from database import SessionLocal
    from models import User
    from crud.prefs import get_pref
    from services.email_service import render_eod_digest, render_eod_telegram, send_email
    from services.alert_service import email_enabled, telegram_enabled
    from services.telegram_service import send_telegram_sync

    db = SessionLocal()
    try:
        users = db.query(User).all()
        for u in users:
            if get_pref(db, u.id, "digest_eod_opt_in", "0") != "1":
                continue
            try:
                if email_enabled(db, u.id):
                    html = render_eod_digest(u.id)
                    send_email(u.email, "Crest EOD Digest", html)
                if telegram_enabled(db, u.id):
                    send_telegram_sync(u.id, render_eod_telegram(u.id))
            except Exception:
                log.exception("eod digest failed for user %d", u.id)
    finally:
        db.close()


# ── Job: Telegram long-poll (every 5s) ───────────────────────────────────────

async def job_poll_telegram() -> None:
    try:
        await asyncio.to_thread(_sync_poll_telegram)
    except Exception:
        log.exception("job_poll_telegram failed")


def _sync_poll_telegram() -> None:
    from services.telegram_service import poll_telegram_updates
    poll_telegram_updates()
