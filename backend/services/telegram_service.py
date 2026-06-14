"""
Telegram bot service — direct Bot API via httpx (no python-telegram-bot dep).
Gracefully no-ops when TELEGRAM_BOT_TOKEN is absent or user has no chat_id.

Long-polling getUpdates runs in the APScheduler (no webhook / ngrok needed).
"""
from __future__ import annotations

import asyncio
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone

import httpx

log = logging.getLogger(__name__)

_POLL_OFFSET: dict[str, int] = {"value": 0}  # mutable singleton for update_id tracking


def _token() -> str | None:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip() or None


def _api(path: str) -> str:
    tok = _token()
    return f"https://api.telegram.org/bot{tok}/{path}"


# ── Send helpers ───────────────────────────────────────────────────────────────

async def send_telegram(user_id: int, text: str, image_path: str | None = None) -> bool:
    """
    Send a Telegram message to the user's linked chat.
    Returns True on success; False if unconfigured or error (never raises).
    """
    tok = _token()
    if not tok:
        log.debug("send_telegram: TELEGRAM_BOT_TOKEN not set — skip")
        return False

    chat_id = _get_chat_id(user_id)
    if not chat_id:
        log.debug("send_telegram: user %d has no telegram_chat_id — skip", user_id)
        return False

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            if image_path:
                with open(image_path, "rb") as f:
                    r = await client.post(
                        _api("sendPhoto"),
                        data={"chat_id": chat_id, "caption": text, "parse_mode": "HTML"},
                        files={"photo": f},
                    )
            else:
                r = await client.post(
                    _api("sendMessage"),
                    json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                )
        if r.status_code == 200:
            return True
        log.warning("send_telegram: status %d body %s", r.status_code, r.text[:200])
        return False
    except Exception as e:
        log.error("send_telegram error: %s", e)
        return False


def send_telegram_sync(user_id: int, text: str, image_path: str | None = None) -> bool:
    """Sync wrapper for use inside APScheduler sync jobs (run in worker threads
    with no event loop). Schedules onto a running loop if present, else runs a
    fresh loop via asyncio.run."""
    try:
        running = asyncio.get_running_loop()
    except RuntimeError:
        running = None

    if running is not None:
        asyncio.ensure_future(send_telegram(user_id, text, image_path))
        return True
    try:
        return asyncio.run(send_telegram(user_id, text, image_path))
    except Exception as e:
        log.error("send_telegram_sync error: %s", e)
        return False


def _get_chat_id(user_id: int) -> str | None:
    from database import SessionLocal
    from crud.prefs import get_pref
    db = SessionLocal()
    try:
        return get_pref(db, user_id, "telegram_chat_id")
    finally:
        db.close()


# ── Link-code generation ───────────────────────────────────────────────────────

def generate_link_code(user_id: int) -> str:
    """
    Generate a 6-char link code and persist it in UserPreference.
    Expires after 10 minutes (checked on receipt).
    """
    from database import SessionLocal
    from crud.prefs import set_pref

    code = secrets.token_hex(3).upper()  # 6 hex chars
    expiry = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()

    db = SessionLocal()
    try:
        set_pref(db, user_id, "telegram_link_code", code)
        set_pref(db, user_id, "telegram_link_code_expiry", expiry)
    finally:
        db.close()

    return code


def get_bot_username() -> str | None:
    """Return bot username from getMe — cached at module level after first call."""
    tok = _token()
    if not tok:
        return None
    try:
        r = httpx.get(_api("getMe"), timeout=10)
        if r.status_code == 200:
            data = r.json()
            return data.get("result", {}).get("username")
    except Exception as e:
        log.debug("get_bot_username failed: %s", e)
    return None


# ── Short-poll handler (called by APScheduler every 5s) ──────────────────────

def poll_telegram_updates() -> None:
    """
    Non-blocking short-poll (getUpdates timeout=0) for bot updates. Handles
    /start <code>, /unlink, /status. Returns immediately — safe to run every 5s
    without overlapping the prior tick. Safe to call from a sync APScheduler job.
    """
    tok = _token()
    if not tok:
        return

    try:
        r = httpx.get(
            _api("getUpdates"),
            params={"offset": _POLL_OFFSET["value"], "timeout": 0, "allowed_updates": ["message"]},
            timeout=4,
        )
        if r.status_code != 200:
            return
        data = r.json()
    except Exception as e:
        log.debug("poll_telegram_updates error: %s", e)
        return

    for update in data.get("result", []):
        _POLL_OFFSET["value"] = update["update_id"] + 1
        msg = update.get("message", {})
        text = msg.get("text", "").strip()
        chat_id = str(msg.get("chat", {}).get("id", ""))
        if not chat_id:
            continue

        if text.startswith("/start"):
            parts = text.split(None, 1)
            code = parts[1].strip() if len(parts) > 1 else ""
            _handle_link(chat_id, code)

        elif text == "/unlink":
            _handle_unlink(chat_id)

        elif text == "/status":
            _handle_status(chat_id)


def _handle_link(chat_id: str, code: str) -> None:
    from database import SessionLocal
    from crud.prefs import get_pref, set_pref
    from models import User

    db = SessionLocal()
    try:
        users = db.query(User).all()
        matched_user = None
        for u in users:
            stored = get_pref(db, u.id, "telegram_link_code")
            expiry = get_pref(db, u.id, "telegram_link_code_expiry")
            if stored and stored == code:
                if expiry:
                    exp_dt = datetime.fromisoformat(expiry)
                    if datetime.now(timezone.utc) > exp_dt:
                        _send_sync(chat_id, "Link code expired. Please generate a new one in Settings.")
                        return
                matched_user = u
                break

        if not matched_user:
            _send_sync(chat_id, "Invalid or expired link code. Generate a new one in Settings → Connections.")
            return

        set_pref(db, matched_user.id, "telegram_chat_id", chat_id)
        set_pref(db, matched_user.id, "telegram_link_code", "")
        _send_sync(chat_id, f"Linked! Crest alerts for <b>{matched_user.email}</b> will now arrive here.\n\nCommands: /status /unlink")
        log.info("telegram linked: user %d chat %s", matched_user.id, chat_id)
    finally:
        db.close()


def _handle_unlink(chat_id: str) -> None:
    from database import SessionLocal
    from crud.prefs import get_pref, set_pref
    from models import User

    db = SessionLocal()
    try:
        users = db.query(User).all()
        for u in users:
            stored = get_pref(db, u.id, "telegram_chat_id")
            if stored == chat_id:
                set_pref(db, u.id, "telegram_chat_id", "")
                _send_sync(chat_id, "Unlinked. You will no longer receive Crest alerts here.")
                log.info("telegram unlinked: user %d", u.id)
                return
        _send_sync(chat_id, "This chat was not linked to any Crest account.")
    finally:
        db.close()


def _handle_status(chat_id: str) -> None:
    from database import SessionLocal
    from crud.prefs import get_pref
    from models import User

    db = SessionLocal()
    try:
        users = db.query(User).all()
        for u in users:
            stored = get_pref(db, u.id, "telegram_chat_id")
            if stored == chat_id:
                _send_sync(chat_id, f"Linked to <b>{u.email}</b>. Crest alerts are active.")
                return
        _send_sync(chat_id, "This chat is not linked to a Crest account. Use /start &lt;code&gt; to link.")
    finally:
        db.close()


def _send_sync(chat_id: str, text: str) -> None:
    tok = _token()
    if not tok:
        return
    try:
        httpx.post(_api("sendMessage"), json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}, timeout=10)
    except Exception as e:
        log.warning("send_message_sync failed for chat_id=%s: %s", chat_id, e)
