"""
Watchlist CRUD API.
Replaces localStorage gp_watchlists.
"""
from __future__ import annotations
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth import is_authenticated
from database import get_db
from deps import get_current_user_id
from crud.watchlist import (
    get_watchlists, create_watchlist, delete_watchlist, rename_watchlist,
    add_item, remove_item,
)

router = APIRouter(prefix="/api/watchlists", tags=["watchlists"])


def _auth(request: Request):
    if not is_authenticated(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return None


class WatchlistCreate(BaseModel):
    name: str
    list_type: str = "custom"


class WatchlistRename(BaseModel):
    name: str


class ItemAdd(BaseModel):
    sym: str
    note: str | None = None


@router.get("")
async def list_watchlists(request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    return get_watchlists(db, user_id)


@router.post("")
async def create(request: Request, body: WatchlistCreate, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    return create_watchlist(db, user_id, body.name, body.list_type)


@router.patch("/{watchlist_id}")
async def rename(watchlist_id: int, request: Request, body: WatchlistRename,
                 db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    result = rename_watchlist(db, user_id, watchlist_id, body.name)
    if not result:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return result


@router.delete("/{watchlist_id}")
async def delete(watchlist_id: int, request: Request, db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    if not delete_watchlist(db, user_id, watchlist_id):
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return {"ok": True}


@router.post("/{watchlist_id}/items")
async def add(watchlist_id: int, request: Request, body: ItemAdd,
              db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    if not add_item(db, user_id, watchlist_id, body.sym, note=body.note):
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return {"ok": True}


@router.delete("/{watchlist_id}/items/{sym}")
async def remove(watchlist_id: int, sym: str, request: Request,
                 db: Session = Depends(get_db)):
    err = _auth(request)
    if err:
        return err
    user_id = get_current_user_id(request, db)
    if not remove_item(db, user_id, watchlist_id, sym):
        raise HTTPException(status_code=404, detail="Item not found")
    return {"ok": True}
