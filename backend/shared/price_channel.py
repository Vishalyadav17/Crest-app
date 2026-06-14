"""
Thread-safe bridge between the APScheduler price-snapshot writer (runs in a thread)
and the async WebSocket broadcaster (runs on the event loop).

Usage in scheduler:
    from shared.price_channel import enqueue_price_update
    enqueue_price_update({"RELIANCE": {"ltp": 1234.5, "chg_pct": 0.5}})

Usage in WS routes:
    from shared.price_channel import price_queue
    while True:
        batch = await price_queue.get()
        ...
"""
from __future__ import annotations

import asyncio
import logging

log = logging.getLogger(__name__)

price_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=256)

_loop: asyncio.AbstractEventLoop | None = None


def set_event_loop(loop: asyncio.AbstractEventLoop) -> None:
    global _loop
    _loop = loop


def enqueue_price_update(batch: dict) -> None:
    """Called from any thread (scheduler). Puts batch on the async queue."""
    if _loop is None or _loop.is_closed():
        return
    try:
        _loop.call_soon_threadsafe(price_queue.put_nowait, batch)
    except asyncio.QueueFull:
        log.debug("price_queue full — dropping batch")
    except Exception:
        log.exception("enqueue_price_update failed")
