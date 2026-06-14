"""
Top gainers and losers from the Nifty 500 universe.
Primary: NSE equity-stockIndices API (live during market hours).
Fallback: yfinance 5d download (EOD data).
Cached 5 min.
"""
from __future__ import annotations
import logging
from datetime import datetime
from pathlib import Path
import pandas as pd
import requests
from shared.cache import cache_get, cache_set
from shared.yfinance_client import get_bulk_daily

log = logging.getLogger(__name__)

_TTL = 300   # 5 min — NSE is live
_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_TOP_N = 10
_MAX_STOCKS = 200

_NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
    "Referer": "https://www.nseindia.com/",
}


def _load_meta() -> dict[str, dict]:
    csv = _DATA_DIR / "nifty500.csv"
    if not csv.exists():
        return {}
    df = pd.read_csv(csv).dropna(subset=["symbol"])
    return {
        row["symbol"]: {
            "name": row.get("name", row["symbol"]),
            "sector": row.get("sector", ""),
            "mcap_cr": float(row.get("mcap_cr", 0)),
        }
        for _, row in df.iterrows()
    }


def _load_universe() -> list[str]:
    csv = _DATA_DIR / "nifty500.csv"
    if not csv.exists():
        return []
    df = pd.read_csv(csv).dropna(subset=["symbol", "mcap_cr"])
    df = df.sort_values("mcap_cr", ascending=False).head(_MAX_STOCKS)
    syms = df["symbol"].drop_duplicates().tolist()
    return [s + ".NS" for s in syms if not s.endswith(".NS")]


def _from_nse(n: int) -> dict | None:
    """Fetch live gainers/losers from NSE live-analysis-variations (allSec)."""
    try:
        s = requests.Session()
        s.get("https://www.nseindia.com", headers=_NSE_HEADERS, timeout=10)
        rg = s.get(
            "https://www.nseindia.com/api/live-analysis-variations?index=gainers",
            headers=_NSE_HEADERS, timeout=15,
        )
        rg.raise_for_status()
        rl = s.get(
            "https://www.nseindia.com/api/live-analysis-variations?index=loosers",
            headers=_NSE_HEADERS, timeout=15,
        )
        rl.raise_for_status()
    except Exception as e:
        log.warning("NSE gainers fetch failed: %s", e)
        return None

    meta = _load_meta()

    def _parse_items(payload: dict, key: str = "allSec") -> tuple[list, str]:
        section = payload.get(key, {})
        if not isinstance(section, dict):
            return [], ""
        items = section.get("data", [])
        ts = section.get("timestamp", "")
        as_of = ts if ts else datetime.now().strftime("%Y-%m-%d %H:%M")
        results = []
        for item in items:
            sym = item.get("symbol", "")
            if not sym or not item.get("series"):
                continue
            try:
                chg_pct = float(item.get("perChange", 0))
                price = float(item.get("ltp", 0))
                turnover_cr = round(float(item.get("turnover") or 0) / 100, 1)
                m = meta.get(sym, {})
                results.append({
                    "symbol": sym,
                    "name": m.get("name", sym),
                    "sector": m.get("sector", ""),
                    "mcap_cr": m.get("mcap_cr", 0),
                    "price": round(price, 2),
                    "chg_pct": round(chg_pct, 2),
                    "turnover_cr": turnover_cr,
                })
            except (KeyError, ValueError, TypeError):
                pass
        return results, as_of

    gainers, as_of = _parse_items(rg.json())
    losers, _ = _parse_items(rl.json())

    if not gainers and not losers:
        return None

    gainers = sorted(gainers, key=lambda x: x["chg_pct"], reverse=True)[:n]
    losers = sorted(losers, key=lambda x: x["chg_pct"])[:n]
    universe_size = len(gainers) + len(losers)
    return {"gainers": gainers, "losers": losers, "as_of": as_of, "universe_size": universe_size, "source": "nse"}


def _from_yfinance(n: int) -> dict:
    """Fallback: yfinance 5d EOD download."""
    symbols_ns = _load_universe()
    meta = _load_meta()

    if not symbols_ns:
        return {"gainers": [], "losers": [], "as_of": "no data"}

    bulk = get_bulk_daily(symbols_ns, period="5d")
    if not bulk:
        return {"gainers": [], "losers": [], "as_of": "error"}

    results = []
    as_of = None

    for sym_ns, df in bulk.items():
        sym = sym_ns.replace(".NS", "")
        try:
            close = df["Close"].dropna() if "Close" in df.columns else pd.Series()
            if len(close) < 2:
                continue
            if as_of is None:
                as_of = str(close.index[-1].date())
            price = float(close.iloc[-1])
            prev = float(close.iloc[-2])
            chg_pct = (price - prev) / prev * 100 if prev else 0.0
            avg_vol = float(df["Volume"].tail(5).mean()) if "Volume" in df.columns else 0
            turnover_cr = round(price * avg_vol / 1e7, 1)
            m = meta.get(sym, {})
            results.append({
                "symbol": sym,
                "name": m.get("name", sym),
                "sector": m.get("sector", ""),
                "mcap_cr": m.get("mcap_cr", 0),
                "price": round(price, 2),
                "chg_pct": round(chg_pct, 2),
                "turnover_cr": turnover_cr,
            })
        except (KeyError, ValueError, TypeError, IndexError):
            pass

    results.sort(key=lambda x: x["chg_pct"], reverse=True)
    gainers = [r for r in results if r["chg_pct"] > 0][:n]
    losers = [r for r in reversed(results) if r["chg_pct"] < 0][:n]
    return {"gainers": gainers, "losers": losers, "as_of": as_of or "?", "universe_size": len(results), "source": "yfinance"}


def get_gainers_losers(n: int = _TOP_N) -> dict:
    key = f"gainers_losers|{n}"
    cached = cache_get(key, _TTL)
    if cached:
        return cached

    result = _from_nse(n) or _from_yfinance(n)
    cache_set(key, result)
    return result
