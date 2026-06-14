"""
data_source.py — Pluggable market-data registry for the Charts module.

Each source registers two callables:
  history_fn(symbol, timeframe) -> list[CandleDict]
  quote_fn(symbol)              -> QuoteDict

CandleDict = {"time": unix_seconds_int, "open": float, "high": float,
              "low": float, "close": float, "volume": float}
QuoteDict  = {"symbol": str, "price": float|None, "source": str}

To add a new source (e.g. Alpaca):
    from my_alpaca_adapter import alpaca_history, alpaca_quote
    _HISTORY_REGISTRY["alpaca"] = alpaca_history
    _QUOTE_REGISTRY["alpaca"]   = alpaca_quote
"""

import time as _time
import logging
import warnings
warnings.filterwarnings("ignore", category=FutureWarning, module="yfinance")

_log = logging.getLogger(__name__)

# ── Timeframe maps ────────────────────────────────────────────────────────────

_YF_INTERVAL_MAP = {
    "1m":  ("1m",   "1d"),
    "5m":  ("5m",   "5d"),
    "15m": ("15m",  "5d"),
    "30m": ("30m",  "1mo"),
    "1h":  ("60m",  "1mo"),
    "4h":  ("1h",   "3mo"),   # yfinance has no 4h; use 1h data for 3 months
    "1d":  ("1d",   "1y"),
    "1w":  ("1wk",  "5y"),
}

_HL_INTERVAL_MAP = {
    "1m": "1m", "3m": "3m", "5m": "5m", "15m": "15m",
    "30m": "30m", "1h": "1h", "4h": "4h", "1d": "1d",
}

_HL_LOOKBACK_MS = {
    "1m":  8   * 60 * 60 * 1000,
    "3m":  24  * 60 * 60 * 1000,
    "5m":  2   * 24 * 60 * 60 * 1000,
    "15m": 7   * 24 * 60 * 60 * 1000,
    "30m": 14  * 24 * 60 * 60 * 1000,
    "1h":  30  * 24 * 60 * 60 * 1000,
    "4h":  90  * 24 * 60 * 60 * 1000,
    "1d":  365 * 24 * 60 * 60 * 1000,
}

_DAILY_INTERVALS = {"1d", "1wk"}


def _to_unix_daily(ts) -> int:
    """Convert a date/Timestamp to UTC midnight unix seconds to avoid IST offset issues."""
    from datetime import datetime, timezone
    d = ts.date() if hasattr(ts, "date") and callable(ts.date) else ts
    return int(datetime(d.year, d.month, d.day, tzinfo=timezone.utc).timestamp())


# ── yfinance ─────────────────────────────────────────────────────────────────

def _yfinance_history(symbol: str, timeframe: str) -> list[dict]:
    import yfinance as yf
    import pandas as pd

    interval, period = _YF_INTERVAL_MAP.get(timeframe, ("1d", "1y"))
    is_daily = interval in _DAILY_INTERVALS

    try:
        df = yf.download(
            symbol, period=period, interval=interval,
            auto_adjust=True, progress=False, timeout=30,
        )
        if df is None or df.empty:
            return []

        # yfinance 1.3+ wraps single-ticker downloads in a MultiIndex
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = [col[0] for col in df.columns]

        df = df.reset_index()
        # yfinance 1.3+ with MultiIndex: after column flatten, the date index
        # loses its name and reset_index() creates an 'index' column
        if "index" in df.columns and "Date" not in df.columns and "Datetime" not in df.columns:
            df = df.rename(columns={"index": "Date"})
        time_col = "Datetime" if "Datetime" in df.columns else "Date"

        result = []
        for _, row in df.iterrows():
            try:
                o = float(row["Open"])
                h = float(row["High"])
                l = float(row["Low"])
                c = float(row["Close"])
                v = float(row.get("Volume", 0) or 0)
                if pd.isna(o) or pd.isna(c):
                    continue
                ts = row[time_col]
                unix = _to_unix_daily(ts) if is_daily else int(ts.timestamp())
                result.append({
                    "time":   unix,
                    "open":   round(o, 4),
                    "high":   round(h, 4),
                    "low":    round(l, 4),
                    "close":  round(c, 4),
                    "volume": round(v, 2),
                })
            except (KeyError, ValueError, TypeError, AttributeError):
                continue
        return result
    except Exception as e:
        _log.warning("yfinance_history %s %s: %s", symbol, timeframe, e)
        return []


def _yfinance_quote(symbol: str) -> dict:
    import yfinance as yf
    try:
        ticker = yf.Ticker(symbol)
        price = None
        try:
            price = float(ticker.fast_info["last_price"])
        except Exception:
            hist = ticker.history(period="2d", auto_adjust=True)
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
        return {"symbol": symbol, "price": price, "source": "yfinance"}
    except Exception as e:
        _log.warning("yfinance_quote %s: %s", symbol, e)
        return {"symbol": symbol, "price": None, "source": "yfinance"}


# ── Hyperliquid ───────────────────────────────────────────────────────────────

