import io
import time
import logging
import json
import pandas as pd
import yfinance as yf
from shared.cache import cache_get, cache_set

log = logging.getLogger(__name__)

_DAILY_TTL    = 86400      # 24h for EOD data
_LIVE_TTL     = 900        # 15 min for live snapshots
_RETRIES      = 3
_BACKOFF      = [30, 60, 120]
_CHUNK_SIZE   = 50         # Yahoo rate-limits bulk calls; 50/chunk stays safe
_CHUNK_SLEEP  = 1.0        # seconds between chunks


def _flatten_columns(df: pd.DataFrame) -> pd.DataFrame:
    """yfinance 1.3+ returns MultiIndex columns for single-ticker downloads; flatten to plain names."""
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [col[0] for col in df.columns]
    return df


def _fetch_with_retry(sym: str, period: str, interval: str = "1d") -> pd.DataFrame:
    for attempt in range(_RETRIES):
        try:
            df = yf.download(sym, period=period, interval=interval,
                             auto_adjust=True, progress=False, timeout=30)
            if df is not None and not df.empty:
                return _flatten_columns(df)
            # Empty but no exception = ticker not found / delisted — no point retrying
            return pd.DataFrame()
        except Exception as e:
            log.warning("yfinance attempt %d failed for %s: %s", attempt + 1, sym, e)
            if attempt < _RETRIES - 1:
                time.sleep(_BACKOFF[attempt])
    return pd.DataFrame()


def get_daily(sym: str, period: str = "1y") -> pd.DataFrame:
    """Cached daily OHLCV. period = '1mo','3mo','6mo','1y','2y','3y'."""
    key = f"daily|{sym}|{period}"
    ttl = _DAILY_TTL
    cached = cache_get(key, ttl)
    if cached is not None:
        return pd.read_json(io.StringIO(cached), orient="split")

    df = _fetch_with_retry(sym, period)
    if not df.empty:
        cache_set(key, df.to_json(orient="split"))
    return df


def get_bulk_daily(symbols: list[str], period: str = "1y") -> dict[str, pd.DataFrame]:
    """
    Download symbols in 50-ticker chunks with 1s sleep between chunks.
    Yahoo Finance silently drops tickers in large bulk calls (rate limit ~100 concurrent
    requests); chunking keeps each call well within that limit.
    Returns {sym: DataFrame} — keys match exactly what was passed in.
    """
    key = f"bulk|{'_'.join(sorted(symbols)[:5])}|{len(symbols)}|{period}"
    cached = cache_get(key, _DAILY_TTL)

    if cached is not None:
        raw = json.loads(cached)
        return {s: pd.read_json(io.StringIO(v), orient="split") for s, v in raw.items()}

    result: dict[str, pd.DataFrame] = {}
    n_chunks = -(-len(symbols) // _CHUNK_SIZE)  # ceiling div

    for i in range(0, len(symbols), _CHUNK_SIZE):
        chunk = symbols[i : i + _CHUNK_SIZE]
        chunk_n = i // _CHUNK_SIZE + 1
        raw = None

        for attempt in range(_RETRIES):
            try:
                raw = yf.download(chunk, period=period, auto_adjust=True,
                                  progress=False, timeout=60, group_by="ticker")
                break
            except Exception as e:
                log.warning("bulk chunk %d/%d attempt %d failed: %s", chunk_n, n_chunks, attempt + 1, e)
                if attempt < _RETRIES - 1:
                    time.sleep(_BACKOFF[attempt])

        if raw is None or raw.empty:
            log.warning("bulk chunk %d/%d returned no data", chunk_n, n_chunks)
        elif isinstance(raw.columns, pd.MultiIndex):
            for sym in chunk:
                try:
                    df = raw[sym].dropna(how="all")
                    if not df.empty:
                        result[sym] = df
                except KeyError:
                    pass
        else:
            # Single-ticker chunk — flat columns
            df = raw.dropna(how="all")
            if not df.empty and chunk:
                result[chunk[0]] = df

        if i + _CHUNK_SIZE < len(symbols):
            time.sleep(_CHUNK_SLEEP)

    log.info("bulk_daily %s/%d symbols (%d chunks)", len(result), len(symbols), n_chunks)

    if result:
        payload = {s: df.to_json(orient="split") for s, df in result.items()}
        cache_set(key, json.dumps(payload))

    return result


def get_live_price(sym: str) -> float | None:
    """Last close price with 15-min cache."""
    key = f"live|{sym}"
    cached = cache_get(key, _LIVE_TTL)
    if cached is not None:
        return cached

    try:
        ticker = yf.Ticker(sym, )
        hist = ticker.history(period="2d", auto_adjust=True)
        if not hist.empty:
            price = float(hist["Close"].iloc[-1])
            cache_set(key, price)
            return price
    except Exception as e:
        log.warning("live price failed for %s: %s", sym, e)
    return None
