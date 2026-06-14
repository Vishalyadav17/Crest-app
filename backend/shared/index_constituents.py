"""
Fetch NSE index constituents from niftyindices.com CSV endpoints.
Usage: fetch_index_constituents("niftyenergy") -> [{symbol, company_name, industry, yf_ticker}]
"""
from __future__ import annotations
import io
import logging
import requests
import pandas as pd

log = logging.getLogger(__name__)

_BASE_URL = "https://www.niftyindices.com/IndexConstituent/ind_{index_id}list.csv"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.niftyindices.com/",
}


def fetch_index_constituents(index_id: str) -> list[dict]:
    """
    Download constituent CSV for a given index_id (e.g. 'niftyenergy').
    Returns list of {symbol, company_name, industry, yf_ticker}.
    Returns [] on any failure.
    """
    url = _BASE_URL.format(index_id=index_id)
    try:
        resp = requests.get(url, headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        df = pd.read_csv(io.StringIO(resp.text))

        # Column name can vary — normalise
        df.columns = [c.strip() for c in df.columns]
        sym_col = next((c for c in df.columns if c.upper() in ("SYMBOL", "TICKER")), None)
        if sym_col is None:
            log.warning("index %s CSV has no Symbol column: %s", index_id, list(df.columns))
            return []

        df["symbol"]      = df[sym_col].str.strip()
        df["yf_ticker"]   = df["symbol"] + ".NS"
        df["company_name"] = df.get("Company Name", df.get("Company", "")).astype(str).str.strip()
        df["industry"]     = df.get("Industry", "").astype(str).str.strip()

        records = df[["symbol", "company_name", "industry", "yf_ticker"]].dropna(subset=["symbol"])
        # Filter NSE placeholder tickers (e.g. DUMMYVEDL1-4 from Vedanta restructuring)
        records = records[~records["symbol"].str.upper().str.startswith("DUMMY")]
        return records.to_dict(orient="records")

    except Exception as e:
        log.warning("fetch_index_constituents(%s) failed: %s", index_id, e)
        return []
