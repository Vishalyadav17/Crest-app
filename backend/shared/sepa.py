"""
SEPA scoring engine — 7-criteria Minervini model, recalibrated for Indian mid/smallcaps.
Shared by Module 2 (single-stock UI) and Module 3 (batch Saturday scan).

Usage:
    from shared.sepa import score_sepa
    from shared.yfinance_client import get_daily
    from shared.tickers import nse

    hist = get_daily(nse("POLYCAB"), period="1y")
    result = score_sepa("POLYCAB", hist)
    # result = {"total": 82, "grade": "HIGH CONVICTION", "criteria": {...}}
"""
from __future__ import annotations
import logging
import pandas as pd
import numpy as np

log = logging.getLogger(__name__)

_CRITERIA_WEIGHTS = {
    "trend_template":    20,
    "high_proximity":    15,
    "low_distance":      10,
    "relative_strength": 20,
    "vcp_proxy":         15,
    "liquidity":         10,
    "weinstein_stage2":  10,
}


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()


def _sma(series: pd.Series, window: int) -> pd.Series:
    return series.rolling(window=window).mean()


def _score_trend_template(close: pd.Series) -> tuple[int, str]:
    if len(close) < 210:
        return 0, "insufficient data"
    price = close.iloc[-1]
    sma50  = _sma(close, 50).iloc[-1]
    sma150 = _sma(close, 150).iloc[-1]
    sma200 = _sma(close, 200).iloc[-1]
    sma200_prev = _sma(close, 200).iloc[-21]  # 1 month ago

    checks = [
        price > sma50,
        sma50 > sma150,
        sma150 > sma200,
        sma200 > sma200_prev,  # 200 SMA rising
    ]
    n = sum(checks)
    score = {4: 20, 3: 12, 2: 6, 1: 0, 0: 0}[n]
    detail = f"{n}/4 checks (P>{sma50:.0f}, 50>{sma150:.0f}, 150>{sma200:.0f}, 200↑)"
    return score, detail


def _score_high_proximity(close: pd.Series, high: pd.Series) -> tuple[int, str]:
    if len(close) < 252:
        window = min(252, len(close))
    else:
        window = 252
    high52w = high.tail(window).max()
    price = close.iloc[-1]
    pct_from_high = (high52w - price) / high52w * 100

    if pct_from_high <= 25:
        score, band = 15, f"within {pct_from_high:.1f}% of 52W high"
    elif pct_from_high <= 40:
        score, band = 10, f"{pct_from_high:.1f}% below 52W high"
    else:
        score, band = 0, f"{pct_from_high:.1f}% below 52W high (too far)"
    return score, band


def _score_low_distance(close: pd.Series, low: pd.Series) -> tuple[int, str]:
    if len(close) < 252:
        window = min(252, len(close))
    else:
        window = 252
    low52w = low.tail(window).min()
    price = close.iloc[-1]
    pct_above_low = (price - low52w) / low52w * 100

    if pct_above_low >= 50:
        score, detail = 10, f"{pct_above_low:.1f}% above 52W low"
    elif pct_above_low >= 30:
        score, detail = 7, f"{pct_above_low:.1f}% above 52W low"
    else:
        score, detail = 0, f"only {pct_above_low:.1f}% above 52W low"
    return score, detail


def _score_relative_strength(rs_pct: float | None) -> tuple[int, str]:
    if rs_pct is None:
        return 0, "RS universe not computed (pass rs_universe dict)"
    if rs_pct >= 80:
        return 20, f"RS rank {rs_pct:.1f}th pct (top 20%)"
    if rs_pct >= 50:
        return 10, f"RS rank {rs_pct:.1f}th pct"
    return 0, f"RS rank {rs_pct:.1f}th pct (bottom half)"


