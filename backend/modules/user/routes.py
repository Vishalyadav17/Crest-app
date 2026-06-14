"""
User preferences & dashboard module config API.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import is_authenticated
from database import get_db
from deps import get_current_user_id
from crud.prefs import get_all_prefs, set_pref, get_dashboard_modules, set_dashboard_module
from models import User

router = APIRouter(prefix="/api/user", tags=["user"])


def _auth(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None


class PrefSet(BaseModel):
    key: str
    value: str


class ModuleUpdate(BaseModel):
    is_enabled: bool | None = None
    display_order: int | None = None
    custom_label: str | None = None
    config: str | None = None


class UserSetup(BaseModel):
    tier: str  # "free" | "pro"


@router.get("/me")
async def get_me(request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return JSONResponse({"error": "user_not_found"}, status_code=404)
    return {
        "id":                   user.id,
        "email":                user.email,
        "name":                 user.name,
        "avatar_url":           user.avatar_url,
        "tier":                 user.tier,
        "onboarding_complete":  user.onboarding_complete,
    }


@router.post("/setup")
async def complete_setup(request: Request, body: UserSetup, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        return JSONResponse({"error": "user_not_found"}, status_code=404)
    if body.tier not in ("free", "pro"):
        return JSONResponse({"error": "invalid_tier"}, status_code=400)
    user.tier = body.tier
    user.onboarding_complete = True
    db.commit()
    return {"ok": True, "tier": user.tier}


@router.get("/preferences")
async def get_prefs(request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    return get_all_prefs(db, user_id)


@router.put("/preferences")
async def set_pref_endpoint(request: Request, body: PrefSet, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    set_pref(db, user_id, body.key, body.value)
    return {"ok": True, "key": body.key}


@router.get("/dashboard")
async def get_dashboard(request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    return get_dashboard_modules(db, user_id)


@router.put("/dashboard/{module_key}")
async def update_dashboard_module(
    module_key: str, request: Request, body: ModuleUpdate, db: Session = Depends(get_db)
):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    kwargs = {k: v for k, v in body.model_dump().items() if v is not None}
    return set_dashboard_module(db, user_id, module_key, **kwargs)
