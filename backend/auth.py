"""
Google OAuth.
Credentials come from .env (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, SESSION_SECRET).
Allowlist: if config.json auth.allowed_email is set, only that account may sign in.
If empty/unset, any Google account is accepted (multi-user mode).
"""
from __future__ import annotations
import logging
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

from authlib.integrations.starlette_client import OAuth
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

log = logging.getLogger(__name__)

oauth = OAuth()


_DEV_SECRET = "dev-secret-change-in-production"


def get_session_secret() -> str:
    s = os.getenv("SESSION_SECRET", _DEV_SECRET)
    if is_auth_enabled() and (not s or s == _DEV_SECRET):
        raise RuntimeError(
            "SESSION_SECRET must be set to a strong random value when auth.enabled=true. "
            "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
        )
    return s


def is_auth_enabled() -> bool:
    import json
    from pathlib import Path
    try:
        cfg = json.loads((Path(__file__).parent / "config.json").read_text())
        return cfg.get("auth", {}).get("enabled", False)
    except Exception:
        return False


def setup_oauth() -> None:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "")
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "")
    if not client_id or client_id == "FILL_IN_FROM_GOOGLE_CONSOLE":
        log.warning("Google OAuth credentials not set — auth will not work if enabled")
        return
    oauth.register(
        name="google",
        client_id=client_id,
        client_secret=client_secret,
        server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
        client_kwargs={"scope": "openid email profile"},
    )


def is_authenticated(request: Request) -> bool:
    if not is_auth_enabled():
        return True
    return "user_id" in request.session


def get_user_email(request: Request) -> str | None:
    return request.session.get("user_email")


router = APIRouter()


@router.get("/auth/google")
async def login(request: Request):
    import json
    from pathlib import Path
    cfg = json.loads((Path(__file__).parent / "config.json").read_text())
    redirect_uri = cfg["auth"].get("redirect_uri", "http://localhost:8000/auth/google/callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/auth/google/callback")
async def callback(request: Request):
    from datetime import datetime, timezone
    from database import SessionLocal
    from models import User

    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as e:
        log.error("OAuth callback error: %s", e)
        return RedirectResponse("/login.html?auth_error=1")

    info = token.get("userinfo") or {}
    email = info.get("email", "").lower()
    google_id = info.get("sub", "")
    name = info.get("name", email.split("@")[0])
    avatar = info.get("picture", "")

    if not email:
        return RedirectResponse("/login.html?auth_error=no_email")

    # Allowlist enforcement
    import json as _json
    try:
        _cfg = _json.loads((Path(__file__).parent / "config.json").read_text())
        allowed = (_cfg.get("auth", {}).get("allowed_email") or "").strip().lower()
    except Exception:
        allowed = ""
    if allowed and email != allowed:
        log.warning("Rejected login from %s (not in allowlist)", email)
        return RedirectResponse("/login.html?auth_error=forbidden")

    db = SessionLocal()
    try:
        user = db.query(User).filter(User.google_id == google_id).first()
        if not user:
            user = db.query(User).filter(User.email == email).first()
        is_new = user is None
        if is_new:
            user = User(email=email, google_id=google_id, name=name, avatar_url=avatar, tier="free", onboarding_complete=False)
            db.add(user)
        else:
            user.google_id = google_id
            user.avatar_url = avatar
            if name:
                user.name = name
        user.last_login = datetime.now(timezone.utc)
        db.commit()
        db.refresh(user)

        request.session["user_id"] = user.id
        request.session["user_email"] = user.email
        request.session["user_name"] = user.name or ""

        log.info("Login: %s (id=%d, new=%s)", email, user.id, is_new)
        if not user.onboarding_complete:
            return RedirectResponse("/onboarding")
        return RedirectResponse("/")
    finally:
        db.close()


@router.post("/auth/logout")
async def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)
