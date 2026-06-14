"""
USD/INR rate — single source of truth.

The nightly job (`jobs.market_data.job_refresh_fx`) caches `fx_usdinr` once a day, but on a
cold cache (job not yet run, or TTL lapsed) callers were hard-coding ₹84. This fetches live on a
cache miss so the rate stays current, only falling back to 84 if the network fetch also fails.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)

_FALLBACK = 84.0


def get_fx_rate() -> float:
    from shared.cache import cache_get, cache_set
    cached = cache_get("fx_usdinr", ttl_seconds=86400)
    if cached and cached.get("rate"):
        return float(cached["rate"])

    # Cold cache — fetch live and store for the next caller.
    try:
        import yfinance as yf
        raw = yf.download("USDINR=X", period="2d", auto_adjust=True, progress=False)
        col = raw["Close"].dropna() if raw is not None and not raw.empty else None
        if col is not None and not col.empty:
            rate = round(float(col.iloc[-1]), 4)
            cache_set("fx_usdinr", {"rate": rate}, ttl_seconds=86400)
            log.info("FX USD/INR fetched live: %.4f", rate)
            return rate
    except Exception as e:
        log.warning("live FX fetch failed: %s", e)
    return _FALLBACK
