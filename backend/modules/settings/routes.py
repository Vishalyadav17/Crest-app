from __future__ import annotations
from fastapi import APIRouter, Depends, Request, UploadFile, File, Form
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from sqlalchemy.orm import Session

from auth import is_authenticated
from database import get_db
from deps import get_current_user_id
from crud.prefs import get_all_prefs, set_pref
from models import User
from models import ProviderCredential
from services.portfolio_service import recompute_portfolio_snapshot

router = APIRouter(prefix="/api/settings", tags=["settings"])


def _count_active_keys(db: Session, user_id: int) -> int:
    return db.query(ProviderCredential).filter(
        ProviderCredential.user_id == user_id,
        ProviderCredential.status == "active",
    ).count()


def _auth(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None


@router.get("/profile")
async def get_profile(request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return JSONResponse({"error": "user_not_found"}, status_code=404)
    prefs = get_all_prefs(db, user_id)
    return {
        "email": user.email,
        "name": user.name,
        "tier": user.tier,
        "created_at": user.created_at.isoformat() if user.created_at else None,
        "kite_linked": prefs.get("kite_linked") == "1",
        "telegram_linked": bool(prefs.get("telegram_chat_id")),
        "model_configs_count": _count_active_keys(db, user_id),
    }


@router.post("/refresh-holdings")
async def refresh_holdings(request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    snap = recompute_portfolio_snapshot(user_id, db)
    return {
        "ok": True,
        "total_wealth": float(snap.total_wealth) if snap.total_wealth is not None else None,
        "computed_at": snap.computed_at.isoformat() if snap.computed_at else None,
    }


@router.get("/preferences")
async def get_preferences(request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    prefs = get_all_prefs(db, user_id)
    return {
        "theme": prefs.get("theme", "dark"),
        "privacy_mode": prefs.get("privacy_mode", "0") == "1",
        "digest_morning_opt_in": prefs.get("digest_morning_opt_in", "0") == "1",
        "digest_eod_opt_in": prefs.get("digest_eod_opt_in", "0") == "1",
        "auto_prune_enabled": prefs.get("auto_prune_enabled", "1") == "1",
        "alert_telegram_enabled": prefs.get("alert_telegram_enabled", "1") == "1",
        "alert_email_enabled": prefs.get("alert_email_enabled", "1") == "1",
    }


@router.put("/preferences")
async def update_preferences(request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    body = await request.json()
    allowed = {"theme", "privacy_mode", "digest_morning_opt_in", "digest_eod_opt_in", "auto_prune_enabled", "alert_telegram_enabled", "alert_email_enabled"}
    for k, v in body.items():
        if k in allowed:
            set_pref(db, user_id, k, "1" if v is True else ("0" if v is False else str(v)))
    return {"ok": True}


# ── Test digest endpoint ───────────────────────────────────────────────────────

@router.get("/test-digest")
async def test_digest(request: Request, db: Session = Depends(get_db), kind: str = "morning"):
    """Render digest HTML without sending — for verifying template output."""
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    from services.email_service import render_morning_digest, render_eod_digest
    if kind == "eod":
        html = render_eod_digest(user_id)
    else:
        html = render_morning_digest(user_id)
    return HTMLResponse(content=html)


# ── Telegram link flow ─────────────────────────────────────────────────────────

@router.post("/telegram/link-code")
async def telegram_link_code(request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    from services.telegram_service import generate_link_code, get_bot_username
    code = generate_link_code(user_id)
    bot_username = get_bot_username()
    deep_link = f"https://t.me/{bot_username}?start={code}" if bot_username else None
    return {"code": code, "deep_link": deep_link, "expires_in_minutes": 10}


@router.post("/telegram/unlink")
async def telegram_unlink(request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    set_pref(db, user_id, "telegram_chat_id", "")
    return {"ok": True}


@router.get("/telegram/status")
async def telegram_status(request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    prefs = get_all_prefs(db, user_id)
    chat_id = prefs.get("telegram_chat_id", "")
    return {
        "linked": bool(chat_id),
        "chat_id": chat_id or None,
    }


# ── BYOK LLM Keys API ─────────────────────────────────────────────────────────

@router.post("/keys")
async def add_key(request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    body = await request.json()
    provider = body.get("provider", "").strip()
    key_label = body.get("key_label", "default").strip()
    key = body.get("key", "").strip()
    if not provider or not key:
        return JSONResponse({"error": "provider and key required"}, status_code=400)
    from crud.credentials import add_credential
    from services.llm.crypto import mask
    try:
        row = add_credential(db, user_id, provider, key_label, key)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    try:
        plain = key
        masked = mask(plain)
    except Exception:
        masked = "****"
    return {"id": row.id, "provider": row.provider, "key_label": row.key_label, "key_masked": masked, "status": row.status}


@router.get("/keys")
async def list_keys(request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    from crud.credentials import list_credentials
    return {"keys": list_credentials(db, user_id)}


@router.delete("/keys/{cred_id}")
async def delete_key(cred_id: int, request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    from crud.credentials import delete_credential
    deleted = delete_credential(db, user_id, cred_id)
    if not deleted:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return {"ok": True}


@router.post("/keys/{cred_id}/test")
async def test_key(cred_id: int, request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    from models import ProviderCredential
    from services.llm.crypto import decrypt
    row = db.query(ProviderCredential).filter(
        ProviderCredential.id == cred_id,
        ProviderCredential.user_id == user_id,
    ).first()
    if not row:
        return JSONResponse({"error": "not_found"}, status_code=404)
    try:
        plain = decrypt(row.ciphertext)
    except Exception:
        return JSONResponse({"ok": False, "error": "decrypt_failed"}, status_code=200)

    import httpx
    from services.llm.config import REQUEST_TIMEOUT
    from services.llm.providers import PROVIDERS, TASK_MODELS
    from services.llm.router import _headers, _url

    if row.provider not in PROVIDERS:
        return JSONResponse({"ok": False, "error": f"unknown provider {row.provider}"}, status_code=400)

    test_model = next(
        (m for tasks in TASK_MODELS.values() for p, m in tasks if p == row.provider),
        next(iter(PROVIDERS[row.provider]["allowlist"]), None),
    )
    if not test_model:
        return JSONResponse({"ok": False, "error": "no model for provider"}, status_code=400)

    body = {
        "model": test_model,
        "messages": [{"role": "user", "content": "Reply with just: OK"}],
        "max_tokens": 5,
        "temperature": 0.0,
    }
    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.post(_url(row.provider), headers=_headers(row.provider, plain), json=body)
        if resp.status_code == 200:
            return {"ok": True, "provider": row.provider, "model": test_model}
        return JSONResponse(
            {"ok": False, "error": f"HTTP {resp.status_code}: {resp.text[:200]}"},
            status_code=200,
        )
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=200)


@router.get("/providers")
async def list_providers(request: Request):
    """Return configured LLM provider list so FE doesn't hardcode it."""
    from services.llm.providers import PROVIDERS, ORDER
    result = []
    for name in ORDER:
        cfg = PROVIDERS.get(name, {})
        result.append({
            "name":      name,
            "label":     name.capitalize(),
            "needs_key": not cfg.get("always_free", False),
            "key_hint":  cfg.get("env_var", ""),
        })
    return result


@router.get("/mf/scheme-search")
async def mf_scheme_search(q: str, request: Request):
    """Search AMFI scheme list by fund name. Returns top-5 matches."""
    from shared.cache import cache_get
    schemes = cache_get("amfi_scheme_list", ttl_seconds=86400)
    if not schemes:
        return {"results": [], "hint": "AMFI data not cached yet — run the MF NAV job first"}
    q_upper = q.strip().upper()
    if not q_upper:
        return {"results": []}
    matches = [s for s in schemes if q_upper in s["name"].upper()]
    # score: exact prefix > contains
    matches.sort(key=lambda s: (0 if s["name"].upper().startswith(q_upper) else 1, s["name"]))
    return {"results": matches[:5]}


# ── Order Flow routes ─────────────────────────────────────────────────────────

@router.get("/order-flow")
async def get_order_flow(request: Request, db: Session = Depends(get_db)):
    """
    Order flow overview: tracked symbols, their QTD orders, setup scores, guidance.
    Includes recent announcements list.
    """
    err = _auth(request)
    if err:
        return err
    from models import OrderAnnouncement, EarningsGuidance, StockMaster
    from services.earnings_setup import get_tracked_syms, get_or_compute_setup

    syms = get_tracked_syms(db)
    rows = []
    for sym in syms:
        setup = get_or_compute_setup(db, sym)
        guidance = db.query(EarningsGuidance).filter(EarningsGuidance.sym == sym).first()
        sm = db.query(StockMaster).filter(StockMaster.sym == sym).first()
        latest_anns = (
            db.query(OrderAnnouncement)
            .filter(OrderAnnouncement.sym == sym)
            .order_by(OrderAnnouncement.ann_date.desc())
            .limit(3)
            .all()
        )
        rows.append({
            "sym": sym,
            "name": sm.name if sm else sym,
            "qtd_orders_cr": setup["qtd_orders_cr"],
            "last_ann_date": setup["last_ann_date"],
            "ann_count": setup["ann_count"],
            "vs_prev_q": setup["vs_prev_q"],
            "vs_guidance": setup["vs_guidance"],
            "score": setup["score"],
            "last_q_revenue_cr": float(sm.last_q_revenue_cr) if sm and sm.last_q_revenue_cr else None,
            "next_earnings_date": sm.next_earnings_date if sm else None,
            "guidance": {
                "fy_revenue_guidance_cr": float(guidance.fy_revenue_guidance_cr) if guidance and guidance.fy_revenue_guidance_cr else None,
                "q_revenue_guidance_cr": float(guidance.q_revenue_guidance_cr) if guidance and guidance.q_revenue_guidance_cr else None,
                "guidance_note": guidance.guidance_note if guidance else None,
                "guidance_as_of": guidance.guidance_as_of if guidance else None,
            } if guidance else None,
            "recent_announcements": [
                {
                    "ann_date": a.ann_date,
                    "headline": a.headline,
                    "value_cr": float(a.value_cr) if a.value_cr else None,
                    "extraction": a.extraction,
                    "source_url": a.source_url,
                }
                for a in latest_anns
            ],
        })
    return {"tracked_syms": rows}


@router.put("/order-flow/guidance/{sym}")
async def upsert_guidance(sym: str, request: Request, db: Session = Depends(get_db)):
    """Upsert EarningsGuidance for a symbol (manual v1 entry)."""
    err = _auth(request)
    if err:
        return err
    from models import EarningsGuidance
    from datetime import date as date_cls
    from shared.cache import cache_set

    body = await request.json()
    sym = sym.upper()
    row = db.query(EarningsGuidance).filter(EarningsGuidance.sym == sym).first()
    if not row:
        row = EarningsGuidance(sym=sym)
        db.add(row)
    if "fy_revenue_guidance_cr" in body:
        row.fy_revenue_guidance_cr = body["fy_revenue_guidance_cr"]
    if "q_revenue_guidance_cr" in body:
        row.q_revenue_guidance_cr = body["q_revenue_guidance_cr"]
    if "guidance_note" in body:
        row.guidance_note = body["guidance_note"]
    row.guidance_as_of = date_cls.today().isoformat()
    db.commit()
    # invalidate setup cache
    cache_set(f"earnings_setup|{sym}", None, 1)
    return {"ok": True, "sym": sym}


@router.post("/order-flow/guidance/{sym}/notebook-sync")
async def notebook_sync_guidance(sym: str, request: Request, db: Session = Depends(get_db)):
    """Pull revenue/PAT guidance for a symbol from its mapped NotebookLM notebook (if configured)
    and upsert EarningsGuidance. Returns updated=False when no notebook is mapped / auth missing."""
    err = _auth(request)
    if err:
        return err
    from services.notebooklm_connector import sync_guidance, get_notebook_url
    if not get_notebook_url(sym):
        return {"ok": False, "updated": False, "reason": "no NotebookLM notebook mapped for this symbol"}
    updated = await __import__("asyncio").get_event_loop().run_in_executor(None, sync_guidance, db, sym)
    return {"ok": True, "updated": bool(updated)}


@router.post("/order-flow/announcements/{sym}/manual")
async def add_manual_announcement(sym: str, request: Request, db: Session = Depends(get_db)):
    """Manually add an order announcement (extraction='manual')."""
    err = _auth(request)
    if err:
        return err
    from models import OrderAnnouncement
    from services.earnings_setup import invalidate_setup_cache

    body = await request.json()
    sym = sym.upper()
    row = OrderAnnouncement(
        sym=sym,
        ann_date=body.get("ann_date", ""),
        headline=body.get("headline", ""),
        body_excerpt=body.get("body_excerpt"),
        value_cr=body.get("value_cr"),
        extraction="manual",
        source_url=body.get("source_url"),
    )
    db.add(row)
    try:
        db.commit()
    except Exception:
        db.rollback()
        return JSONResponse({"error": "duplicate or invalid"}, status_code=409)
    invalidate_setup_cache(sym)
    return {"ok": True, "id": row.id}


@router.get("/order-flow/announcements/{sym}")
async def list_announcements(
    sym: str, request: Request, db: Session = Depends(get_db), limit: int = 50
):
    """List order announcements for a symbol."""
    err = _auth(request)
    if err:
        return err
    from models import OrderAnnouncement
    if limit > 100:
        limit = 100
    sym = sym.upper()
    anns = (
        db.query(OrderAnnouncement)
        .filter(OrderAnnouncement.sym == sym)
        .order_by(OrderAnnouncement.ann_date.desc())
        .limit(limit)
        .all()
    )
    return {
        "sym": sym,
        "announcements": [
            {
                "id": a.id,
                "ann_date": a.ann_date,
                "headline": a.headline,
                "value_cr": float(a.value_cr) if a.value_cr else None,
                "extraction": a.extraction,
                "source_url": a.source_url,
                "body_excerpt": a.body_excerpt,
            }
            for a in anns
        ],
    }


# ── CAS MF Upload ─────────────────────────────────────────────────────────────

@router.post("/mf/cas-upload")
async def cas_upload(
    request: Request,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
    password: str = Form(...),
):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)

    import io
    import casparser
    from crud.mf import upsert_cas_holdings

    data = await file.read()
    buf = io.BytesIO(data)
    try:
        cas = casparser.read_cas_pdf(buf, password)
    except Exception as e:
        msg = str(e).lower()
        if "password" in msg or "decrypt" in msg or "wrong" in msg:
            return JSONResponse({"error": "wrong_password", "detail": "Incorrect PDF password."}, status_code=422)
        if "image" in msg or "scanned" in msg or "ocr" in msg:
            return JSONResponse({"error": "scanned_pdf", "detail": "Scanned-image PDFs are not supported."}, status_code=422)
        return JSONResponse({"error": "parse_error", "detail": str(e)}, status_code=422)

    holdings = []
    for folio in cas.folios:
        for scheme in folio.schemes:
            units = float(scheme.close) if scheme.close is not None else None
            nav   = float(scheme.valuation.nav) if scheme.valuation and scheme.valuation.nav else None
            cost  = float(scheme.valuation.cost) if scheme.valuation and scheme.valuation.cost else None
            value = float(scheme.valuation.value) if scheme.valuation and scheme.valuation.value else None
            avg_nav = round(cost / units, 4) if (cost and units and units > 0) else nav
            holdings.append({
                "name":          scheme.scheme,
                "amc":           folio.amc,
                "scheme_code":   scheme.amfi,
                "folio_number":  folio.folio,
                "type":          scheme.type,
                "units":         units,
                "avg_nav":       avg_nav,
                "current_nav":   nav,
                "invested":      cost,
                "current_value": value,
            })

    upsert_cas_holdings(db, user_id, holdings)
    return {
        "ok": True,
        "imported": len(holdings),
        "folios":   len(cas.folios),
        "funds": [
            {"name": h["name"], "amc": h["amc"], "units": h["units"],
             "invested": h["invested"], "current_value": h["current_value"]}
            for h in holdings
        ],
    }


# ── Backup ────────────────────────────────────────────────────────────────────

@router.post("/backup/run")
async def backup_run(request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    from services.backup_service import run_backup
    path, date_str = run_backup(user_id, db)
    return {"ok": True, "date": date_str, "path": path}


@router.get("/backup/list")
async def backup_list(request: Request):
    err = _auth(request)
    if err:
        return err
    from services.backup_service import list_backups
    return {"backups": list_backups()}


@router.get("/backup/download/{date_str}")
async def backup_download(date_str: str, request: Request):
    err = _auth(request)
    if err:
        return err
    from services.backup_service import get_backup_zip
    import re
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str):
        return JSONResponse({"error": "invalid date"}, status_code=400)
    zip_path = get_backup_zip(date_str)
    if not zip_path:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return FileResponse(zip_path, media_type="application/zip", filename=f"crest-backup-{date_str}.zip")
