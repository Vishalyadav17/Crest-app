"""
Refresh NIFTY Microcap 250 index members in stock_master DB table.
Sets is_microcap_idx=True for current members, False for stocks that dropped out.
Run weekly on Saturday before the scan.

Usage:
  python backend/scripts/refresh_microcap_idx.py
"""
from __future__ import annotations
import sys
import math
import time
from datetime import datetime, timezone
from pathlib import Path

_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

import yfinance as yf
from shared.index_constituents import fetch_index_constituents
from database import SessionLocal
from models import StockMaster

INDUSTRY_TO_SECTOR: dict[str, str] = {
    "Automobile and Auto Components":    "AUTO",
    "Capital Goods":                     "INFRA",
    "Chemicals":                         "PHARMA",
    "Construction":                      "INFRA",
    "Construction Materials":            "INFRA",
    "Consumer Durables":                 "CONSR_DURBL",
    "Consumer Services":                 "SERVICES",
    "Diversified":                       "",
    "Fast Moving Consumer Goods":        "FMCG",
    "Financial Services":                "FIN_SERVICES",
    "Healthcare":                        "HEALTHCARE",
    "Information Technology":            "IT",
    "Media Entertainment & Publication": "MEDIA",
    "Metals & Mining":                   "METAL",
    "Oil Gas & Consumable Fuels":        "OIL_GAS",
    "Power":                             "ENERGY",
    "Realty":                            "REALTY",
    "Services":                          "SERVICES",
    "Telecommunication":                 "SERVICES",
    "Textiles":                          "",
}

_CHUNK = 50


def _fetch_mcap(symbols: list[str]) -> dict[str, float]:
    result: dict[str, float] = {}
    ns = [s + ".NS" for s in symbols]
    for i in range(0, len(ns), _CHUNK):
        batch = ns[i:i + _CHUNK]
        for ns_sym in batch:
            sym = ns_sym.replace(".NS", "")
            try:
                fi = yf.Ticker(ns_sym).fast_info
                mc = fi.market_cap
                if mc and math.isfinite(mc) and mc > 0:
                    result[sym] = round(mc / 1e7, 0)
            except Exception:
                pass
        time.sleep(0.5)
    return result


def main() -> None:
    print("Fetching NIFTY Microcap 250 constituents from niftyindices.com…")
    records = fetch_index_constituents("niftymicrocap250")
    if not records:
        print("ERROR: could not fetch microcap index — aborting")
        sys.exit(1)
    print(f"  {len(records)} stocks fetched")

    syms = [r["symbol"] for r in records]

    print(f"Fetching market caps for {len(syms)} stocks (chunks of {_CHUNK})…")
    mcap_map = _fetch_mcap(syms)
    print(f"  Got mcap for {len(mcap_map)}/{len(syms)} stocks")

    db = SessionLocal()
    try:
        # Reset all existing microcap flags
        db.query(StockMaster).filter(StockMaster.is_microcap_idx.is_(True)).update(
            {"is_microcap_idx": False}
        )
        db.flush()

        now = datetime.now(timezone.utc)
        updated = 0
        added = 0

        for r in records:
            sym = r["symbol"]
            name = r["company_name"]
            sector = INDUSTRY_TO_SECTOR.get(r.get("industry", ""), "")
            mcap = mcap_map.get(sym)

            existing = db.query(StockMaster).filter(StockMaster.sym == sym).first()
            if existing:
                existing.is_microcap_idx = True
                if sector:
                    existing.sector = sector
                if mcap:
                    existing.mcap_cr = mcap
                existing.last_updated = now
                updated += 1
            else:
                db.add(StockMaster(
                    sym=sym, name=name, exchange="NSE", asset_class="equity",
                    sector=sector, mcap_cr=mcap, is_microcap_idx=True,
                    last_updated=now,
                ))
                added += 1

        db.commit()
        print(f"  Updated {updated} existing, inserted {added} new stocks with is_microcap_idx=True")

        if records:
            print("\nSample (first 10):")
            for r in records[:10]:
                sym = r["symbol"]
                mc = mcap_map.get(sym, 0)
                print(f"  {sym:15} ₹{mc:.0f} Cr  {r.get('industry','')}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
