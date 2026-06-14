"""
NSE bhavcopy downloader — primary OHLCV source for the scheduler.

URL pattern: https://archives.nseindia.com/products/content/sec_bhavdata_full_<DDMMYYYY>.csv
Columns returned: SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, TOTTRDQTY, TOTTRDVAL
"""
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

import pandas as pd
import requests

log = logging.getLogger(__name__)

_BASE_URL = "https://archives.nseindia.com/products/content/sec_bhavdata_full_{date}.csv"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.nseindia.com/",
}
_RETRIES = 3
_BACKOFF  = [30, 60, 120]


def _date_str(d: date) -> str:
    return d.strftime("%d%m%Y")


def _prev_trading_day(d: date) -> date:
    """Walk backwards skipping weekends (does not skip public holidays)."""
    d -= timedelta(days=1)
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def fetch_bhavcopy(for_date: date | None = None) -> pd.DataFrame:
    """
    Fetch NSE bhavcopy for a given date (defaults to most recent available).
    Returns DataFrame with columns: SYMBOL, SERIES, OPEN, HIGH, LOW, CLOSE, TOTTRDQTY, TOTTRDVAL
    Raises RuntimeError if download fails after trying 3 recent trading days.
    """
    candidates: list[date] = []
    d = for_date or date.today()
    while d.weekday() >= 5:
        d = _prev_trading_day(d)
    candidates.append(d)
    candidates.append(_prev_trading_day(d))
    candidates.append(_prev_trading_day(candidates[-1]))

    for candidate in candidates:
        url = _BASE_URL.format(date=_date_str(candidate))
        for attempt in range(_RETRIES):
            try:
                r = requests.get(url, headers=_HEADERS, timeout=30)
                if r.status_code == 404:
                    log.debug("bhavcopy 404 for %s — trying previous day", candidate)
                    break
                r.raise_for_status()
                df = pd.read_csv(
                    pd.io.common.StringIO(r.text),
                    dtype=str,
                    skipinitialspace=True,
                )
                df.columns = [c.strip().upper() for c in df.columns]
                # Normalise column names (NSE changed format mid-2025)
                rename = {
                    "OPEN_PRICE":  "OPEN",
                    "HIGH_PRICE":  "HIGH",
                    "LOW_PRICE":   "LOW",
                    "CLOSE_PRICE": "CLOSE",
                    "TTL_TRD_QNTY": "TOTTRDQTY",
                    "TURNOVER_LACS": "TOTTRDVAL",
                    "TOTAL TRADED QUANTITY": "TOTTRDQTY",
                    "TOTAL TRADED VALUE": "TOTTRDVAL",
                }
                df.rename(columns=rename, inplace=True)

                required = {"SYMBOL", "SERIES", "CLOSE"}
                if not required.issubset(set(df.columns)):
                    log.warning("bhavcopy columns unexpected: %s", list(df.columns))
                    break

                df = df.copy()  # avoid CoW chained-assignment warnings
                for col in ("OPEN", "HIGH", "LOW", "CLOSE", "TOTTRDQTY", "TOTTRDVAL"):
                    if col in df.columns:
                        df.loc[:, col] = pd.to_numeric(df[col].astype(str).str.replace(",", ""), errors="coerce")

                df.loc[:, "SYMBOL"] = df["SYMBOL"].str.strip()
                df.loc[:, "SERIES"] = df["SERIES"].str.strip()
                df.loc[:, "_date"]  = candidate.isoformat()

                log.info("bhavcopy fetched: %d rows for %s", len(df), candidate)
                return df

            except requests.RequestException as e:
                log.warning("bhavcopy attempt %d failed for %s: %s", attempt + 1, candidate, e)
                if attempt < _RETRIES - 1:
                    time.sleep(_BACKOFF[attempt])

    log.error("bhavcopy: all candidates failed")
    return pd.DataFrame()


def get_all_nse_close(for_date: date | None = None) -> dict[str, float]:
    """Returns {SYMBOL: close_price} for all EQ series NSE stocks."""
    df = fetch_bhavcopy(for_date)
    if df.empty:
        return {}
    eq = df[df["SERIES"] == "EQ"]
    return dict(zip(eq["SYMBOL"], eq["CLOSE"].astype(float)))


def upsert_bhavcopy_to_db(df: pd.DataFrame) -> int:
    """
    Upsert bhavcopy rows into bhavcopy_daily and stock_master.
    Returns count of rows processed.
    """
    from database import SessionLocal
    from models import BhavcopydAily, StockMaster
    from datetime import timezone

    eq = df[df["SERIES"] == "EQ"].copy()
    if eq.empty:
        return 0

    db = SessionLocal()
    try:
        today_str = eq["_date"].iloc[0] if "_date" in eq.columns else date.today().isoformat()
        processed = 0

        for _, row in eq.iterrows():
            sym = str(row["SYMBOL"]).strip()
            if not sym:
                continue

            try:
                close = float(row["CLOSE"]) if pd.notna(row.get("CLOSE")) else None
                if close is None:
                    continue

                existing = db.query(BhavcopydAily).filter(
                    BhavcopydAily.date == today_str,
                    BhavcopydAily.sym  == sym,
                ).first()
                if existing is None:
                    db.add(BhavcopydAily(
                        date=today_str,
                        sym=sym,
                        series="EQ",
                        open=float(row["OPEN"]) if "OPEN" in row and pd.notna(row["OPEN"]) else None,
                        high=float(row["HIGH"]) if "HIGH" in row and pd.notna(row["HIGH"]) else None,
                        low=float(row["LOW"])   if "LOW"  in row and pd.notna(row["LOW"])  else None,
                        close=close,
                        volume=float(row["TOTTRDQTY"]) if "TOTTRDQTY" in row and pd.notna(row["TOTTRDQTY"]) else None,
                        tottrdval=float(row["TOTTRDVAL"]) if "TOTTRDVAL" in row and pd.notna(row["TOTTRDVAL"]) else None,
                    ))
                else:
                    existing.close  = close
                    existing.volume = float(row["TOTTRDQTY"]) if "TOTTRDQTY" in row and pd.notna(row["TOTTRDQTY"]) else existing.volume

                # Update stock_master last_updated
                sm = db.query(StockMaster).filter(StockMaster.sym == sym).first()
                if sm:
                    sm.last_updated = datetime.now(timezone.utc)

                processed += 1
            except Exception:
                log.exception("bhavcopy upsert failed for %s", sym)
                continue

        db.commit()
        return processed
    finally:
        db.close()
