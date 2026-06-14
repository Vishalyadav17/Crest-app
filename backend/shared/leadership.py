"""
Leadership score — is this stock a LEADER vs the broad market AND its own sector?

Relative strength of the stock's return over 1M/3M/6M against:
  - the broad benchmark (Nifty 500 MCW or index), and
  - its own sector MCW series (if available).
3M is weighted highest (the IBD/Minervini leadership horizon). Outperformance is
mapped to 0..100 (50 = in line, >50 = leading, <50 = lagging).

Distinct from rs_universe.py (which ranks ABSOLUTE momentum across the universe):
this measures EXCESS return vs specific references — the "sector leader" test.
"""
from __future__ import annotations
import pandas as pd

_WINDOWS = {21: 0.20, 63: 0.50, 126: 0.30}  # trading days -> weight (1M/3M/6M)
_SCALE = 2.0  # +20% excess over a window ≈ 90; -25% ≈ 0


def _ret(close: pd.Series, days: int) -> float | None:
    c = close.dropna()
    if len(c) <= days:
        return None
    a, b = float(c.iloc[-days - 1]), float(c.iloc[-1])
    if a == 0:
        return None
    return (b - a) / a * 100.0


def _excess_score(stock: pd.Series, ref: pd.Series | None) -> float | None:
    if ref is None:
        return None
    num = den = 0.0
    for days, w in _WINDOWS.items():
        rs, rr = _ret(stock, days), _ret(ref, days)
        if rs is None or rr is None:
            continue
        excess = rs - rr
        s = max(0.0, min(100.0, 50.0 + excess * _SCALE))
        num += s * w
        den += w
    return (num / den) if den else None


def score_leadership(sym: str, hist: pd.DataFrame,
                     benchmark_close: pd.Series | None = None,
                     sector_close: pd.Series | None = None) -> dict:
    """0..100. Average of leadership-vs-benchmark and leadership-vs-sector."""
    if hist is None or hist.empty or "Close" not in hist.columns:
        return {"symbol": sym, "score": 0.0, "vs_benchmark": None, "vs_sector": None}
    close = hist["Close"].dropna()

    vs_bench = _excess_score(close, benchmark_close)
    vs_sector = _excess_score(close, sector_close)

    parts = [p for p in (vs_bench, vs_sector) if p is not None]
    score = round(sum(parts) / len(parts), 1) if parts else 0.0
    return {
        "symbol": sym,
        "score": score,
        "vs_benchmark": round(vs_bench, 1) if vs_bench is not None else None,
        "vs_sector": round(vs_sector, 1) if vs_sector is not None else None,
    }
