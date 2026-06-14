"""
WebSocket endpoint: /ws/prices

Protocol:
  Client → Server (after connect):
    {"action": "subscribe",   "symbols": ["RELIANCE", "HDFCBANK"]}
    {"action": "unsubscribe", "symbols": ["RELIANCE"]}
    {"action": "ping"}

  Server → Client:
    {"type": "prices", "data": {"RELIANCE": {"ltp": 1234.5, "chg_pct": 0.5, "fetched_at": "..."}}}
    {"type": "pong"}
    {"type": "snapshot", "data": {...}}   # full PriceSnapshot rows on subscribe
"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

log = logging.getLogger(__name__)

router = APIRouter()


class PriceWsManager:
    def __init__(self) -> None:
        self._ws_syms: dict[int, set[str]] = {}        # ws id → subscribed syms
        self._sym_ws:  dict[str, set[int]] = {}        # sym → set of ws ids
        self._ws_ref:  dict[int, WebSocket] = {}       # ws id → websocket

    def _id(self, ws: WebSocket) -> int:
        return id(ws)

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        self._ws_syms[self._id(ws)] = set()
        self._ws_ref[self._id(ws)] = ws

    def disconnect(self, ws: WebSocket) -> None:
        wid = self._id(ws)
        for sym in self._ws_syms.pop(wid, set()):
            self._sym_ws.get(sym, set()).discard(wid)
        self._ws_ref.pop(wid, None)

    def subscribe(self, ws: WebSocket, syms: list[str]) -> None:
        wid = self._id(ws)
        for sym in syms:
            self._ws_syms[wid].add(sym)
            self._sym_ws.setdefault(sym, set()).add(wid)

    def unsubscribe(self, ws: WebSocket, syms: list[str]) -> None:
        wid = self._id(ws)
        for sym in syms:
            self._ws_syms[wid].discard(sym)
            self._sym_ws.get(sym, set()).discard(wid)

    async def broadcast(self, batch: dict[str, Any]) -> None:
        """
        batch: {sym: {ltp, chg_pct, fetched_at, ...}, ...}
        Each connected client receives only the symbols it subscribed to.
        """
        dead: list[int] = []
        notified: set[int] = set()

        for sym, payload in batch.items():
            for wid in list(self._sym_ws.get(sym, set())):
                if wid in notified:
                    continue
                ws = self._ws_ref.get(wid)
                if ws is None:
                    dead.append(wid)
                    continue
                # Build the subset of batch this client cares about
                client_syms = self._ws_syms.get(wid, set())
                msg_data = {s: batch[s] for s in client_syms if s in batch}
                if not msg_data:
                    continue
                try:
                    await ws.send_text(json.dumps({"type": "prices", "data": msg_data}))
                    notified.add(wid)
                except Exception as e:
                    log.debug("WS send failed wid=%s: %s", wid, e)
                    dead.append(wid)

        for wid in dead:
            ws = self._ws_ref.pop(wid, None)
            if ws:
                self.disconnect(ws)

    def active_count(self) -> int:
        return len(self._ws_ref)


_manager = PriceWsManager()


def get_ws_manager() -> PriceWsManager:
    return _manager


async def _send_snapshot(ws: WebSocket, syms: list[str]) -> None:
    """Push current PriceSnapshot rows to a newly-subscribed client."""
    if not syms:
        return
    try:
        from database import SessionLocal
        from models import PriceSnapshot
        db = SessionLocal()
        try:
            rows = db.query(PriceSnapshot).filter(PriceSnapshot.sym.in_(syms)).all()
            data = {
                r.sym: {
                    "ltp":        float(r.ltp)            if r.ltp            else None,
                    "chg_pct":    float(r.day_change_pct) if r.day_change_pct else None,
                    "prev_close": float(r.prev_close)     if r.prev_close     else None,
                    "fetched_at": r.fetched_at.isoformat() if r.fetched_at   else None,
                }
                for r in rows
            }
        finally:
            db.close()
        if data:
            await ws.send_text(json.dumps({"type": "snapshot", "data": data}))
    except Exception:
        log.exception("_send_snapshot failed")


@router.websocket("/ws/prices")
async def ws_prices(ws: WebSocket) -> None:
    await _manager.connect(ws)
    log.info("WS /ws/prices connected (active=%d)", _manager.active_count())
    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue

            action = msg.get("action", "")
            if action == "subscribe":
                syms = [str(s).upper().replace(".NS", "") for s in msg.get("symbols", [])]
                _manager.subscribe(ws, syms)
                await _send_snapshot(ws, syms)
            elif action == "unsubscribe":
                syms = [str(s).upper().replace(".NS", "") for s in msg.get("symbols", [])]
                _manager.unsubscribe(ws, syms)
            elif action == "ping":
                await ws.send_text('{"type":"pong"}')
    except WebSocketDisconnect:
        pass
    except Exception:
        log.exception("ws_prices error")
    finally:
        _manager.disconnect(ws)
        log.info("WS /ws/prices disconnected (active=%d)", _manager.active_count())
