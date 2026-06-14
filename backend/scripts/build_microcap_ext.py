"""
Build data/microcap_ext.json — NSE stocks outside Nifty 500 with mcap 800–8000 Cr.
These are invisible to the scanner today. Run weekly after market close.

Usage:
  python backend/scripts/build_microcap_ext.py
"""
from __future__ import annotations
import sys, json, math, time, warnings
from pathlib import Path

warnings.filterwarnings("ignore")
_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import requests
import pandas as pd
import yfinance as yf

_OUT = _BACKEND / "data" / "microcap_ext.json"
_SECTORS_FILE = _BACKEND / "data" / "sectors.json"
_MCAP_MIN = 800      # Cr — below this = nano-cap, skip
_MCAP_MAX = 8000     # Cr — above this = already in N500
_PRICE_MIN = 10      # ₹ — filter out penny/suspended stocks
_CHUNK = 50


def _get_all_nse_eq() -> list[tuple[str, str]]:
    r = requests.get(
        "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
        headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.nseindia.com/"},
        timeout=15,
    )
    r.raise_for_status()
    df = pd.read_csv(__import__("io").StringIO(r.text))
    df.columns = [c.strip() for c in df.columns]
    eq = df[df["SERIES"].str.strip() == "EQ"][["SYMBOL", "NAME OF COMPANY"]].copy()
    eq.loc[:, "SYMBOL"] = eq["SYMBOL"].str.strip()
    eq.loc[:, "NAME OF COMPANY"] = eq["NAME OF COMPANY"].str.strip()
    return list(zip(eq["SYMBOL"], eq["NAME OF COMPANY"]))


def _batch_prices(symbols: list[str]) -> dict[str, float]:
    """One yfinance call per chunk → returns {symbol: last_close}."""
    result: dict[str, float] = {}
    ns = [s + ".NS" for s in symbols]
    for i in range(0, len(ns), _CHUNK):
        batch = ns[i : i + _CHUNK]
        try:
            raw = yf.download(batch, period="5d", auto_adjust=True, progress=False, timeout=25)
            if raw is None or raw.empty:
                continue
            close = raw["Close"]
            if isinstance(close, pd.Series):
                close = close.to_frame(name=batch[0])
            last = close.dropna(how="all").iloc[-1] if not close.dropna(how="all").empty else pd.Series(dtype=float)
            for ns_sym in batch:
                sym = ns_sym.replace(".NS", "")
                try:
                    price = float(last.get(ns_sym, 0) or 0)
                    if price >= _PRICE_MIN:
                        result[sym] = round(price, 2)
                except Exception:
                    pass
        except Exception as e:
            print(f"  price chunk {i//50} err: {e}")
        time.sleep(0.3)
    return result


def _fetch_mcap(symbols: list[str]) -> dict[str, float]:
    """Fetch market_cap_cr via fast_info for a small symbol list."""
    result: dict[str, float] = {}
    for sym in symbols:
        try:
            fi = yf.Ticker(sym + ".NS").fast_info
            mc = fi.market_cap
            if mc and math.isfinite(mc) and mc > 0:
                result[sym] = round(mc / 1e7, 0)  # INR → Crores (1 Cr = 1e7)
        except Exception:
            pass
    return result


def main():
    print("1. Fetching NSE EQ listing…")
    all_eq = _get_all_nse_eq()
    print(f"   {len(all_eq)} EQ stocks on NSE")

    with open(_SECTORS_FILE) as f:
        sectors = json.load(f)
    n500 = set(sectors["N500"])

    candidates = [(sym, name) for sym, name in all_eq if sym not in n500]
    print(f"   {len(candidates)} stocks outside N500")

    print("2. Batch price download to filter active stocks…")
    syms = [s for s, _ in candidates]
    prices = _batch_prices(syms)
    active = [s for s in syms if s in prices]
    print(f"   {len(active)} active stocks (price ≥ ₹{_PRICE_MIN})")

    print(f"3. Fetching market caps for {len(active)} active stocks…")
    mcaps = _fetch_mcap(active)
    print(f"   Got mcap for {len(mcaps)} stocks")

    # Filter to microcap range
    micro = {sym: mc for sym, mc in mcaps.items() if _MCAP_MIN <= mc <= _MCAP_MAX}
    print(f"   {len(micro)} stocks in {_MCAP_MIN}–{_MCAP_MAX} Cr range")

    # Build output list with name lookup
    name_map = dict(all_eq)
    output = [
        {"symbol": sym, "name": name_map.get(sym, sym), "mcap_cr": mc}
        for sym, mc in sorted(micro.items(), key=lambda x: -x[1])
    ]

    _OUT.parent.mkdir(parents=True, exist_ok=True)
    with open(_OUT, "w") as f:
        json.dump(output, f, indent=2)

    print(f"\nWrote {len(output)} stocks → {_OUT}")
    if output:
        print("Top 10 by mcap:")
        for o in output[:10]:
            print(f"  {o['symbol']:15} ₹{o['mcap_cr']:.0f} Cr  {o['name']}")


if __name__ == "__main__":
    main()
