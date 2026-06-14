from __future__ import annotations
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from database import get_db
from deps import get_current_user_id
from models import PriceAlert, Notification

router = APIRouter(prefix="/api", tags=["alerts"])


@router.get("/alerts")
async def list_alerts(
    request: Request, db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    user_id = get_current_user_id(request, db)
    rows = (
        db.query(PriceAlert)
        .filter(PriceAlert.user_id == user_id)
        .order_by(PriceAlert.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_alert_dict(r) for r in rows]


@router.post("/alerts")
async def create_alert(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request, db)
    data = await request.json()
    sym = (data.get("sym") or "").strip().upper()
    if not sym:
        return JSONResponse({"error": "sym required"}, status_code=422)
    alert = PriceAlert(
        user_id=user_id,
        sym=sym,
        name=data.get("name"),
        condition=data.get("condition", "above"),
        target_price=data.get("target_price"),
        note=data.get("note"),
        created_at=datetime.now(timezone.utc),
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return _alert_dict(alert)


@router.delete("/alerts/{alert_id}")
async def delete_alert(alert_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request, db)
    row = db.query(PriceAlert).filter(
        PriceAlert.id == alert_id,
        PriceAlert.user_id == user_id,
    ).first()
    if not row:
        return JSONResponse({"error": "not_found"}, status_code=404)
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.patch("/alerts/{alert_id}/reset")
async def reset_alert(alert_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request, db)
    row = db.query(PriceAlert).filter(
        PriceAlert.id == alert_id,
        PriceAlert.user_id == user_id,
    ).first()
    if not row:
        return JSONResponse({"error": "not_found"}, status_code=404)
    row.is_triggered = False
    row.triggered_at = None
    db.commit()
    return {"ok": True}


@router.get("/notifications")
async def list_notifications(
    request: Request, db: Session = Depends(get_db),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
):
    user_id = get_current_user_id(request, db)
    rows = (
        db.query(Notification)
        .filter(Notification.user_id == user_id)
        .order_by(Notification.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [_notif_dict(r) for r in rows]


@router.patch("/notifications/{notif_id}/read")
async def mark_read(notif_id: int, request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request, db)
    row = db.query(Notification).filter(
        Notification.id == notif_id,
        Notification.user_id == user_id,
    ).first()
    if not row:
        return JSONResponse({"error": "not_found"}, status_code=404)
    row.is_read = True
    db.commit()
    return {"ok": True}


@router.post("/notifications/mark-all-read")
async def mark_all_read(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request, db)
    db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.is_read == False,
    ).update({"is_read": True}, synchronize_session=False)
    db.commit()
    return {"ok": True}


def _alert_dict(r: PriceAlert) -> dict:
    return {
        "id":           r.id,
        "sym":          r.sym,
        "name":         r.name,
        "condition":    r.condition,
        "target_price": float(r.target_price) if r.target_price is not None else None,
        "is_triggered": r.is_triggered,
        "triggered_at": r.triggered_at.isoformat() if r.triggered_at else None,
        "note":         r.note,
        "created_at":   r.created_at.isoformat() if r.created_at else None,
    }


def _notif_dict(r: Notification) -> dict:
    return {
        "id":          r.id,
        "type":        r.type,
        "title":       r.title,
        "body":        r.body,
        "is_read":     r.is_read,
        "related_sym": r.related_sym,
        "created_at":  r.created_at.isoformat() if r.created_at else None,
    }