def _hyperliquid_history(symbol: str, timeframe: str) -> list[dict]:
    import requests

    interval = _HL_INTERVAL_MAP.get(timeframe, "1h")
    end_ms   = int(_time.time() * 1000)
    start_ms = end_ms - _HL_LOOKBACK_MS.get(interval, 30 * 24 * 60 * 60 * 1000)

    payload = {
        "type": "candleSnapshot",
        "req": {
            "coin":      symbol,
            "interval":  interval,
            "startTime": start_ms,
            "endTime":   end_ms,
        },
    }
    try:
        resp = requests.post(
            "https://api.hyperliquid.xyz/info", json=payload, timeout=15
        )
        resp.raise_for_status()
        raw = resp.json()
        result = []
        for candle in raw:
            try:
                if isinstance(candle, dict):
                    # t = open time ms, T = close time ms
                    t = int(candle.get("t", candle.get("T", 0))) // 1000
                    o = float(candle.get("o", 0))
                    h = float(candle.get("h", 0))
                    l = float(candle.get("l", 0))
                    c = float(candle.get("c", 0))
                    v = float(candle.get("v", 0))
                elif isinstance(candle, (list, tuple)) and len(candle) >= 6:
                    t = int(candle[0]) // 1000
                    o, h, l, c, v = (float(candle[i]) for i in range(1, 6))
                else:
                    continue
                result.append({"time": t, "open": o, "high": h,
                                "low": l, "close": c, "volume": v})
            except (KeyError, ValueError, TypeError, IndexError):
                continue
        return sorted(result, key=lambda x: x["time"])
    except Exception as e:
        _log.warning("hl_history %s %s: %s", symbol, timeframe, e)
        return []


def _hyperliquid_quote(symbol: str) -> dict:
    import requests
    try:
        resp = requests.post(
            "https://api.hyperliquid.xyz/info",
            json={"type": "allMids"},
            timeout=10,
        )
        resp.raise_for_status()
        mids = resp.json()
        price = float(mids[symbol]) if symbol in mids else None
        return {"symbol": symbol, "price": price, "source": "hyperliquid"}
    except Exception as e:
        _log.warning("hl_quote %s: %s", symbol, e)
        return {"symbol": symbol, "price": None, "source": "hyperliquid"}


# ── Registry & dispatch ───────────────────────────────────────────────────────

_HISTORY_REGISTRY: dict = {
    "yfinance":    _yfinance_history,
    "hyperliquid": _hyperliquid_history,
}

_QUOTE_REGISTRY: dict = {
    "yfinance":    _yfinance_quote,
    "hyperliquid": _hyperliquid_quote,
}


def get_history(symbol: str, timeframe: str, source: str) -> list[dict]:
    """Dispatch to the registered history function for the given source."""
    fn = _HISTORY_REGISTRY.get(source)
    return fn(symbol, timeframe) if fn else []


def get_live_price(symbol: str, source: str) -> dict:
    """Dispatch to the registered quote function for the given source."""
    fn = _QUOTE_REGISTRY.get(source)
    return fn(symbol) if fn else {"symbol": symbol, "price": None, "source": source}


def list_sources() -> list[str]:
    return sorted(_HISTORY_REGISTRY.keys())


def get_namemap() -> dict[str, str]:
    """Return {NSE_base_symbol: company_name} from nifty500.csv."""
    from pathlib import Path
    import pandas as pd
    csv = Path(__file__).parent.parent.parent / "data" / "nifty500.csv"
    if not csv.exists():
        return {}
    df = pd.read_csv(csv).dropna(subset=["symbol"])
    return {str(r["symbol"]): str(r.get("name", r["symbol"])) for _, r in df.iterrows()}


def get_stock_info(symbol: str) -> dict:
    """Return fundamental info for a symbol (fast — uses CSV + yfinance fast_info)."""
    import yfinance as yf
    from pathlib import Path
    import pandas as pd

    csv = Path(__file__).parent.parent.parent / "data" / "nifty500.csv"
    meta: dict = {}
    if csv.exists():
        df = pd.read_csv(csv).dropna(subset=["symbol"])
        for _, row in df.iterrows():
            meta[str(row["symbol"])] = {
                "name": str(row.get("name", row["symbol"])),
                "sector": str(row.get("sector", "")),
                "mcap_cr": float(row.get("mcap_cr", 0) or 0),
            }

    base = symbol.replace(".NS", "").replace("^", "").upper()
    m = meta.get(base, {})

    result: dict = {
        "symbol": symbol,
        "name": m.get("name") or base,
        "sector": m.get("sector") or "",
        "mcap_cr": m.get("mcap_cr") or 0,
        "price": None,
        "change_pct": None,
        "fifty_two_week_high": None,
        "fifty_two_week_low": None,
    }

    def _f(x):
        try:
            v = float(x)
            return None if v != v else v  # NaN guard
        except Exception:
            return None

    try:
        fi = yf.Ticker(symbol).fast_info
        result["price"] = _f(fi.get("lastPrice"))
        result["fifty_two_week_high"] = _f(fi.get("yearHigh"))
        result["fifty_two_week_low"] = _f(fi.get("yearLow"))
        prev = _f(fi.get("previousClose") or fi.get("regularMarketPreviousClose"))
        if result["price"] and prev:
            result["change_pct"] = round((result["price"] - prev) / prev * 100, 2)
        if not result["mcap_cr"]:
            mc = _f(fi.get("marketCap"))
            if mc:
                result["mcap_cr"] = round(mc / 1e7, 0)
    except Exception as e:
        _log.warning("get_stock_info %s: %s", symbol, e)

    return result
