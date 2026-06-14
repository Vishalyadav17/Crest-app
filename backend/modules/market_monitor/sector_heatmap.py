"""
Sector heatmap: NSE sector indices with 1-day change, 52W proximity, EMA momentum.
12 sectors via yfinance (full EMA history). 3 sectors via NSE allIndices API (no EMA).
Each sector response includes its constituent stock symbols (from sectors.json).
Cached 15 min.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
import requests
import pandas as pd
import yfinance as yf
from shared.cache import cache_get, cache_set
from shared.tickers import SECTOR_TICKERS, NSE_ONLY_SECTORS

_DATA_DIR = Path(__file__).parent.parent.parent / "data"

log = logging.getLogger(__name__)
_TTL = 900

_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/",
}


def _ema(series: pd.Series, span: int) -> float:
    return float(series.ewm(span=span, adjust=False).mean().iloc[-1])


def _fetch_sector(name: str, sym: str) -> dict | None:
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
        chg_pct = (price - prev) / prev * 100 if prev else 0.0

        window = min(252, len(close))
        high52w = float(close.tail(window).max())
        pct_from_high = (high52w - price) / high52w * 100 if high52w else 0

        ema20  = _ema(close, 20)  if len(close) >= 20  else None
        ema50  = _ema(close, 50)  if len(close) >= 50  else None
        ema200 = _ema(close, 200) if len(close) >= 200 else None

        in_momentum = bool(
            ema20 and ema50 and ema200
            and price > ema20 > ema50 > ema200
            and pct_from_high <= 20
        )

        return {
            "name": name, "symbol": sym,
            "price": round(price, 2),
            "chg_pct": round(chg_pct, 2),
            "high52w": round(high52w, 2),
            "pct_from_high": round(pct_from_high, 1),
            "in_momentum": in_momentum,
            "ema20":  round(ema20, 2)  if ema20  else None,
            "ema50":  round(ema50, 2)  if ema50  else None,
            "ema200": round(ema200, 2) if ema200 else None,
        }
    except Exception as e:
        log.warning("sector fetch failed %s (%s): %s", name, sym, e)
        return None


def _fetch_nse_only_sectors(names: dict[str, str]) -> list[dict]:
    """
    Fetch OIL_GAS / CONSR_DURBL / HEALTHCARE from NSE allIndices API.
    Returns partial sector dicts: price, chg_pct, pct_from_high, in_momentum=False.
    """
    try:
        s = requests.Session()
        s.get("https://www.nseindia.com", headers=_NSE_HEADERS, timeout=10)
        r = s.get("https://www.nseindia.com/api/allIndices",
                  headers=_NSE_HEADERS, timeout=10)
        r.raise_for_status()
        all_indices = {item["index"]: item for item in r.json().get("data", [])}
    except Exception as e:
        log.warning("NSE allIndices fetch failed: %s", e)
        return []

    results = []
    for sector_name, nse_name in names.items():
        item = all_indices.get(nse_name)
        if not item:
            log.warning("NSE index not found: %s", nse_name)
            continue
        try:
            price     = float(item["last"])
            prev      = float(item["previousClose"])
            chg_pct   = float(item["percentChange"])
            year_high = float(item.get("yearHigh", price))
            pct_from_high = (year_high - price) / year_high * 100 if year_high else 0
            results.append({
                "name": sector_name,
                "symbol": nse_name,
                "price": round(price, 2),
                "chg_pct": round(chg_pct, 2),
                "high52w": round(year_high, 2),
                "pct_from_high": round(pct_from_high, 1),
                "in_momentum": False,   # no EMA history available
                "ema20": None, "ema50": None, "ema200": None,
            })
        except Exception as e:
            log.warning("NSE sector parse failed %s: %s", sector_name, e)

    return results


def _load_sector_stocks() -> dict[str, list[str]]:
    path = _DATA_DIR / "sectors.json"
    if not path.exists():
        return {}
    try:
        with open(path) as f:
            return json.load(f)
    except (OSError, ValueError) as e:
        log.error("sectors.json load failed: %s", e)
        return {}


def get_sector_heatmap() -> dict:
    key = "sector_heatmap"
    cached = cache_get(key, _TTL)
    if cached:
        return cached

    sector_stocks = _load_sector_stocks()
    sectors = []

    # 12 sectors with full yfinance history
    for name, sym in SECTOR_TICKERS.items():
        data = _fetch_sector(name, sym)
        if data:
            data["stocks"] = sector_stocks.get(name, [])
            sectors.append(data)

    # 3 sectors via NSE API (no EMA history on Yahoo Finance)
    for data in _fetch_nse_only_sectors(NSE_ONLY_SECTORS):
        data["stocks"] = sector_stocks.get(data["name"], [])
        sectors.append(data)

    sectors.sort(key=lambda x: x["chg_pct"], reverse=True)
    momentum_count = sum(1 for s in sectors if s["in_momentum"])

    result = {
        "sectors": sectors,
        "momentum_count": momentum_count,
        "total": len(sectors),
    }
    cache_set(key, result)
    return result
