"""
Earnings calendar — next earnings date lookup via yfinance.

Called only for ~40 finalists after composite ranking (not the 1300-universe).
Cached per symbol in market_cache with 3-day TTL per [[reference_yfinance]].
"""
from __future__ import annotations

import logging
from datetime import datetime, date, timezone, timedelta

log = logging.getLogger(__name__)

_TTL_SECONDS = 3 * 86400  # 3 days
_MARKET_SESSIONS_PER_WEEK = 5


def _cache_key(sym: str) -> str:
    return f"earnings|{sym}"


def get_next_earnings(sym: str, db=None, ttl_days: int = 3) -> date | None:
    """
    Return the next earnings date for `sym` (NSE symbol, no .NS suffix needed).
    Returns None if unknown or lookup fails.

    Uses market_cache for memoisation (ttl = 3 days).
    """
    from shared.cache import cache_get, cache_set
    key = _cache_key(sym)
    cached = cache_get(key, _TTL_SECONDS)
    if cached is not None:
        raw = cached.get("next_earnings")
        if raw:
            try:
                return date.fromisoformat(raw)
            except Exception:
                pass
        return None

    result: date | None = None
    try:
        import yfinance as yf
        ticker = yf.Ticker(f"{sym}.NS")
        df = ticker.get_earnings_dates(limit=4)
        if df is not None and not df.empty:
            today = date.today()
            for idx in df.index:
                try:
                    ed = idx.date() if hasattr(idx, "date") else date.fromisoformat(str(idx)[:10])
                    if ed >= today:
                        result = ed
                        break
                except Exception:
                    continue
    except Exception as e:
        log.warning("earnings_calendar %s: %s", sym, e)

    cache_set(key, {"next_earnings": result.isoformat() if result else None}, _TTL_SECONDS)
    return result


def sessions_until_earnings(next_date: date | None) -> int | None:
    """
    Approximate trading sessions until `next_date` (weekdays only, ignores holidays).
    Returns None if next_date is None.
    """
    if next_date is None:
        return None
    today = date.today()
    if next_date <= today:
        return 0
    days = 0
    sessions = 0
    cursor = today
    while cursor < next_date:
        cursor += timedelta(days=1)
        days += 1
        if cursor.weekday() < 5:  # Mon–Fri
            sessions += 1
    return sessions
