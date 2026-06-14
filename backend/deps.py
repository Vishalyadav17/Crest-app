from __future__ import annotations
import os
import logging
from fastapi import Request, HTTPException
from sqlalchemy.orm import Session

log = logging.getLogger(__name__)

_DEFAULT_USER_ID: int | None = None


def _get_default_user_id() -> int:
    """Resolve dev user once at first call; cache result for the process lifetime."""
    global _DEFAULT_USER_ID
    if _DEFAULT_USER_ID is not None:
        return _DEFAULT_USER_ID

    # 1. Explicit env override
    env_val = int(os.getenv("DEV_USER_ID", "0"))
    if env_val:
        _DEFAULT_USER_ID = env_val
        log.debug("dev user from DEV_USER_ID env: %d", env_val)
        return env_val

    # 2. Resolve from config.json allowed_email → User row, then fallback to lowest id
    try:
        import json
        from pathlib import Path
        cfg = json.loads((Path(__file__).parent / "config.json").read_text())
        allowed = cfg.get("auth", {}).get("allowed_email", "")
        from database import SessionLocal
        from models import User
        db = SessionLocal()
        try:
            if allowed:
                u = db.query(User).filter(User.email == allowed).first()
                if u:
                    _DEFAULT_USER_ID = u.id
                    log.debug("dev user resolved from allowed_email: id=%d", u.id)
                    return u.id
            u = db.query(User).order_by(User.id.asc()).first()
            if u:
                _DEFAULT_USER_ID = u.id
                log.debug("dev user resolved to lowest id: %d", u.id)
                return u.id
        finally:
            db.close()
    except Exception as e:
        log.warning("dev user resolution failed: %s", e)

    _DEFAULT_USER_ID = 1
    log.warning("dev user fallback to id=1")
    return 1


def get_current_user_id(request: Request, db: Session) -> int:
    from auth import is_auth_enabled
    if not is_auth_enabled():
        return _get_default_user_id()
    user_id = request.session.get("user_id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user_id
