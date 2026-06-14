"""
Validate all yfinance tickers from shared/tickers.py against live data.
Run once before building any feature that uses these tickers.

Usage: python scripts/probe_tickers.py
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import yfinance as yf
from shared.tickers import INDEX_NIFTY50, INDEX_BANKNIFTY, INDEX_NIFTY500, INDEX_SMALLCAP, SECTOR_TICKERS

ALL_TICKERS = {
    "INDEX_NIFTY50":   INDEX_NIFTY50,
    "INDEX_BANKNIFTY": INDEX_BANKNIFTY,
    "INDEX_NIFTY500":  INDEX_NIFTY500,
    "INDEX_SMALLCAP":  INDEX_SMALLCAP,
    **{f"SECTOR_{k}": v for k, v in SECTOR_TICKERS.items()},
}

def probe(label: str, ticker: str) -> tuple[bool, str]:
    try:
        df = yf.download(ticker, period="5d", auto_adjust=True, progress=False,
                         timeout=15)
        if df is None or df.empty:
            return False, "empty response"
        last_close = float(df["Close"].dropna().iloc[-1])
        rows = len(df.dropna())
        return True, f"{rows} rows, last close={last_close:.2f}"
    except Exception as e:
        return False, str(e)

def main():
    ok_list  = []
    bad_list = []

    print(f"\nProbing {len(ALL_TICKERS)} tickers…\n")
    for label, ticker in ALL_TICKERS.items():
        ok, detail = probe(label, ticker)
        status = "✅ OK " if ok else "❌ BAD"
        print(f"  {status}  {label:30s}  {ticker:35s}  {detail}")
        (ok_list if ok else bad_list).append((label, ticker))
        time.sleep(0.3)  # gentle rate limit

    print(f"\n{'='*70}")
    print(f"  PASSED: {len(ok_list)}/{len(ALL_TICKERS)}")
    if bad_list:
        print(f"  FAILED ({len(bad_list)}):")
        for label, ticker in bad_list:
            print(f"    {label} → {ticker}")
        print("\n  ⚠️  Fix failed tickers in shared/tickers.py before building features.")
    else:
        print("  All tickers valid — safe to proceed.")
    print()

if __name__ == "__main__":
    main()
