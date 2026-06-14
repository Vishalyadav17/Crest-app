"""
Compute synthetic OHLC price series for a CustomIndex and persist to custom_index_history.

Algorithm (ChartMaze _MCW style — weighted candlesticks):
  - Fetch member OHLCV from bhavcopy_daily (primary) with yfinance bulk fallback.
  - Weights: mcap from stock_master; equal weight if too few mcaps known.
  - Align members on common dates; rebase each member to BASE at the window start.
  - Index O/H/L/C = Σ (member_field × rebase_factor × normalized_weight).
    Because each member's H≥C≥L and the same per-member factor/weight is applied,
    the resulting index candles stay internally consistent (H≥O,C≥L).
  - Index volume = Σ member_volume (raw sum) — gives the spike profile.
  - `value` column holds close (back-compat); open/high/low/volume populated.
  - Skips index with < 2 valid members.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from statistics import median

import pandas as pd

log = logging.getLogger(__name__)

_MAX_HISTORY_DAYS = 730   # 2 years
_BASE_VALUE = 1000.0


def _get_members(db, idx_id: int) -> list[str]:
    from models import CustomIndexMember
    return [m.sym for m in db.query(CustomIndexMember).filter(CustomIndexMember.custom_index_id == idx_id).all()]


def _fetch_bhavcopy(db, syms: list[str], cutoff: str) -> dict[str, pd.DataFrame]:
    from models import BhavcopydAily as BhavCopyDaily
    rows = (
        db.query(
            BhavCopyDaily.sym, BhavCopyDaily.date,
            BhavCopyDaily.open, BhavCopyDaily.high, BhavCopyDaily.low,
            BhavCopyDaily.close, BhavCopyDaily.volume,
        )
        .filter(BhavCopyDaily.sym.in_(syms), BhavCopyDaily.date >= cutoff)
        .order_by(BhavCopyDaily.date)
        .all()
    )
    acc: dict[str, dict] = {}
    for sym, date, o, h, l, c, v in rows:
        acc.setdefault(sym, {})[date] = {
            "o": float(o) if o is not None else None,
            "h": float(h) if h is not None else None,
            "l": float(l) if l is not None else None,
            "c": float(c),
            "v": float(v) if v is not None else 0.0,
        }
    return {sym: pd.DataFrame.from_dict(d, orient="index") for sym, d in acc.items()}


def _fetch_yfinance_fallback(syms: list[str]) -> dict[str, pd.DataFrame]:
    from shared.yfinance_client import get_bulk_daily
    from shared.tickers import nse
    bulk = get_bulk_daily([nse(s) for s in syms], period="2y")
    out = {}
    for sym in syms:
        df = bulk.get(nse(sym))
        if df is None or df.empty or "Close" in df.columns and df["Close"].dropna().empty:
            continue
        if "Close" not in df.columns:
            continue
        f = pd.DataFrame({
            "o": df.get("Open", df["Close"]),
            "h": df.get("High", df["Close"]),
            "l": df.get("Low", df["Close"]),
            "c": df["Close"],
            "v": df.get("Volume", 0.0),
        }).dropna(subset=["c"])
        f.index = f.index.strftime("%Y-%m-%d")
        out[sym] = f
    return out


def _get_weights(db, syms: list[str], mode: str) -> dict[str, float]:
    if mode == "equal":
        return {s: 1.0 for s in syms}
    from models import StockMaster
    rows = db.query(StockMaster.sym, StockMaster.mcap_cr).filter(StockMaster.sym.in_(syms)).all()
    raw = {s: (float(m) if m is not None else None) for s, m in rows}
    known = [v for v in raw.values() if v and v > 0]
    if not known or len(known) < max(1, len(syms) // 2):
        return {s: 1.0 for s in syms}
    fill = median(known)
    return {s: (raw.get(s) if raw.get(s) and raw[s] > 0 else fill) for s in syms}


def compute_and_persist(db, idx_id: int) -> int:
    """Returns number of history rows upserted."""
    from models import CustomIndex, CustomIndexHistory

    idx = db.query(CustomIndex).filter(CustomIndex.id == idx_id).one_or_none()
    if idx is None:
        log.warning("compute_and_persist: idx %d not found", idx_id)
        return 0

    syms = _get_members(db, idx_id)
    if len(syms) < 2:
        log.warning("compute idx %d (%s): < 2 members", idx_id, idx.name)
        return 0

    cutoff = (datetime.now(timezone.utc) - timedelta(days=_MAX_HISTORY_DAYS)).strftime("%Y-%m-%d")
    data = _fetch_bhavcopy(db, syms, cutoff)

    missing = [s for s in syms if s not in data or len(data[s]) < 20]
    if missing:
        for sym, df in _fetch_yfinance_fallback(missing).items():
            if sym not in data or len(data[sym]) < len(df):
                data[sym] = df

    valid = [s for s in syms if s in data and len(data[s]) >= 20]
    if len(valid) < 2:
        log.warning("compute idx %d (%s): only %d valid series", idx_id, idx.name, len(valid))
        return 0

    # Common-date close frame drives alignment
    close_frame = pd.DataFrame({s: data[s]["c"] for s in valid}).sort_index().ffill().dropna()
    if len(close_frame) < 5:
        log.warning("compute idx %d (%s): not enough common dates", idx_id, idx.name)
        return 0

    if idx.base_date and idx.base_date in close_frame.index:
        close_frame = close_frame.loc[idx.base_date:]
    elif idx.base_date and idx.base_date > close_frame.index[-1]:
        log.warning("compute idx %d: base_date after all data", idx_id)
        return 0
    if len(close_frame) < 5:
        return 0

    dates = close_frame.index
    weights = _get_weights(db, valid, idx.weight_mode)
    wvec = pd.Series({s: weights.get(s, 1.0) for s in valid})
    wvec = wvec / wvec.sum()
    factor = _BASE_VALUE / close_frame.iloc[0]   # per-sym rebase factor

    def _field(field: str) -> pd.Series:
        f = pd.DataFrame({s: data[s][field] for s in valid}).reindex(dates).ffill()
        f = f.fillna(close_frame)                       # O/H/L gaps -> close
        return f.mul(factor, axis=1).mul(wvec, axis=1).sum(axis=1).round(4)

    o, h, l, c = _field("o"), _field("h"), _field("l"), _field("c")
    vol = (
        pd.DataFrame({s: data[s]["v"] for s in valid})
        .reindex(dates).ffill().fillna(0.0).sum(axis=1).round(2)
    )

    existing = {
        r.date: r
        for r in db.query(CustomIndexHistory)
        .filter(CustomIndexHistory.custom_index_id == idx_id)
        .all()
    }
    n = 0
    for d in dates:
        row = existing.get(d)
        if row is None:
            row = CustomIndexHistory(custom_index_id=idx_id, date=d, value=float(c[d]))
            db.add(row)
        row.value  = float(c[d])
        row.open   = float(o[d])
        row.high   = float(h[d])
        row.low    = float(l[d])
        row.volume = float(vol[d])
        n += 1
    db.commit()
    log.info("compute idx %d (%s): %d OHLC rows upserted", idx_id, idx.name, n)
    return n


def recompute_all(db) -> int:
    """Recompute every custom index from current prices. Called after each scan/bhavcopy refresh."""
    from models import CustomIndex
    ids = [r.id for r in db.query(CustomIndex.id).all()]
    total = 0
    for idx_id in ids:
        try:
            total += compute_and_persist(db, idx_id)
        except Exception as e:
            db.rollback()
            log.warning("recompute_all: idx %d failed: %s", idx_id, e)
    log.info("recompute_all: %d indices, %d rows", len(ids), total)
    return total
