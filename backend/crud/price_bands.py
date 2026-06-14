from __future__ import annotations
from sqlalchemy.orm import Session
from models import PriceBand


def list_active(db: Session, user_id: int) -> list[PriceBand]:
    return db.query(PriceBand).filter(
        PriceBand.user_id == user_id,
        PriceBand.is_active == True,
    ).all()


def upsert(db: Session, user_id: int, sym: str, category: str, **fields) -> PriceBand:
    row = db.query(PriceBand).filter(
        PriceBand.user_id == user_id,
        PriceBand.sym == sym,
        PriceBand.category == category,
    ).first()
    if not row:
        row = PriceBand(user_id=user_id, sym=sym, category=category)
        db.add(row)
    for k, v in fields.items():
        if hasattr(row, k):
            setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row
