"""
Module — Custom Indices.
CRUD for user-defined synthetic indices + history serving.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from deps import get_current_user_id
from models import CustomIndex, CustomIndexMember, CustomIndexHistory, PriceSnapshot

log = logging.getLogger(__name__)
router = APIRouter(prefix="/api/custom-indices", tags=["custom_indices"])


# ── helpers ───────────────────────────────────────────────────────────────────

def _get_index_or_404(db: Session, idx_id: int, user_id: int) -> CustomIndex:
    idx = db.query(CustomIndex).filter(
        CustomIndex.id == idx_id, CustomIndex.user_id == user_id
    ).one_or_none()
    if idx is None:
        raise HTTPException(404, "Index not found")
    return idx


def _member_count(db: Session, idx_id: int) -> int:
    return db.query(CustomIndexMember).filter(CustomIndexMember.custom_index_id == idx_id).count()


def _last_history(db: Session, idx_id: int):
    return (
        db.query(CustomIndexHistory)
        .filter(CustomIndexHistory.custom_index_id == idx_id)
        .order_by(CustomIndexHistory.date.desc())
        .first()
    )


def _serialize_index(db: Session, idx: CustomIndex) -> dict:
    last = _last_history(db, idx.id)
    prev = None
    if last:
        prev_row = (
            db.query(CustomIndexHistory)
            .filter(
                CustomIndexHistory.custom_index_id == idx.id,
                CustomIndexHistory.date < last.date,
            )
            .order_by(CustomIndexHistory.date.desc())
            .first()
        )
        if prev_row and prev_row.value:
            prev = float(prev_row.value)
    last_value = float(last.value) if last else None
    change_1d = None
    if last_value and prev:
        change_1d = round((last_value - prev) / prev * 100, 2)
    return {
        "id": idx.id,
        "name": idx.name,
        "kind": idx.kind,
        "weight_mode": idx.weight_mode,
        "base_date": idx.base_date,
        "member_count": _member_count(db, idx.id),
        "last_value": last_value,
        "last_date": last.date if last else None,
        "change_1d_pct": change_1d,
    }


# ── list ──────────────────────────────────────────────────────────────────────

@router.get("")
def list_indices(request: Request, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request, db)
    rows = db.query(CustomIndex).filter(CustomIndex.user_id == user_id).order_by(CustomIndex.kind, CustomIndex.name).all()
    return {"indices": [_serialize_index(db, r) for r in rows]}


# ── create ────────────────────────────────────────────────────────────────────

class CreateIndexBody(BaseModel):
    name: str
    symbols: list[str]
    weight_mode: str = "mcap"


@router.post("", status_code=201)
def create_index(request: Request, body: CreateIndexBody, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request, db)
    if not body.name.strip():
        raise HTTPException(400, "name required")
    if len(body.symbols) < 2:
        raise HTTPException(400, "at least 2 symbols required")
    syms = [s.strip().upper() for s in body.symbols if s.strip()]
    existing = db.query(CustomIndex).filter(
        CustomIndex.user_id == user_id, CustomIndex.name == body.name
    ).one_or_none()
    if existing:
        raise HTTPException(409, f"Index '{body.name}' already exists")
    idx = CustomIndex(
        user_id=user_id,
        name=body.name.strip(),
        kind="user",
        weight_mode=body.weight_mode if body.weight_mode in ("mcap", "equal") else "mcap",
    )
    db.add(idx)
    db.flush()
    for sym in syms:
        db.add(CustomIndexMember(custom_index_id=idx.id, sym=sym))
    db.commit()
    # Trigger background compute
    import threading; threading.Thread(target=_compute_one_sync, args=(idx.id,), daemon=True).start()
    return _serialize_index(db, idx)


# ── update ────────────────────────────────────────────────────────────────────

class UpdateIndexBody(BaseModel):
    name: str | None = None
    symbols: list[str] | None = None
    weight_mode: str | None = None


@router.put("/{idx_id}")
def update_index(request: Request, idx_id: int, body: UpdateIndexBody, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request, db)
    idx = _get_index_or_404(db, idx_id, user_id)
    if body.name is not None and body.name.strip():
        idx.name = body.name.strip()
    if body.weight_mode in ("mcap", "equal"):
        idx.weight_mode = body.weight_mode
    if body.symbols is not None:
        syms = [s.strip().upper() for s in body.symbols if s.strip()]
        if len(syms) < 2:
            raise HTTPException(400, "at least 2 symbols required")
        db.query(CustomIndexMember).filter(CustomIndexMember.custom_index_id == idx.id).delete()
        for sym in syms:
            db.add(CustomIndexMember(custom_index_id=idx.id, sym=sym))
        # Drop stale history so recompute starts fresh
        db.query(CustomIndexHistory).filter(CustomIndexHistory.custom_index_id == idx.id).delete()
        db.commit()
        import threading; threading.Thread(target=_compute_one_sync, args=(idx.id,), daemon=True).start()
    else:
        db.commit()
    db.refresh(idx)
    return _serialize_index(db, idx)


# ── delete ────────────────────────────────────────────────────────────────────

@router.delete("/{idx_id}", status_code=204)
def delete_index(request: Request, idx_id: int, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request, db)
    idx = _get_index_or_404(db, idx_id, user_id)
    db.delete(idx)
    db.commit()


# ── history ───────────────────────────────────────────────────────────────────

@router.get("/{idx_id}/history")
def get_history(request: Request, idx_id: int, period: str = "1y", db: Session = Depends(get_db)):
    user_id = get_current_user_id(request, db)
    _get_index_or_404(db, idx_id, user_id)
    from datetime import timedelta
    _period_days = {"3m": 90, "6m": 180, "1y": 365, "2y": 730, "3y": 1095, "5y": 1825, "max": 99999}
    days = _period_days.get(period, 365)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = (
        db.query(CustomIndexHistory)
        .filter(
            CustomIndexHistory.custom_index_id == idx_id,
            CustomIndexHistory.date >= cutoff,
        )
        .order_by(CustomIndexHistory.date)
        .all()
    )

    def _candle(r):
        close = float(r.value)
        return {
            "time":   r.date,
            "open":   float(r.open) if r.open is not None else close,
            "high":   float(r.high) if r.high is not None else close,
            "low":    float(r.low) if r.low is not None else close,
            "close":  close,
            "volume": float(r.volume) if r.volume is not None else 0.0,
        }

    return {
        "series":  [{"date": r.date, "value": float(r.value)} for r in rows],
        "candles": [_candle(r) for r in rows],
    }


# ── members ───────────────────────────────────────────────────────────────────

@router.get("/{idx_id}/members")
def get_members(request: Request, idx_id: int, db: Session = Depends(get_db)):
    user_id = get_current_user_id(request, db)
    _get_index_or_404(db, idx_id, user_id)
    members = db.query(CustomIndexMember).filter(CustomIndexMember.custom_index_id == idx_id).all()
    syms = [m.sym for m in members]
    # Live snapshots first; fall back to scan-refreshed bhavcopy closes for the rest.
    snaps = db.query(PriceSnapshot).filter(PriceSnapshot.sym.in_(syms)).all()
    snap_map = {s.sym: s for s in snaps}
    bhav_map = _bhavcopy_ltp_map(db, syms)

    result = []
    for sym in syms:
        snap = snap_map.get(sym)
        ltp = float(snap.ltp) if snap and snap.ltp else None
        chg = float(snap.day_change_pct) if snap and snap.day_change_pct else None
        if ltp is None:
            bh = bhav_map.get(sym)
            if bh:
                ltp, chg = bh
        result.append({"sym": sym, "ltp": ltp, "change_1d_pct": chg})
    return {"members": result}


def _bhavcopy_ltp_map(db: Session, syms: list[str]) -> dict[str, tuple[float, float | None]]:
    """Last close + 1d % change per sym from the latest two bhavcopy_daily rows."""
    from models import BhavcopydAily as BhavCopyDaily
    rows = (
        db.query(BhavCopyDaily.sym, BhavCopyDaily.date, BhavCopyDaily.close)
        .filter(BhavCopyDaily.sym.in_(syms))
        .order_by(BhavCopyDaily.sym, BhavCopyDaily.date.desc())
        .all()
    )
    by_sym: dict[str, list[float]] = {}
    for sym, _date, close in rows:
        lst = by_sym.setdefault(sym, [])
        if len(lst) < 2:
            lst.append(float(close))
    out: dict[str, tuple[float, float | None]] = {}
    for sym, closes in by_sym.items():
        ltp = closes[0]
        chg = round((closes[0] - closes[1]) / closes[1] * 100, 2) if len(closes) == 2 and closes[1] else None
        out[sym] = (ltp, chg)
    return out


# ── inline compute (called after create/update) ───────────────────────────────

def _compute_one_sync(idx_id: int):
    from services.custom_index_compute import compute_and_persist
    from database import SessionLocal
    db = SessionLocal()
    try:
        compute_and_persist(db, idx_id)
    except Exception as e:
        log.warning("inline compute idx %d: %s", idx_id, e)
    finally:
        db.close()