def _score_vcp_proxy(close: pd.Series) -> tuple[int, str]:
    """
    True VCP: 3+ consecutive pivot ranges each contracting ≥20% vs prior.
    Falls back to BBW percentile if insufficient pivot data.
    """
    window = min(126, len(close))  # ~6 months
    if window < 40:
        return 0, "insufficient data for VCP"

    prices = close.tail(window).reset_index(drop=True)

    # Find local swing highs/lows (min 5-bar separation)
    def _pivot_highs(s: pd.Series, n: int = 5) -> list[float]:
        out = []
        for i in range(n, len(s) - n):
            if s.iloc[i] == s.iloc[i-n:i+n+1].max():
                out.append(float(s.iloc[i]))
        return out

    def _pivot_lows(s: pd.Series, n: int = 5) -> list[float]:
        out = []
        for i in range(n, len(s) - n):
            if s.iloc[i] == s.iloc[i-n:i+n+1].min():
                out.append(float(s.iloc[i]))
        return out

    highs = _pivot_highs(prices)
    lows  = _pivot_lows(prices)

    # Build contraction ranges: range = high - low for each consecutive pivot pair
    n_contractions = min(len(highs), len(lows))
    if n_contractions >= 3:
        ranges = [highs[i] - lows[i] for i in range(n_contractions) if highs[i] > lows[i]]
        contracting = sum(
            1 for i in range(1, len(ranges))
            if ranges[i] < ranges[i-1] * 0.80  # ≥20% contraction each stage
        )
        if contracting >= 2 and len(ranges) >= 3:
            latest_range_pct = (ranges[-1] / prices.iloc[-1] * 100) if prices.iloc[-1] else 0
            return 15, f"VCP: {contracting}+ contractions, latest range {latest_range_pct:.1f}%"
        if contracting >= 1:
            return 7, f"VCP: partial contraction ({contracting} stage)"

    # Fallback: BBW percentile
    bb_mid = _sma(prices, 20)
    bb_std = prices.rolling(20).std()
    bbw = (bb_std * 4) / bb_mid
    valid_bbw = bbw.dropna()
    if valid_bbw.empty:
        return 0, "BBW computation failed"
    current_bbw = valid_bbw.iloc[-1]
    pct_rank = float((valid_bbw <= current_bbw).mean() * 100)
    if pct_rank <= 20:
        return 15, f"BBW pct rank {pct_rank:.0f}% (tight consolidation)"
    if pct_rank <= 40:
        return 7, f"BBW pct rank {pct_rank:.0f}% (moderate contraction)"
    return 0, f"BBW pct rank {pct_rank:.0f}% (volatility expanding)"


def _detect_pullback_setup(close: pd.Series) -> str:
    """
    Detect 20DMA pullback re-entry setup — the primary swing entry trigger.
    Returns a short human-readable signal string; not a scored criterion.
    """
    if len(close) < 25:
        return ""
    ema20 = _ema(close, 20)
    price = float(close.iloc[-1])
    e20   = float(ema20.iloc[-1])
    pct_from_20 = (price - e20) / e20 * 100

    # Touched 20DMA in last 3 sessions then bounced
    touched = any(
        abs(float(close.iloc[-i]) - float(ema20.iloc[-i])) / float(ema20.iloc[-i]) < 0.02
        for i in range(1, 4)
    )
    bouncing = price > e20 and close.iloc[-1] > close.iloc[-2]

    if touched and bouncing:
        return f"20DMA BOUNCE (price {price:.0f}, EMA20 {e20:.0f})"
    if -2 <= pct_from_20 <= 3:
        return f"AT 20DMA ({pct_from_20:+.1f}%)"
    if pct_from_20 > 3:
        return f"above 20DMA (+{pct_from_20:.1f}%)"
    return f"below 20DMA ({pct_from_20:.1f}%)"


def _score_liquidity(close: pd.Series, volume: pd.Series) -> tuple[int, str]:
    """Avg daily turnover in crores (last 20 sessions)."""
    window = min(20, len(close))
    avg_price = close.tail(window).mean()
    avg_vol = volume.tail(window).mean()
    turnover_cr = (avg_price * avg_vol) / 1e7  # ₹ → crores

    if turnover_cr >= 20:
        return 10, f"₹{turnover_cr:.1f} Cr avg daily turnover"
    if turnover_cr >= 5:
        return 5, f"₹{turnover_cr:.1f} Cr avg daily turnover"
    return 0, f"₹{turnover_cr:.2f} Cr turnover (low liquidity)"


