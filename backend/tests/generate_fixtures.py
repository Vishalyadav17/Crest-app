"""
Generate frozen OHLCV fixtures for test_sepa.py.
Run once: python tests/generate_fixtures.py
Saves JSON files to tests/fixtures/{SYM}.json
"""
import json
import sys
from pathlib import Path
import pandas as pd

sys.path.insert(0, str(Path(__file__).parent.parent))

import yfinance as yf

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_FIXTURES_DIR.mkdir(exist_ok=True)

STOCKS = {
    "stage2":    ["POLYCAB.NS", "SUNPHARMA.NS", "NESTLEIND.NS"],
    "stage4":    ["YESBANK.NS", "PNB.NS", "HINDPETRO.NS"],
    "ambiguous": ["TATASTEEL.NS", "UNIONBANK.NS", "IRFC.NS"],
}

def main():
    all_syms = [s for group in STOCKS.values() for s in group]
    print(f"Fetching {len(all_syms)} tickers…")

    for sym in all_syms:
        try:
            df = yf.download(sym, period="1y", auto_adjust=True, progress=False)
            if df.empty:
                print(f"  SKIP {sym} — no data")
                continue
            # yfinance 1.3+ returns MultiIndex columns for single ticker — flatten
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = [col[0] for col in df.columns]
            out = _FIXTURES_DIR / f"{sym.replace('.NS','')}.json"
            df.reset_index(inplace=True)
            df["Date"] = df["Date"].astype(str)
            out.write_text(json.dumps(df.to_dict(orient="records"), indent=2))
            print(f"  OK   {sym} → {len(df)} rows")
        except Exception as e:
            print(f"  ERR  {sym}: {e}")

    meta = {label: [s.replace(".NS","") for s in syms] for label, syms in STOCKS.items()}
    (_FIXTURES_DIR / "meta.json").write_text(json.dumps(meta, indent=2))
    print("Done.")

if __name__ == "__main__":
    main()
