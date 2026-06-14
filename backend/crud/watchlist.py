from __future__ import annotations
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from models import Watchlist, WatchlistItem
from crud.stock import upsert_stock, search_stocks


def get_watchlists(db: Session, user_id: int) -> list[dict]:
    rows = db.query(Watchlist).filter(Watchlist.user_id == user_id).all()
    return [
        {
            "id":        w.id,
            "name":      w.name,
            "list_type": w.list_type,
            "symbols":   [
                {"sym": i.sym, "name": i.name or i.sym, "note": i.note}
                for i in sorted(w.items, key=lambda x: x.added_at or datetime.min)
            ],
        }
        for w in rows
    ]


def create_watchlist(db: Session, user_id: int, name: str, list_type: str = "custom") -> dict:
    wl = Watchlist(user_id=user_id, name=name, list_type=list_type)
    db.add(wl)
    db.commit()
    db.refresh(wl)
    return {"id": wl.id, "name": wl.name, "list_type": wl.list_type, "symbols": []}


def delete_watchlist(db: Session, user_id: int, watchlist_id: int) -> bool:
    wl = db.query(Watchlist).filter(
        Watchlist.id == watchlist_id,
        Watchlist.user_id == user_id,
    ).first()
    if not wl:
        return False
    db.delete(wl)
    db.commit()
    return True


def rename_watchlist(db: Session, user_id: int, watchlist_id: int, name: str) -> dict | None:
    wl = db.query(Watchlist).filter(
        Watchlist.id == watchlist_id,
        Watchlist.user_id == user_id,
    ).first()
    if not wl:
        return None
    wl.name = name
    db.commit()
    return {"id": wl.id, "name": wl.name}


def add_item(db: Session, user_id: int, watchlist_id: int,
             sym: str, name: str | None = None, note: str | None = None) -> bool:
    wl = db.query(Watchlist).filter(
        Watchlist.id == watchlist_id,
        Watchlist.user_id == user_id,
    ).first()
    if not wl:
        return False

    sym = sym.upper().replace(".NS", "").strip()

    # Try to resolve name from stock_master
    if not name:
        results = search_stocks(db, sym, limit=1)
        if results and results[0]["sym"] == sym:
            name = results[0]["name"]

    existing = db.query(WatchlistItem).filter(
        WatchlistItem.watchlist_id == watchlist_id,
        WatchlistItem.sym == sym,
    ).first()
    if existing:
        if note:
            existing.note = note
        db.commit()
        return True

    db.add(WatchlistItem(
        watchlist_id=watchlist_id,
        sym=sym,
        name=name or sym,
        note=note,
        added_at=datetime.now(timezone.utc),
    ))
    upsert_stock(db, sym, name or sym)
    db.commit()
    return True


def remove_item(db: Session, user_id: int, watchlist_id: int, sym: str) -> bool:
    sym = sym.upper().replace(".NS", "").strip()
    wl = db.query(Watchlist).filter(
        Watchlist.id == watchlist_id,
        Watchlist.user_id == user_id,
    ).first()
    if not wl:
        return False
    item = db.query(WatchlistItem).filter(
        WatchlistItem.watchlist_id == watchlist_id,
        WatchlistItem.sym == sym,
    ).first()
    if not item:
        return False
    db.delete(item)
    db.commit()
    return True


def get_all_symbols(db: Session, user_id: int) -> set[str]:
    wls = db.query(Watchlist).filter(Watchlist.user_id == user_id).all()
    return {item.sym for wl in wls for item in wl.items}
