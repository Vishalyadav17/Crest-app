"""
Refresh backend/data/portfolio.json from Kite data.

USAGE:
  Option A — via Claude Code with Kite MCP (recommended):
    Ask Claude: "Export my current Kite holdings, positions, and account info to portfolio.json"
    Claude will call kite MCP tools and write the file directly.

  Option B — from Kite CSV export (no MCP required):
    1. Log in to Console (console.zerodha.com) → Reports → Holdings → Download CSV
    2. python export_from_kite.py --csv path/to/holdings.csv

  Option C — manual JSON edit:
    Directly edit backend/data/portfolio.json with updated ltps, qtys, etc.

Market cap buckets (set mcap_cr per stock, bucket is derived):
  Large:  mcap_cr >= 20000
  Mid:    5000 <= mcap_cr < 20000
  Small:  500 <= mcap_cr < 5000
  Micro:  mcap_cr < 500
"""
import csv
import json
import sys
from datetime import datetime
from pathlib import Path

_DATA_DIR    = Path(__file__).parent / "data"
_OUTPUT_PATH = _DATA_DIR / "portfolio.json"

_MCAP_LOOKUP = {
    "BAJFINANCE": 550000, "CAPLIPOINT": 700,  "VBL": 70000,   "ITC": 380000,
    "RELIANCE": 1800000,  "ADANIPORTS": 370000,"BHARTIARTL": 900000,"LT": 550000,
    "NUVAMA": 20000,      "SJS": 1800,         "HCG": 4500,    "NH": 30000,
    "IEX": 11000,         "IKS": 16000,        "ATHERENERG": 1500,"RRKABEL": 15000,
    "LAURUSLABS": 7000,   "STLTECH": 3500,     "CARTRADE": 4000,"KPL": 800,
    "APARINDS": 11000,    "TDPOWERSYS": 3000,  "DEEDEV": 2000,  "RBA": 500,
    "MCX": 20000,         "GPIL": 8000,        "JBCHEPHARM": 5000,"RPTECH": 1500,
    "ARMANFIN": 4500,     "HFCL": 3000,
}
_ETF_SYMS = {"NIFTYBEES", "GOLDIETF", "GOLD1", "JUNIORBEES", "ICICIB22"}
_SECTOR_LOOKUP = {
    "BAJFINANCE": "Finance",    "IEX": "Finance",       "NUVAMA": "Finance",
    "MCX": "Finance",           "VBL": "FMCG",          "ITC": "FMCG",
    "CAPLIPOINT": "Pharma",     "HCG": "Pharma",        "NH": "Pharma",
    "LAURUSLABS": "Pharma",     "IKS": "Pharma",        "KPL": "Pharma",
    "JBCHEPHARM": "Pharma",     "LT": "Engineering",    "RRKABEL": "Engineering",
    "APARINDS": "Engineering",  "ATHERENERG": "Energy", "TDPOWERSYS": "Energy",
    "ADANIPORTS": "Infra",      "BHARTIARTL": "Telecom","STLTECH": "Telecom",
    "HFCL": "Telecom",          "SJS": "Auto",          "CARTRADE": "Auto",
    "DEEDEV": "Capital Goods",  "RELIANCE": "Conglomerate","RBA": "Consumer",
    "ARMANFIN": "Finance",      "GPIL": "Metal",        "RPTECH": "IT",
    "NIFTYBEES": "ETF",         "GOLDIETF": "Gold ETF",
}


def _mcap_bucket(mcap_cr: int | None) -> str:
    if mcap_cr is None:
        return "Small"
    if mcap_cr >= 20000:
        return "Large"
    if mcap_cr >= 5000:
        return "Mid"
    if mcap_cr >= 500:
        return "Small"
    return "Micro"


def from_csv(csv_path: str) -> None:
    holdings = []
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sym = row.get("Symbol", row.get("SYMBOL", "")).strip().upper()
            if not sym:
                continue
            qty  = int(float(row.get("Quantity", row.get("QTY", 0))))
            avg  = float(row.get("Average Price", row.get("AVG PRICE", 0)))
            ltp  = float(row.get("Last Price",   row.get("LTP", avg)))
            mcap = _MCAP_LOOKUP.get(sym)
            holdings.append({
                "sym":        sym,
                "sector":     _SECTOR_LOOKUP.get(sym, "Other"),
                "mcap_bucket": _mcap_bucket(mcap),
                "mcap_cr":    mcap,
                "qty":        qty,
                "avg":        avg,
                "ltp":        ltp,
                "is_etf":     sym in _ETF_SYMS,
            })

    existing = json.loads(_OUTPUT_PATH.read_text()) if _OUTPUT_PATH.exists() else {}
    existing["holdings"] = holdings
    existing["as_of"]    = datetime.now().astimezone().isoformat()

    _OUTPUT_PATH.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    print(f"Updated {len(holdings)} holdings → {_OUTPUT_PATH}")


if __name__ == "__main__":
    if "--csv" in sys.argv:
        idx = sys.argv.index("--csv")
        from_csv(sys.argv[idx + 1])
    else:
        print(__doc__)
