"""
Relative Rotation Graph (RRG) — JdK approximation.

Public JdK formula (internally consistent week-over-week):
  RS(t)       = 100 * industry_index(t) / benchmark(t)
  RS_Ratio(t) = 100 + zscore(RS, window=63)(t)
  RS_Mom(t)   = 100 + zscore(ROC_10(RS_Ratio), window=63)(t)
  quadrant    = Leading(≥100,≥100) | Weakening(≥100,<100)
              | Lagging(<100,<100) | Improving(<100,≥100)

Not the proprietary JdK formula but internally consistent for ranking sectors
week-over-week, which is what the scanner needs.
"""
from __future__ import annotations

import logging

import pandas as pd

log = logging.getLogger(__name__)


def _zscore(s: pd.Series, window: int) -> pd.Series:
    roll = s.rolling(window)
    return (s - roll.mean()) / roll.std().replace(0, float("nan"))


def compute_rrg_point(
    industry_idx: pd.Series,
    benchmark_idx: pd.Series,
    *,
    window: int = 63,
    roc_window: int = 10,
) -> dict | None:
    """
    Compute the latest (RS_Ratio, RS_Mom, quadrant) for one industry series
    vs a benchmark series. Both should be daily closes, common index.

    Returns dict with rs_ratio, rs_mom, quadrant, or None on insufficient data.
    """
    common = industry_idx.index.intersection(benchmark_idx.index)
    if len(common) < window + roc_window + 5:
        return None

    ind = industry_idx.reindex(common).ffill().dropna()
    bm  = benchmark_idx.reindex(common).ffill().dropna()
    common = ind.index.intersection(bm.index)
    ind, bm = ind.reindex(common), bm.reindex(common)

    if len(ind) < window + roc_window:
        return None

    rs = 100.0 * (ind / bm)
    rs_ratio_raw = _zscore(rs, window)

    roc_rs_ratio = rs_ratio_raw.diff(roc_window)
    rs_mom_raw = _zscore(roc_rs_ratio, window)

    rs_ratio = float((100.0 + rs_ratio_raw).iloc[-1])
    rs_mom   = float((100.0 + rs_mom_raw).iloc[-1])

    if pd.isna(rs_ratio) or pd.isna(rs_mom):
        return None

    if rs_ratio >= 100 and rs_mom >= 100:
        quadrant = "Leading"
    elif rs_ratio >= 100 and rs_mom < 100:
        quadrant = "Weakening"
    elif rs_ratio < 100 and rs_mom >= 100:
        quadrant = "Improving"
    else:
        quadrant = "Lagging"

    return {
        "rs_ratio": round(rs_ratio, 3),
        "rs_mom":   round(rs_mom, 3),
        "quadrant": quadrant,
    }


def compute_rrg_trail(
    industry_idx: pd.Series,
    benchmark_idx: pd.Series,
    *,
    weeks: int = 8,
    window: int = 63,
    roc_window: int = 10,
) -> list[dict]:
    """
    Return last `weeks` weekly RRG points (newest last) for storage in rrg_history.
    Each point: {date, rs_ratio, rs_mom, quadrant}.
    """
    common = industry_idx.index.intersection(benchmark_idx.index)
    if len(common) < window + roc_window + weeks * 5:
        pt = compute_rrg_point(industry_idx, benchmark_idx, window=window, roc_window=roc_window)
        if pt is None:
            return []
        import datetime
        return [{**pt, "date": common[-1].strftime("%Y-%m-%d")}]

    ind = industry_idx.reindex(common).ffill().dropna()
    bm  = benchmark_idx.reindex(common).ffill().dropna()
    common = ind.index.intersection(bm.index)
    ind, bm = ind.reindex(common), bm.reindex(common)

    rs = 100.0 * (ind / bm)
    rs_ratio_raw = _zscore(rs, window)
    roc_rs_ratio = rs_ratio_raw.diff(roc_window)
    rs_mom_raw = _zscore(roc_rs_ratio, window)

    rs_ratio_series = 100.0 + rs_ratio_raw
    rs_mom_series   = 100.0 + rs_mom_raw

    # Sample one point per week going back `weeks` weeks from the end
    trail = []
    used_dates = rs_ratio_series.dropna().index
    if len(used_dates) == 0:
        return []

    # Weekly sampling: every 5 trading days
    indices = range(len(used_dates) - 1, max(-1, len(used_dates) - 1 - weeks * 5), -5)
    for i in sorted(indices):
        dt = used_dates[i]
        rr = float(rs_ratio_series.loc[dt])
        rm = float(rs_mom_series.loc[dt])
        if pd.isna(rr) or pd.isna(rm):
            continue
        if rr >= 100 and rm >= 100:
            q = "Leading"
        elif rr >= 100 and rm < 100:
            q = "Weakening"
        elif rr < 100 and rm >= 100:
            q = "Improving"
        else:
            q = "Lagging"
        trail.append({"date": dt.strftime("%Y-%m-%d"), "rs_ratio": round(rr, 3),
                      "rs_mom": round(rm, 3), "quadrant": q})
    trail.sort(key=lambda x: x["date"])
    return trail
