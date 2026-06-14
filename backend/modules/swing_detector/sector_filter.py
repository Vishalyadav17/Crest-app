"""
Pass 1 — Sector momentum gate.
A sector qualifies if:
  price > EMA20 > EMA50 > EMA200 (all ascending, strict)
  price >= 52W_high × 0.80  (within 20% of 52W high)
  EMA200 slope is rising     (EMA200 today > EMA200 one month ago)

Returns list of qualifying sector names and their constituent stock symbols.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
import pandas as pd
import yfinance as yf
from shared.tickers import SECTOR_TICKERS

log = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _qualifies(close: pd.Series) -> bool:
    if len(close) < 210:
        return False
    price  = float(close.iloc[-1])
    ema20  = float(_ema(close, 20).iloc[-1])
    ema50  = float(_ema(close, 50).iloc[-1])
    ema200 = float(_ema(close, 200).iloc[-1])
    ema200_prev = float(_ema(close, 200).iloc[-21])  # ~1 month ago

    high52w = float(close.tail(min(252, len(close))).max())
    within_20pct_high = price >= high52w * 0.80

    return (
        price > ema20 > ema50 > ema200
        and ema200 > ema200_prev
        and within_20pct_high
    )


def _load_sector_stocks() -> dict[str, list[str]]:
    path = _DATA_DIR / "sectors.json"
    if not path.exists():
        log.warning("sectors.json not found at %s", path)
        return {}
    with open(path) as f:
        return json.load(f)


def get_qualifying_sectors() -> dict:
    """
    Returns:
        {
          "qualifying": [{"name": str, "stocks": [str], "pct_from_high": float}],
          "all_sectors": [{"name": str, "qualified": bool, "pct_from_high": float}],
          "count": int,
        }
    """
    sector_stocks = _load_sector_stocks()
    qualifying = []
    all_sectors = []

    for sector_name, sym in SECTOR_TICKERS.items():
        try:
            df = yf.download(sym, period="1y", interval="1d",
                             auto_adjust=True, progress=False, timeout=30)
            if df is None or df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [c[0] for c in df.columns]
            close = df["Close"].dropna()

            price = float(close.iloc[-1])
            window = min(252, len(close))
            high52w = float(close.tail(window).max())
            pct_from_high = round((high52w - price) / high52w * 100, 1) if high52w else 0

            qualified = _qualifies(close)
            all_sectors.append({
                "name": sector_name,
                "symbol": sym,
                "qualified": qualified,
                "pct_from_high": pct_from_high,
                "price": round(price, 2),
            })
            if qualified:
                stocks = sector_stocks.get(sector_name, [])
                qualifying.append({
                    "name": sector_name,
                    "symbol": sym,
                    "stocks": stocks,
                    "pct_from_high": pct_from_high,
                })
                log.info("Sector QUALIFIES: %s (%.1f%% from 52W high)", sector_name, pct_from_high)
            else:
                log.debug("Sector filtered: %s (%.1f%% from 52W high)", sector_name, pct_from_high)
        except Exception as e:
            log.warning("sector fetch error %s: %s", sector_name, e)

    return {
        "qualifying": qualifying,
        "all_sectors": all_sectors,
        "count": len(qualifying),
        "total": len(all_sectors),
    }
