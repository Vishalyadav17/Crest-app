"""
Market overview: indices snapshot + A/D ratio + breakout signal.
Cached 15 min (live quote cadence).
"""
from __future__ import annotations
import logging
import requests
import pandas as pd
import yfinance as yf
from shared.cache import cache_get, cache_set
from shared.tickers import (
    INDEX_NIFTY50, INDEX_BANKNIFTY, INDEX_NIFTY500,
    SECTOR_TICKERS,
)

log = logging.getLogger(__name__)

_TTL = 900  # 15 min
_USDINR = "USDINR=X"

_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/",
}

_INDEX_META = {
    INDEX_NIFTY50:   {"label": "NIFTY 50",     "short": "N50"},
    INDEX_BANKNIFTY: {"label": "BANK NIFTY",   "short": "BNIFTY"},
    _USDINR:         {"label": "USD/INR",       "short": "USDINR"},
}

# Indices fetched from NSE allIndices (no reliable Yahoo Finance history)
_NSE_ONLY_INDICES = {
    "NIFTY MIDCAP 100":   {"label": "MIDCAP 100",   "short": "MIDCAP100"},
    "NIFTY SMALLCAP 100": {"label": "SMALLCAP 100", "short": "SC100"},
}


def _ema(series: pd.Series, span: int) -> float:
    return float(series.ewm(span=span, adjust=False).mean().iloc[-1])


def _fetch_index(sym: str) -> dict | None:
    try:
        df = yf.download(sym, period="1y", interval="1d",
                         auto_adjust=True, progress=False, timeout=30)
        if df is None or df.empty:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [c[0] for c in df.columns]
        close = df["Close"].dropna()
        if len(close) < 2:
            return None

        price = float(close.iloc[-1])
        prev  = float(close.iloc[-2])
        chg   = price - prev
        chg_pct = (chg / prev * 100) if prev else 0.0

        ema20 = _ema(close, 20)
        result = {
            "price":      round(price, 2),
            "change":     round(chg, 2),
            "chg_pct":    round(chg_pct, 2),
            "ema50":      round(ema20, 2),   # field kept as ema50 for API compat; value is 20EMA
            "above_ema50": price > ema20,
        }
        if len(close) >= 252:
            result["high52w"] = round(float(close.tail(252).max()), 2)
            result["low52w"]  = round(float(close.tail(252).min()), 2)
        return result
    except Exception as e:
        log.warning("index fetch failed %s: %s", sym, e)
        return None


def _fetch_nse_only_indices() -> dict:
    """Fetch indices that have no usable Yahoo Finance history from NSE allIndices."""
    out: dict = {}
    try:
        s = requests.Session()
        s.get("https://www.nseindia.com", headers=_NSE_HEADERS, timeout=10)
        r = s.get("https://www.nseindia.com/api/allIndices", headers=_NSE_HEADERS, timeout=10)
        r.raise_for_status()
        for item in r.json().get("data", []):
            meta = _NSE_ONLY_INDICES.get(item.get("index"))
            if not meta:
                continue
            price = float(item["last"])
            prev  = float(item["previousClose"])
            out[meta["short"]] = {
                **meta,
                "price":       round(price, 2),
                "change":      round(price - prev, 2),
                "chg_pct":     round(float(item["percentChange"]), 2),
                "ema50":       None,
                "above_ema50": None,
            }
    except Exception as e:
        log.warning("NSE allIndices fetch failed: %s", e)
    return out


def get_indices() -> dict:
    key = "market_overview|indices"
    cached = cache_get(key, _TTL)
    if cached:
        return cached

    result = {}
    for sym, meta in _INDEX_META.items():
        data = _fetch_index(sym)
        if data:
            result[meta["short"]] = {**meta, **data, "symbol": sym}

    # MIDCAP100 + SC100 via NSE allIndices (no reliable Yahoo Finance history)
    result.update(_fetch_nse_only_indices())

    # Breakout signal: are most sector indices above 50 EMA?
    sector_above = 0
    sector_total = 0
    for name, tsym in list(SECTOR_TICKERS.items())[:8]:  # sample 8 for speed
        try:
            df = yf.download(tsym, period="3mo", interval="1d",
                             auto_adjust=True, progress=False, timeout=20)
            if df is not None and not df.empty:
                if isinstance(df.columns, pd.MultiIndex):
                    df.columns = [c[0] for c in df.columns]
                close = df["Close"].dropna()
                if len(close) >= 50:
                    sector_total += 1
                    if float(close.iloc[-1]) > _ema(close, 50):
                        sector_above += 1
        except (OSError, ValueError, KeyError) as e:
            log.warning("sector signal fetch failed %s (%s): %s", name, tsym, e)

    breakout_score = sector_above / sector_total if sector_total else 0
    result["market_signal"] = {
        "sectors_above_ema50": sector_above,
        "sectors_checked": sector_total,
        "breakout_likely": breakout_score >= 0.6,
        "signal": "BULLISH" if breakout_score >= 0.6 else ("NEUTRAL" if breakout_score >= 0.4 else "CAUTION"),
    }

    cache_set(key, result)
    return result


def get_ad_ratio() -> dict:
    """
    Approximate A/D using Nifty 50 constituents via yfinance.
    Returns {advances, declines, unchanged, ratio, above_50ema}.
    Cached 15 min.
    """
    key = "market_overview|ad_ratio"
    cached = cache_get(key, _TTL)
    if cached:
        return cached

    # Use a fixed basket of 30 liquid large-caps as proxy for A/D
    basket = [
        "RELIANCE.NS","TCS.NS","HDFCBANK.NS","INFY.NS","ICICIBANK.NS",
        "HINDUNILVR.NS","LT.NS","ITC.NS","BAJFINANCE.NS","HCLTECH.NS",
        "AXISBANK.NS","MARUTI.NS","NTPC.NS","SUNPHARMA.NS","WIPRO.NS",
        "TITAN.NS","POWERGRID.NS","TMPV.NS","M&M.NS","NESTLEIND.NS",
        "TECHM.NS","HINDALCO.NS","TATASTEEL.NS","ONGC.NS","BPCL.NS",
        "JSWSTEEL.NS","ASIANPAINT.NS","DIVISLAB.NS","DRREDDY.NS","CIPLA.NS",
    ]
    advances = declines = unchanged = above_50ema = 0
    try:
        raw = yf.download(basket, period="5d", interval="1d",
                          auto_adjust=True, progress=False, timeout=45)
        if raw is not None and not raw.empty:
            if isinstance(raw.columns, pd.MultiIndex):
                for sym in basket:
                    try:
                        close = raw["Close"][sym].dropna()
                        if len(close) >= 2:
                            chg = close.iloc[-1] - close.iloc[-2]
                            if chg > 0: advances += 1
                            elif chg < 0: declines += 1
                            else: unchanged += 1
                    except (KeyError, IndexError, TypeError):
                        pass
    except Exception as e:
        log.warning("A/D fetch failed: %s", e)

    total = advances + declines + unchanged or 1
    result = {
        "advances": advances,
        "declines": declines,
        "unchanged": unchanged,
        "ratio": round(advances / (declines or 1), 2),
        "breadth_pct": round(advances / total * 100, 1),
    }
    cache_set(key, result)
    return result
