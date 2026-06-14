"""
Key levels calculator per swing pick — ADAPTIVE tight entry band.

Two band shapes (Minervini/SEPA aligned), both ~4% wide vs the old 6%:
  breakout  — stock at/below a fresh-high pivot: band = pivot-1% … pivot+3%
              (buy the breakout into new highs; classic pivot buy-point)
  pullback  — stock already extended >3% past pivot: band = 10 EMA … CMP,
              capped to 4% wide (buy a shallow dip in the rising trend)

SL = ~5.5% below entry, tucked just under a nearby swing low when that is tighter.
Target = 12% above entry (swing band 10-14% / SL 5-6%). R:R filter = (target-entry)/(entry-SL) >= 2.0
"""
from __future__ import annotations
import logging
import pandas as pd
import yfinance as yf
from shared.tickers import nse

log = logging.getLogger(__name__)

_MIN_RR      = 2.0
_SL_PCT      = 0.055   # ~5.5% below entry as SL (target band 5-6%)
_TGT_PCT     = 0.12    # ~12% above entry as target (band 10-14%)
_PIVOT_LB    = 15      # sessions for the breakout pivot (recent base high)
_EXT_TOL     = 0.03    # CMP within +3% of pivot still counts as "at the pivot"
_BREAK_LO    = 0.99    # breakout band floor = pivot * 0.99
_BREAK_HI    = 1.03    # breakout band ceiling = pivot * 1.03
_PULL_MAX_W  = 0.04    # pullback band at most 4% wide below CMP


def _ema(series: pd.Series, span: int) -> float:
    return float(series.ewm(span=span, adjust=False).mean().iloc[-1])


def compute_key_levels(symbol: str, hist: pd.DataFrame) -> dict | None:
    """
    Compute adaptive entry band, SL, target, R:R for a stock.
    Returns None if R:R < _MIN_RR (pick should be excluded).
    """
    if hist is None or hist.empty or len(hist) < 30:
        return None

    if isinstance(hist.columns, pd.MultiIndex):
        hist = hist.droplevel(1, axis=1)
    hist.columns = [c.capitalize() for c in hist.columns]

    close = hist["Close"].dropna()
    low   = hist["Low"].dropna()
    high  = hist["High"].dropna()

    price = float(close.iloc[-1])
    ema10 = _ema(close, 10)
    ema20 = _ema(close, 20)
    pivot = float(high.tail(_PIVOT_LB).max())   # recent base / breakout high

    near_high = bool(pivot) and price >= pivot * (1 - _EXT_TOL)
    if near_high:
        # at/breaking the fresh-high pivot — breakout band into new highs
        band_kind = "breakout"
        entry_lo = pivot * _BREAK_LO
        entry_hi = pivot * _BREAK_HI
    else:
        # pulled back below the pivot — tight band around CMP, capped under pivot
        band_kind = "pullback"
        entry_hi = min(price * 1.01, pivot if pivot else price * 1.01)
        entry_lo = max(price * (1 - _PULL_MAX_W), ema10 if ema10 < price else price * (1 - _PULL_MAX_W))

    entry_lo = round(entry_lo, 2)
    entry_hi = round(entry_hi, 2)
    entry    = round((entry_lo + entry_hi) / 2, 2)

    # SL: ~6% below entry; tuck just under a nearby swing low if that is tighter
    swing_low = float(low.tail(10).min())
    sl = entry * (1 - _SL_PCT)
    if sl < swing_low * 0.995 < entry:
        sl = swing_low * 0.995
    sl = round(sl, 2)

    target = round(entry * (1 + _TGT_PCT), 2)

    if entry <= sl:
        return None

    rr = round((target - entry) / (entry - sl), 2)
    if rr < _MIN_RR:
        return None

    return {
        "price":     round(price, 2),
        "ema10":     round(ema10, 2),
        "ema20":     round(ema20, 2),
        "pivot":     round(pivot, 2),
        "band_kind": band_kind,
        "entry":     entry,
        "entry_lo":  entry_lo,
        "entry_hi":  entry_hi,
        "sl":        sl,
        "target":    target,
        "rr":        rr,
        "sl_pct":    round((entry - sl) / entry * 100, 1),
        "tgt_pct":   round((target - entry) / entry * 100, 1),
    }


def fetch_and_compute(symbol: str) -> dict | None:
    """Download 3-month OHLCV and compute key levels."""
    try:
        sym = nse(symbol)
        df = yf.download(sym, period="3mo", interval="1d",
                         auto_adjust=True, progress=False, timeout=30)
        return compute_key_levels(symbol, df)
    except Exception as e:
        log.warning("key_levels fetch failed for %s: %s", symbol, e)
        return None
