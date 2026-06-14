"""
IBD-style Relative Strength universe computation for Nifty 500.

RS score = 0.4*ret_3M + 0.2*ret_6M + 0.2*ret_9M + 0.2*ret_12M
Percentile-ranked across all 500 stocks.

Cached on disk for 24h — expensive to compute (500 tickers).
"""
from __future__ import annotations
import logging
import json
import time
from pathlib import Path

import pandas as pd

from shared.cache import cache_get, cache_set
from shared.yfinance_client import get_bulk_daily
from shared.tickers import nse

log = logging.getLogger(__name__)

_CACHE_KEY = "rs_universe_n500"
_TTL       = 86400  # 24h


def _pct_return(series: pd.Series, days: int) -> float:
    if len(series) < days:
        return 0.0
    start = series.iloc[-days]
    end   = series.iloc[-1]
    if start == 0:
        return 0.0
    return (end - start) / start * 100


def compute_universe(symbols: list[str]) -> dict[str, float]:
    """
    Download 1Y daily data for all symbols, compute IBD-weighted RS score,
    return {symbol: percentile_rank_0_to_100}.

    Args:
        symbols: list of NSE symbols WITHOUT .NS suffix
    """
    cached = cache_get(_CACHE_KEY, _TTL)
    if cached:
        return cached

    nse_syms = [nse(s) for s in symbols]
    log.info("Computing RS universe for %d symbols", len(nse_syms))

    bulk = get_bulk_daily(nse_syms, period="1y")
    if not bulk:
        log.error("RS universe: no data returned from bulk download")
        return {}

    raw_scores: dict[str, float] = {}
    for sym_ns, df in bulk.items():
        close = df["Close"].dropna() if "Close" in df.columns else pd.Series()
        if len(close) < 63:  # need at least 3 months
            continue
        sym = sym_ns.replace(".NS", "")
        r3m  = _pct_return(close, 63)
        r6m  = _pct_return(close, 126)
        r9m  = _pct_return(close, 189)
        r12m = _pct_return(close, 252)
        raw_scores[sym] = 0.4*r3m + 0.2*r6m + 0.2*r9m + 0.2*r12m

    if not raw_scores:
        return {}

    series = pd.Series(raw_scores)
    # percentile rank: value's rank / count * 100
    pct_ranks = series.rank(pct=True) * 100
    result = {sym: round(float(rank), 1) for sym, rank in pct_ranks.items()}

    cache_set(_CACHE_KEY, result)
    return result


def get_rs_universe() -> dict[str, float]:
    """Return cached RS universe dict (empty if not yet computed)."""
    cached = cache_get(_CACHE_KEY, _TTL)
    return cached if cached else {}


def get_rs_pct(symbol: str, universe: dict[str, float] | None = None) -> float | None:
    """
    Get RS percentile rank for a single symbol.
    If universe dict is provided (from a pre-computed batch), looks it up directly.
    Otherwise loads from cache or returns None.
    """
    sym = symbol.replace(".NS", "")
    if universe is not None:
        return universe.get(sym)

    cached = cache_get(_CACHE_KEY, _TTL)
    if cached:
        return cached.get(sym)

    return None
