"""
Rebuild data/nifty500.csv with all 500 Nifty 500 stocks.
- Fetches constituents from niftyindices.com (symbol, name, industry)
- Maps NSE industry → our sector label
- Merges existing mcap_cr where available; fetches fresh for new stocks via yfinance
- Writes symbol,name,sector,mcap_cr

Usage:
  python backend/scripts/rebuild_nifty500.py
"""
from __future__ import annotations
import sys
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import math
import time
import pandas as pd
import yfinance as yf
from shared.index_constituents import fetch_index_constituents

_OUT = _BACKEND / "data" / "nifty500.csv"

INDUSTRY_TO_SECTOR: dict[str, str] = {
    "Automobile and Auto Components":  "AUTO",
    "Capital Goods":                   "INFRA",
    "Chemicals":                       "PHARMA",
    "Construction":                    "INFRA",
    "Construction Materials":          "INFRA",
    "Consumer Durables":               "CONSR_DURBL",
    "Consumer Services":               "SERVICES",
    "Diversified":                     "",
    "Fast Moving Consumer Goods":      "FMCG",
    "Financial Services":              "FIN_SERVICES",
    "Healthcare":                      "HEALTHCARE",
    "Information Technology":          "IT",
    "Media Entertainment & Publication": "MEDIA",
    "Metals & Mining":                 "METAL",
    "Oil Gas & Consumable Fuels":      "OIL_GAS",
    "Power":                           "ENERGY",
    "Realty":                          "REALTY",
    "Services":                        "SERVICES",
    "Telecommunication":               "SERVICES",
    "Textiles":                        "",
}


def _fetch_mcap_batch(symbols: list[str], chunk: int = 50) -> dict[str, float]:
    """Fetch mcap_cr for symbols using yfinance fast_info in chunks."""
    result: dict[str, float] = {}
    ns_syms = [s + ".NS" for s in symbols]
    for i in range(0, len(ns_syms), chunk):
        batch = ns_syms[i:i + chunk]
        try:
            df = yf.download(batch, period="1d", auto_adjust=True, progress=False, timeout=30)
            if df is None or df.empty:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                close = df["Close"]
            else:
                close = df[["Close"]]
                close.columns = [batch[0]]
            # We only have price — need market_cap from info; use fast_info per ticker
            for ns in batch:
                sym = ns.replace(".NS", "")
                try:
                    t = yf.Ticker(ns)
                    mc = t.fast_info.market_cap
                    if mc and math.isfinite(mc) and mc > 0:
                        result[sym] = round(mc / 1e7, 0)  # convert to Cr (1 Cr = 1e7 INR)
                except Exception:
                    pass
        except Exception as e:
            print(f"  batch {i//chunk} failed: {e}")
        time.sleep(0.5)
    return result


def main():
    print("Fetching N500 constituents from niftyindices.com…")
    records = fetch_index_constituents("nifty500")
    if not records:
        print("ERROR: could not fetch N500 constituents")
        sys.exit(1)
    print(f"  {len(records)} stocks fetched")

    # Load existing CSV to preserve mcap data
    existing_mcap: dict[str, float] = {}
    existing_sector: dict[str, str] = {}
    if _OUT.exists():
        old = pd.read_csv(_OUT).dropna(subset=["symbol"])
        existing_mcap   = dict(zip(old["symbol"], old["mcap_cr"].fillna(0)))
        existing_sector = dict(zip(old["symbol"], old.get("sector", pd.Series()).fillna("")))
    print(f"  {len(existing_mcap)} stocks in existing CSV (mcap preserved)")

    # Build new frame
    rows = []
    for r in records:
        sym     = r["symbol"]
        name    = r["company_name"]
        industry = r.get("industry", "")
        sector  = INDUSTRY_TO_SECTOR.get(industry, "")
        mcap    = existing_mcap.get(sym, 0)
        rows.append({"symbol": sym, "name": name, "sector": sector, "mcap_cr": mcap})

    df = pd.DataFrame(rows)

    # Fetch mcap for stocks missing it
    missing = df[df["mcap_cr"] == 0]["symbol"].tolist()
    if missing:
        print(f"  Fetching mcap for {len(missing)} new stocks (this takes ~{len(missing)//50 + 1} min)…")
        fresh_mcap = _fetch_mcap_batch(missing)
        print(f"  Got mcap for {len(fresh_mcap)}/{len(missing)} stocks")
        for sym, mc in fresh_mcap.items():
            df.loc[df["symbol"] == sym, "mcap_cr"] = mc

    df.to_csv(_OUT, index=False)
    print(f"\nWrote {len(df)} stocks → {_OUT}")
    print(f"  Sector coverage: {df[df['sector'] != ''].shape[0]}/{len(df)} stocks have sector")
    print(f"  Mcap coverage:   {df[df['mcap_cr'] > 0].shape[0]}/{len(df)} stocks have mcap")


if __name__ == "__main__":
    main()
