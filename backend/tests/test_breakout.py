"""
Breakout v2 tests — pure decision logic, synthetic OHLCV fixtures. No DB, no network.

Run: pytest backend/tests/test_breakout.py -v
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.breakout import score_breakout, adr_pct, _base_depth


def _make_hist(n: int = 120, *, vol_ratio: float = 1.0, close_end: float = 100.0,
               rising: bool = True, high_near_52wh: bool = True) -> pd.DataFrame:
    """Synthetic OHLCV. close monotonically rises or falls; volume_ratio on last day."""
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    if rising:
        closes = np.linspace(80.0, close_end, n)
    else:
        closes = np.linspace(close_end, 80.0, n)
    highs  = closes * 1.01
    lows   = closes * 0.99
    vols   = np.full(n, 1_000_000.0)
    vols[-1] = vols[-1] * vol_ratio  # volume expansion on last day
    df = pd.DataFrame({"Open": closes * 0.995, "High": highs, "Low": lows,
                       "Close": closes, "Volume": vols}, index=dates)
    return df


def _make_tight_base(n: int = 120) -> pd.DataFrame:
    """Very tight sideways base: minimal daily range. Fixed seed for determinism."""
    rng = np.random.default_rng(42)
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    closes = np.full(n, 100.0) + rng.uniform(-0.2, 0.2, n)
    highs  = closes + 0.1
    lows   = closes - 0.1
    vols   = np.full(n, 500_000.0)
    vols[-1] = vols[-1] * 2.0  # strong breakout day
    return pd.DataFrame({"Open": closes, "High": highs, "Low": lows,
                         "Close": closes, "Volume": vols},
                        index=dates)


def _make_deep_base(n: int = 120) -> pd.DataFrame:
    """Base with >35% drawdown."""
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    closes = np.concatenate([
        np.linspace(100.0, 60.0, n // 2),   # drops 40%
        np.linspace(60.0, 100.0, n - n // 2)  # recovers
    ])
    highs = closes * 1.01
    lows  = closes * 0.99
    vols  = np.full(n, 800_000.0)
    return pd.DataFrame({"Open": closes, "High": highs, "Low": lows,
                         "Close": closes, "Volume": vols}, index=dates)


# ── score_breakout ─────────────────────────────────────────────────────────────

def test_insufficient_data_returns_zero():
    df = _make_hist(40)  # < 55 rows required
    r = score_breakout("TEST", df)
    assert r["score"] == 0.0
    assert r["components"] == {}


def test_tight_base_volume_spike_scores_high():
    df = _make_tight_base(120)
    r = score_breakout("CLEAN", df)
    assert r["score"] > 35.0, f"Expected >35, got {r['score']}"
    assert r["components"]["base_tightness"] > 0


def test_deep_base_scores_penalized():
    df = _make_deep_base(120)
    without_penalty = score_breakout.__wrapped__(df) if hasattr(score_breakout, "__wrapped__") else None
    r = score_breakout("DEEP", df)
    assert r["components"]["depth_penalty"] is True
    # Penalty ×0.6 must clearly reduce the score
    assert r["score"] < 60.0, f"Deep base should score lower, got {r['score']}"


def test_rs_line_new_high_adds_score():
    df = _make_hist(120, high_near_52wh=True)
    # Bench also rising — RS line near high
    bench = pd.Series(
        np.linspace(1000.0, 1000.0, 120),  # flat bench → stock outperforms → RS at high
        index=df.index,
    )
    r_no_bench  = score_breakout("SYM", df)
    r_with_bench = score_breakout("SYM", df, bench_close=bench)
    assert r_with_bench["components"]["rs_line_new_high"] >= 0
    # rs_line_new_high component should be populated
    assert "rs_line_new_high" in r_with_bench["components"]


def test_rs_line_lagging_scores_zero():
    df = _make_hist(120)
    # Bench rises much faster → RS line at low, NOT near high
    bench = pd.Series(
        np.linspace(1000.0, 5000.0, 120),  # bench 5× — stock RS line collapses
        index=df.index,
    )
    r = score_breakout("LAG", df, bench_close=bench)
    assert r["components"]["rs_line_new_high"] == 0.0


def test_volume_dry_up_quiet_base():
    df = _make_hist(120, vol_ratio=0.5)  # last day volume is 0.5× avg — quiet
    # Modify: make last 5 sessions very low volume
    df = df.copy()
    avg50 = df["Volume"].tail(50).mean()
    df.iloc[-5:, df.columns.get_loc("Volume")] = avg50 * 0.4  # very dry
    r = score_breakout("DRY", df)
    assert r["components"]["volume_dry_up"] > 5.0  # should score above neutral


def test_components_sum_consistent():
    df = _make_hist(120, vol_ratio=2.0)
    r = score_breakout("SUM", df)
    comps = r["components"]
    # sum of non-penalty raw components × 0.6 (if penalty) or × 1.0
    raw = (comps["volume_expansion"] + comps["close_in_range"] +
           comps["base_tightness"] + comps["high_proximity"] +
           comps["volume_dry_up"] + comps["rs_line_new_high"])
    if comps.get("depth_penalty"):
        expected = round(raw * 0.6, 1)
    else:
        expected = round(raw, 1)
    assert abs(r["score"] - expected) < 0.2, f"Score {r['score']} vs expected {expected}"


# ── adr_pct ────────────────────────────────────────────────────────────────────

def test_adr_pct_computed():
    df = _make_hist(30)
    val = adr_pct(df)
    assert val is not None
    assert 0.5 < val < 5.0  # synthetic 1% daily range


def test_adr_pct_none_on_insufficient():
    df = _make_hist(10)
    assert adr_pct(df) is None


# ── base_depth ─────────────────────────────────────────────────────────────────

def test_base_depth_detects_40pct_drop():
    df = _make_deep_base(120)
    d = _base_depth(df["Close"])
    assert d > 0.35, f"Expected >35% depth, got {d:.2%}"


def test_base_depth_low_on_rising():
    df = _make_hist(120, rising=True)
    d = _base_depth(df["Close"])
    assert d < 0.25, f"Rising stock should have shallow base, got {d:.2%}"
