"""
Alert dispatcher — single entry point for outbound alerts.
Routes to Telegram and/or Email based on per-user channel toggles, and always
records a Notification row. Channels no-op silently when disabled or unconfigured.

Toggles (UserPreference):
  alert_telegram_enabled  default "1"
  alert_email_enabled     default "1"
"""
from __future__ import annotations
import logging

from sqlalchemy.orm import Session

log = logging.getLogger(__name__)


def telegram_enabled(db: Session, user_id: int) -> bool:
    from crud.prefs import get_pref
    return get_pref(db, user_id, "alert_telegram_enabled", "1") == "1"


def email_enabled(db: Session, user_id: int) -> bool:
    from crud.prefs import get_pref
    return get_pref(db, user_id, "alert_email_enabled", "1") == "1"


def dispatch_alert(
    db: Session,
    user_id: int,
    *,
    title: str,
    telegram_text: str,
    notif_type: str,
    related_sym: str | None = None,
    notif_body: str | None = None,
) -> None:
    """Record a Notification and push to enabled channels (Telegram only for now)."""
    from datetime import datetime, timezone
    from models import Notification

    db.add(Notification(
        user_id=user_id,
        type=notif_type,
        title=title,
        body=notif_body or telegram_text,
        related_sym=related_sym,
        created_at=datetime.now(timezone.utc),
    ))
    db.commit()

    if telegram_enabled(db, user_id):
        from services.telegram_service import send_telegram_sync
        send_telegram_sync(user_id, telegram_text)
