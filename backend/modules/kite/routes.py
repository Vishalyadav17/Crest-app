"""
Kite MCP read-only gateway.

Buttons call POST /api/kite/tool/{name} → persists → returns data.
Write tools are rejected 403. LLM query is BYOK-gated (phase 2).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from auth import is_authenticated
from database import get_db
from deps import get_current_user_id
from crud.prefs import get_pref, set_pref
from services.kite_mcp.client import (
    _READ_TOOLS,
    _WRITE_TOOLS,
    call_tool,
    is_authenticated as kite_is_authenticated,
    list_tools,
    open_session,
    start_login,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/kite", tags=["kite"])


def _auth(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None


def _get_sid(db: Session, user_id: int) -> str | None:
    return get_pref(db, user_id, "kite_session_id")


# ── Connect / status ───────────────────────────────────────────────────────────

@router.post("/connect")
async def connect(request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    try:
        sid = await open_session()
        login_url = await start_login(sid)
        set_pref(db, user_id, "kite_session_id", sid)
        set_pref(db, user_id, "kite_linked", "0")
        _refresh_portfolio_snapshot(user_id, db)
        return {"login_url": login_url, "session_id": sid[:16] + "..."}
    except Exception as e:
        log.error("kite connect error: %s", e)
        return JSONResponse({"error": str(e)}, status_code=503)


@router.get("/status")
async def status(request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    sid = _get_sid(db, user_id)
    if not sid:
        return {"authenticated": False, "linked": False}
    try:
        authenticated = await kite_is_authenticated(sid)
        if authenticated:
            set_pref(db, user_id, "kite_linked", "1")
        return {"authenticated": authenticated, "linked": authenticated}
    except Exception as e:
        log.warning("kite status error: %s", e)
        return {"authenticated": False, "linked": False, "error": str(e)}


@router.get("/tools")
async def get_tools(request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    sid = _get_sid(db, user_id)
    if not sid:
        return JSONResponse({"error": "not_connected"}, status_code=400)
    try:
        tools = await list_tools(sid)
        return {"tools": tools}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=503)


# ── Button-driven tool call (read-only) ────────────────────────────────────────

@router.post("/tool/{name}")
async def call(name: str, request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err

    if name in _WRITE_TOOLS:
        return JSONResponse(
            {"error": f"write tool '{name}' not permitted — read-only platform"},
            status_code=403,
        )
    if name not in _READ_TOOLS:
        return JSONResponse({"error": f"unknown tool '{name}'"}, status_code=400)

    user_id = get_current_user_id(request, db)
    sid = _get_sid(db, user_id)
    if not sid:
        return JSONResponse({"error": "not_connected — call /api/kite/connect first"}, status_code=400)

    try:
        body = await request.json()
    except Exception:
        body = {}

    args = body.get("args", body) if body else {}

    try:
        result = await call_tool(sid, name, args)
    except Exception as e:
        log.error("kite tool %s error: %s", name, e)
        return JSONResponse({"error": str(e)}, status_code=503)

    _persist(name, result, user_id, db)
    _refresh_portfolio_snapshot(user_id, db)
    return {"tool": name, "data": result}


def _refresh_portfolio_snapshot(user_id: int, db: Session) -> None:
    """Any Kite fetch can mutate holdings/MF — rebuild the cached portfolio
    snapshot so the Vault reflects fresh data instead of stale totals."""
    try:
        from services.portfolio_service import recompute_portfolio_snapshot
        recompute_portfolio_snapshot(user_id, db)
    except Exception as e:
        log.warning("kite: portfolio snapshot refresh failed: %s", e)


def _unwrap(result):
    """Strip a Kite REST-style envelope ({"status":..,"data":..}) so downstream
    sync_* receive the bare list/dict they expect."""
    if isinstance(result, dict) and "data" in result and set(result.keys()) <= {"status", "data", "message"}:
        return result["data"]
    return result


def _persist(name: str, result, user_id: int, db: Session) -> None:
    try:
        import crud.kite as ck
        from crud.prefs import set_pref as _sp
        from datetime import datetime, timezone

        result = _unwrap(result)
        now_iso = datetime.now(timezone.utc).isoformat()

        if name == "get_holdings":
            ck.sync_holdings(db, user_id, result if isinstance(result, list) else [])
            _sp(db, user_id, "kite_holdings_synced_at", now_iso)

        elif name == "get_mf_holdings":
            ck.sync_mf_holdings(db, user_id, result if isinstance(result, list) else [])
            _sp(db, user_id, "kite_mf_synced_at", now_iso)

        elif name == "get_positions":
            ck.sync_positions(db, user_id, result)
            _sp(db, user_id, "kite_positions_synced_at", now_iso)

        elif name == "get_orders":
            ck.sync_orders(db, user_id, result if isinstance(result, list) else [])
            _sp(db, user_id, "kite_orders_synced_at", now_iso)

        elif name == "get_trades":
            ck.sync_trades(db, user_id, result if isinstance(result, list) else [])
            _sp(db, user_id, "kite_trades_synced_at", now_iso)

        elif name == "get_margins":
            if isinstance(result, dict):
                ck.sync_margins(db, user_id, result)
                _sp(db, user_id, "kite_margins_synced_at", now_iso)

        elif name == "get_gtts":
            ck.sync_gtts(db, user_id, result if isinstance(result, list) else [])
            _sp(db, user_id, "kite_gtts_synced_at", now_iso)

        elif name in ("get_quotes", "get_ohlc", "get_ltp"):
            if isinstance(result, dict):
                ck.sync_quotes(db, result)

        elif name == "get_profile":
            _sync_profile(result, user_id, db, _sp, now_iso)

    except Exception as e:
        log.error("kite persist %s error: %s", name, e)


def _sync_profile(result, user_id: int, db, set_pref_fn, now_iso: str) -> None:
    if not isinstance(result, dict):
        return
    from models import User
    import json as _json
    user = db.query(User).filter(User.id == user_id).first()
    if user and not user.name:
        user.name = result.get("user_name")
        db.commit()
    set_pref_fn(db, user_id, "kite_user_id", str(result.get("user_id", "")))
    set_pref_fn(db, user_id, "kite_email", str(result.get("email", "")))
    set_pref_fn(db, user_id, "kite_profile_json", _json.dumps(result))
    set_pref_fn(db, user_id, "kite_linked", "1")
    set_pref_fn(db, user_id, "kite_profile_synced_at", now_iso)