def _score_weinstein_stage2(close: pd.Series) -> tuple[int, str]:
    """30-week EMA (~150 trading days) rising and price above it."""
    if len(close) < 160:
        return 0, "insufficient data for 30W EMA"
    ema150 = _ema(close, 150)
    price = close.iloc[-1]
    ema_now = ema150.iloc[-1]
    ema_prev = ema150.iloc[-21]  # 1 month ago

    stage2 = price > ema_now and ema_now > ema_prev
    if stage2:
        return 10, f"Stage 2: price {price:.0f} > 30W EMA {ema_now:.0f} (↑)"
    if price > ema_now:
        return 0, f"Price above 30W EMA but EMA not rising (Stage 1 late?)"
    return 0, f"Price {price:.0f} below 30W EMA {ema_now:.0f} (Stage 3/4)"


def score_sepa(sym: str, hist: pd.DataFrame, rs_pct: float | None = None) -> dict:
    """
    Score a single stock on the 7-criteria SEPA model.

    Args:
        sym:    Stock symbol (for labelling only)
        hist:   DataFrame with columns Open, High, Low, Close, Volume (daily, at least 1Y)
        rs_pct: Precomputed RS percentile rank (0–100) from rs_universe.py.
                If None, RS criterion scores 0 — always pass this for accurate results.

    Returns:
        {
          "symbol": str,
          "total": int,            # 0–100
          "grade": str,            # HIGH CONVICTION / QUALIFIES / WEAK
          "criteria": {
            "trend_template":    {"score": int, "max": 20, "detail": str},
            "high_proximity":    {"score": int, "max": 15, "detail": str},
            "low_distance":      {"score": int, "max": 10, "detail": str},
            "relative_strength": {"score": int, "max": 20, "detail": str},
            "vcp_proxy":         {"score": int, "max": 15, "detail": str},
            "liquidity":         {"score": int, "max": 10, "detail": str},
            "weinstein_stage2":  {"score": int, "max": 10, "detail": str},
          }
        }
    """
    if hist is None or hist.empty or len(hist) < 50:
        return {"symbol": sym, "total": 0, "grade": "NO DATA", "score_label": "LOW", "score_class": "low", "score_color": "red", "criteria": {}}

    # Normalise column names — yfinance may return MultiIndex or flat
    if isinstance(hist.columns, pd.MultiIndex):
        hist = hist.droplevel(1, axis=1)
    hist.columns = [c.capitalize() for c in hist.columns]

    close  = hist["Close"].dropna()
    high   = hist["High"].dropna()
    low    = hist["Low"].dropna()
    volume = hist["Volume"].dropna()

    scores = {}

    tt_s, tt_d   = _score_trend_template(close)
    scores["trend_template"] = {"score": tt_s, "max": 20, "detail": tt_d}

    hp_s, hp_d = _score_high_proximity(close, high)
    scores["high_proximity"] = {"score": hp_s, "max": 15, "detail": hp_d}

    ld_s, ld_d = _score_low_distance(close, low)
    scores["low_distance"] = {"score": ld_s, "max": 10, "detail": ld_d}

    rs_s, rs_d = _score_relative_strength(rs_pct)
    scores["relative_strength"] = {"score": rs_s, "max": 20, "detail": rs_d}

    vcp_s, vcp_d = _score_vcp_proxy(close)
    scores["vcp_proxy"] = {"score": vcp_s, "max": 15, "detail": vcp_d}

    liq_s, liq_d = _score_liquidity(close, volume)
    scores["liquidity"] = {"score": liq_s, "max": 10, "detail": liq_d}

    ws_s, ws_d = _score_weinstein_stage2(close)
    scores["weinstein_stage2"] = {"score": ws_s, "max": 10, "detail": ws_d}

    total = sum(v["score"] for v in scores.values())
    grade = "HIGH CONVICTION" if total >= 80 else ("QUALIFIES" if total >= 60 else "WEAK")
    score_label = "HIGH" if total >= 80 else ("MID" if total >= 70 else "LOW")
    score_class = "high" if total >= 80 else ("mid" if total >= 70 else "low")
    score_color = "green" if total >= 80 else ("gold" if total >= 60 else "red")

    pullback_signal = _detect_pullback_setup(close)

    return {
        "symbol":        sym,
        "total":         total,
        "grade":         grade,
        "score_label":   score_label,
        "score_class":   score_class,
        "score_color":   score_color,
        "criteria":      scores,
        "pullback_signal": pullback_signal,
    }
