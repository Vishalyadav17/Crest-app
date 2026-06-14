"""
Breakout quality score (0..100) — how clean is the current breakout/setup?

Components v2 (Minervini VCP playbook + RS-line awareness):
  - volume_expansion  (20): strongest up-day volume vs 50d avg (≥1.5× = full).
  - close_in_range    (15): on that day, where did it close in the day's range.
  - base_tightness    (20): Bollinger-band-width percentile; tighter = better.
  - high_proximity    (15): how close price is to its 52W high.
  - volume_dry_up     (10): 5-session avg vol / 50d avg < 0.7 = quiet base (VCP).
  - rs_line_new_high  (10): RS line (close/bench) within 2% of its 252d high.
  - base_depth_guard  (penalty ×0.6): last base drawdown > 35% = failure-prone.

ADR gate: avg daily range % < 2% → caller adds `low_adr` FLAG via tradeability.
          (not scored here; evaluate() in tradeability.py handles it)
"""
from __future__ import annotations
import logging

import pandas as pd

log = logging.getLogger(__name__)


def _sma(s: pd.Series, w: int) -> pd.Series:
    return s.rolling(w).mean()


def _volume_and_close(hist: pd.DataFrame) -> tuple[float, float]:
    close, high, low, vol = (hist["Close"], hist["High"], hist["Low"], hist["Volume"])
    if len(close) < 55:
        return 0.0, 0.0
    avg50 = float(vol.tail(50).mean())
    if avg50 <= 0:
        return 0.0, 0.0
    look = 10
    recent = hist.tail(look)
    up_days = recent[recent["Close"] > recent["Close"].shift(1)]
    target = up_days if not up_days.empty else recent
    bi = target["Volume"].idxmax()
    ratio = float(hist.loc[bi, "Volume"]) / avg50
    vol_score = min(ratio / 1.5, 1.0) * 20.0  # reweighted: 30 → 20

    d_high, d_low, d_close = float(hist.loc[bi, "High"]), float(hist.loc[bi, "Low"]), float(hist.loc[bi, "Close"])
    rng = d_high - d_low
    pos = (d_close - d_low) / rng if rng > 0 else 0.5
    close_score = max(0.0, min(pos, 1.0)) * 15.0  # reweighted: 20 → 15
    return round(vol_score, 1), round(close_score, 1)


def _base_tightness(close: pd.Series) -> float:
    window = min(126, len(close))
    if window < 40:
        return 0.0
    prices = close.tail(window)
    mid = _sma(prices, 20)
    std = prices.rolling(20).std()
    bbw = ((std * 4) / mid).dropna()
    if bbw.empty:
        return 0.0
    pct_rank = float((bbw <= bbw.iloc[-1]).mean())
    return round((1.0 - pct_rank) * 20.0, 1)  # reweighted: 25 → 20


def _high_proximity(close: pd.Series) -> float:
    window = min(252, len(close))
    hi = float(close.tail(window).max())
    price = float(close.iloc[-1])
    if hi <= 0:
        return 0.0
    pct_from_high = (hi - price) / hi * 100.0
    return round(max(0.0, (1.0 - min(pct_from_high, 15.0) / 15.0)) * 15.0, 1)  # reweighted: 25 → 15


def _volume_dry_up(hist: pd.DataFrame) -> float:
    """
    Minervini VCP signature: volume drying up before breakout.
    5-session avg vol / 50d avg < 0.7 → full 10pts.
    Skip (5pts neutral) if the strongest up-day is within last 3 sessions (already broke out).
    """
    if len(hist) < 55:
        return 5.0
    vol = hist["Volume"]
    avg50 = float(vol.tail(50).mean())
    if avg50 <= 0:
        return 5.0

    # Check if already broke out (strong up-day in last 3 sessions)
    recent3 = hist.tail(3)
    up3 = recent3[recent3["Close"] > recent3["Close"].shift(1)]
    if not up3.empty:
        strong_up = (float(up3["Volume"].max()) / avg50) > 1.5
        if strong_up:
            return 5.0  # neutral — already in breakout move

    avg5 = float(vol.tail(5).mean())
    ratio = avg5 / avg50
    if ratio < 0.7:
        return 10.0
    if ratio < 1.0:
        return round((1.0 - ratio) / 0.3 * 10.0, 1)
    return 0.0


def _rs_line_new_high(close: pd.Series, bench_close: pd.Series | None) -> float:
    """
    RS line = close / bench_close. Full 10pts if RS line within 2% of its 252d high.
    Returns 0.0 if no benchmark supplied.
    """
    if bench_close is None or bench_close.empty:
        return 0.0
    # Align on common dates
    common = close.index.intersection(bench_close.index)
    if len(common) < 20:
        return 0.0
    c = close.reindex(common)
    b = bench_close.reindex(common)
    rs = c / b
    window = min(252, len(rs))
    rs_high = float(rs.tail(window).max())
    rs_now  = float(rs.iloc[-1])
    if rs_high <= 0:
        return 0.0
    pct_from_high = (rs_high - rs_now) / rs_high * 100.0
    return round(max(0.0, (1.0 - min(pct_from_high, 2.0) / 2.0)) * 10.0, 1)


def _base_depth(close: pd.Series) -> float:
    """
    Max drawdown of last base: look back 35–130 sessions from today.
    Returns drawdown as positive fraction (0..1).
    """
    window = min(130, len(close))
    if window < 35:
        return 0.0
    prices = close.tail(window)
    peak = prices.expanding().max()
    dd = ((prices - peak) / peak).min()
    return float(abs(dd))


def adr_pct(hist: pd.DataFrame, days: int = 20) -> float | None:
    """Average Daily Range % over last `days` sessions. None if insufficient data."""
    if hist is None or len(hist) < days:
        return None
    recent = hist.tail(days)
    h, l, c = recent["High"], recent["Low"], recent["Close"].shift(1)
    c = c.fillna(recent["Close"])
    ranges = ((h - l) / c.replace(0, float("nan"))) * 100.0
    valid = ranges.dropna()
    return float(valid.mean()) if len(valid) >= days // 2 else None


def score_breakout(sym: str, hist: pd.DataFrame, bench_close: pd.Series | None = None) -> dict:
    if hist is None or hist.empty or "Close" not in hist.columns or len(hist) < 55:
        return {"symbol": sym, "score": 0.0, "components": {}}
    close = hist["Close"].dropna()
    vol_s, close_s = _volume_and_close(hist)
    base_s  = _base_tightness(close)
    high_s  = _high_proximity(close)
    dry_s   = _volume_dry_up(hist)
    rs_s    = _rs_line_new_high(close, bench_close)

    raw = vol_s + close_s + base_s + high_s + dry_s + rs_s

    # Base depth guard: deep base (>35% drawdown) → multiply final score ×0.6
    depth = _base_depth(close)
    depth_penalty = depth > 0.35
    if depth_penalty:
        log.debug("breakout %s: deep base %.1f%% → penalty ×0.6", sym, depth * 100)
        raw = raw * 0.6

    total = round(raw, 1)

    return {
        "symbol": sym,
        "score": total,
        "components": {
            "volume_expansion": vol_s,
            "close_in_range":   close_s,
            "base_tightness":   base_s,
            "high_proximity":   high_s,
            "volume_dry_up":    dry_s,
            "rs_line_new_high": rs_s,
            "base_depth_pct":   round(depth * 100, 1),
            "depth_penalty":    depth_penalty,
        },
    }
