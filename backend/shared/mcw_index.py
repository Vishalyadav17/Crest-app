"""
Market-cap-weighted (MCW) synthetic index engine.

Builds a synthetic price series for any index_master row (chartmaze basic-industry,
official NSE sector index, or broad tier) from its live constituent OHLC, then
computes the same trend/level/breadth signals a real index would expose. This is
how niche sectors with no Yahoo index ticker (Defence, EV, Digital, …) get ranked.

Construction (correctness notes):
- Each constituent's Close is REBASED to 100 at the common start date, so the index
  reflects mcap-WEIGHTED RETURNS, not absolute price levels (a ₹5000 stock must not
  dominate a ₹50 stock merely by price).
- Weights = static mcap_cr. Free-float weights are unavailable; this is a documented
  simplification. Missing-mcap constituents get the median weight of known ones; if
  most are missing the whole index falls back to EQUAL weight.
- Constituents failing data_quality are dropped (never pollute the index).
"""
from __future__ import annotations
import logging
from statistics import median

import pandas as pd

from shared.tickers import nse
from shared.yfinance_client import get_bulk_daily
from shared import data_quality as dq
from shared.cache import cache_get, cache_set

log = logging.getLogger(__name__)

_TTL = 86400  # 24h
_KIND_TO_MTYPE = {"basic_industry": "basic_industry", "sector": "sector", "broad": "broad"}


def _ema(s: pd.Series, span: int) -> pd.Series:
    return s.ewm(span=span, adjust=False).mean()


def _constituents(db, name: str, kind: str) -> list[str]:
    from models import IndexMembership
    mtype = _KIND_TO_MTYPE.get(kind, "basic_industry")
    return [
        m.sym for m in db.query(IndexMembership)
        .filter(IndexMembership.index_name == name, IndexMembership.index_type == mtype)
        .all()
    ]


def _weights(db, syms: list[str]) -> dict[str, float]:
    from models import StockMaster
    rows = db.query(StockMaster.sym, StockMaster.mcap_cr).filter(StockMaster.sym.in_(syms)).all()
    raw = {s: (float(m) if m is not None else None) for s, m in rows}
    known = [v for v in raw.values() if v and v > 0]
    if not known or len(known) < max(1, len(syms) // 2):
        # Too few known mcaps → equal weight everything.
        return {s: 1.0 for s in syms}
    fill = median(known)
    return {s: (raw.get(s) if raw.get(s) and raw[s] > 0 else fill) for s in syms}


def compute_mcw_index(name: str, kind: str, db, period: str = "1y", use_cache: bool = True) -> dict | None:
    """
    Returns a dict of index signals, or None if too few valid constituents.
    Caches the computed signals (not the heavy OHLC) for 24h per (name, kind).
    """
    cache_key = f"mcw::{kind}::{name}"
    if use_cache:
        cached = cache_get(cache_key, _TTL)
        if cached:
            return cached

    syms = _constituents(db, name, kind)
    if not syms:
        log.warning("MCW %s: no constituents", name)
        return None

    weights = _weights(db, syms)
    bulk = get_bulk_daily([nse(s) for s in syms], period=period)

    closes: dict[str, pd.Series] = {}
    valid_w: dict[str, float] = {}
    # Per-constituent trend flags for breadth.
    above20 = above50 = above200 = near_high = considered = 0

    for s in syms:
        df = bulk.get(nse(s))
        ok, _ = dq.check_series(df, min_rows=60)
        if not ok:
            continue
        close = df["Close"].dropna()
        closes[s] = close
        valid_w[s] = weights.get(s, 1.0)

        considered += 1
        price = float(close.iloc[-1])
        if len(close) >= 20 and price > float(_ema(close, 20).iloc[-1]):
            above20 += 1
        if len(close) >= 50 and price > float(_ema(close, 50).iloc[-1]):
            above50 += 1
        if len(close) >= 200 and price > float(_ema(close, 200).iloc[-1]):
            above200 += 1
        hi52 = float(close.tail(min(252, len(close))).max())
        if hi52 and price >= hi52 * 0.95:
            near_high += 1

    if considered < 2:
        log.warning("MCW %s: only %d valid constituents", name, considered)
        return None

    # Build rebased, mcap-weighted index series.
    frame = pd.DataFrame(closes).sort_index()
    frame = frame.ffill().dropna()  # align on common dates; drop leading gaps
    if frame.empty or len(frame) < 60:
        return None
    rebased = frame / frame.iloc[0] * 100.0
    wvec = pd.Series({c: valid_w[c] for c in frame.columns})
    wvec = wvec / wvec.sum()
    idx = (rebased * wvec).sum(axis=1)

    price = float(idx.iloc[-1])
    ema20 = float(_ema(idx, 20).iloc[-1])
    ema50 = float(_ema(idx, 50).iloc[-1])
    ema200 = float(_ema(idx, 200).iloc[-1]) if len(idx) >= 200 else float(_ema(idx, len(idx) - 1).iloc[-1])
    ema200_series = _ema(idx, 200) if len(idx) >= 200 else _ema(idx, max(2, len(idx) - 1))
    ema200_prev = float(ema200_series.iloc[-21]) if len(ema200_series) >= 21 else float(ema200_series.iloc[0])
    ema200_rising = ema200 > ema200_prev

    ath = float(idx.max())
    hi52 = float(idx.tail(min(252, len(idx))).max())
    pct_from_ath = round((ath - price) / ath * 100, 2) if ath else None
    pct_from_52wh = round((hi52 - price) / hi52 * 100, 2) if hi52 else None

    result = {
        "name": name,
        "kind": kind,
        "constituents_total": len(syms),
        "constituents_used": considered,
        "mcw_price": round(price, 2),
        "ema20": round(ema20, 2),
        "ema50": round(ema50, 2),
        "ema200": round(ema200, 2),
        "ema200_rising": bool(ema200_rising),
        "trend_template": bool(price > ema20 > ema50 > ema200 and ema200_rising),
        "pct_from_ath": pct_from_ath,
        "pct_from_52wh": pct_from_52wh,
        "breadth_above_ema20": round(above20 / considered * 100, 1),
        "breadth_above_ema50": round(above50 / considered * 100, 1),
        "breadth_above_ema200": round(above200 / considered * 100, 1),
        "count_near_high": near_high,
    }

    if use_cache:
        cache_set(cache_key, result, _TTL)
    return result


def persist_to_industry_master(db, sig: dict) -> None:
    """Write computed MCW signals onto the industry_master row."""
    from models import IndustryMaster
    from scripts.kb.common import now_utc
    row = db.query(IndustryMaster).filter(IndustryMaster.name == sig["name"]).one_or_none()
    if row is None:
        return
    row.mcw_price = sig["mcw_price"]
    row.ema20 = sig["ema20"]
    row.ema50 = sig["ema50"]
    row.ema200 = sig["ema200"]
    row.ema200_rising = sig["ema200_rising"]
    row.pct_from_52wh = sig["pct_from_52wh"]
    row.pct_from_ath = sig["pct_from_ath"]
    row.breadth_above_ema20 = sig["breadth_above_ema20"]
    row.breadth_above_ema50 = sig["breadth_above_ema50"]
    row.breadth_above_ema200 = sig["breadth_above_ema200"]
    row.count_near_high = sig["count_near_high"]
    row.live_updated_at = now_utc()
