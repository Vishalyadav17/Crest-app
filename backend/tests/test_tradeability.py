"""
Tradeability gate tests — capital protection. Pure decision logic, no fixtures.

Run: pytest backend/tests/test_tradeability.py -v
"""
import sys
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.tradeability import evaluate, OK, FLAGGED, EXCLUDED


def _surv(**kw):
    base = dict(asm_stage=None, gsm_stage=None, esm_stage=None, is_t2t=False,
                circuit_band_pct=None, delivery_pct=None)
    base.update(kw)
    return SimpleNamespace(**base)


def test_clean_name_is_ok():
    r = evaluate("CLEAN", _surv(), turnover_cr=50.0)
    assert r["status"] == OK
    assert r["reasons"] == []


def test_no_surveillance_row_is_ok():
    r = evaluate("UNKNOWN", None, turnover_cr=50.0)
    assert r["status"] == OK
    assert r["inputs"]["surveillance_known"] is False


def test_t2t_hard_excluded():
    r = evaluate("T2T", _surv(is_t2t=True), turnover_cr=50.0)
    assert r["status"] == EXCLUDED
    assert any("T2T" in h for h in r["hard"])


def test_gsm_hard_excluded():
    r = evaluate("GSM", _surv(gsm_stage="Stage 2"), turnover_cr=50.0)
    assert r["status"] == EXCLUDED


def test_esm_stage_two_excluded_stage_one_flagged():
    assert evaluate("E2", _surv(esm_stage="ESM Stage II"), turnover_cr=50.0)["status"] == EXCLUDED
    assert evaluate("E2b", _surv(esm_stage="Stage 2"), turnover_cr=50.0)["status"] == EXCLUDED
    r1 = evaluate("E1", _surv(esm_stage="ESM Stage I"), turnover_cr=50.0)
    assert r1["status"] == FLAGGED


def test_asm_flags_not_excludes():
    r = evaluate("ASM", _surv(asm_stage="LTASM"), turnover_cr=50.0)
    assert r["status"] == FLAGGED
    assert any("ASM" in f for f in r["flags"])


def test_sub_floor_turnover_flags():
    r = evaluate("THIN", _surv(), turnover_cr=0.3, min_turnover_cr=1.0)
    assert r["status"] == FLAGGED
    assert any("turnover" in f for f in r["flags"])


def test_tight_circuit_and_low_delivery_flag():
    r = evaluate("RISKY", _surv(circuit_band_pct=5.0, delivery_pct=10.0), turnover_cr=50.0)
    assert r["status"] == FLAGGED
    assert len(r["flags"]) == 2


def test_hard_exclude_outranks_flags():
    r = evaluate("BOTH", _surv(is_t2t=True, asm_stage="LTASM"), turnover_cr=0.1)
    assert r["status"] == EXCLUDED
    assert r["hard"] and r["flags"]


# ── ADR gate (WS8.2) ──────────────────────────────────────────────────────────

import numpy as np
import pandas as pd


def _make_hist_adr(n: int = 30, daily_range_pct: float = 1.5) -> pd.DataFrame:
    dates = pd.date_range("2025-01-01", periods=n, freq="B")
    closes = np.linspace(100.0, 110.0, n)
    rng = closes * daily_range_pct / 100.0
    highs = closes + rng / 2
    lows  = closes - rng / 2
    return pd.DataFrame({
        "Open": closes, "High": highs, "Low": lows,
        "Close": closes, "Volume": np.ones(n) * 1e6,
    }, index=dates)


def test_low_adr_flags():
    hist = _make_hist_adr(30, daily_range_pct=1.0)  # 1% ADR < 2% threshold
    r = evaluate("DEADMONEY", _surv(), turnover_cr=50.0, hist=hist, min_adr_pct=2.0)
    assert r["status"] == FLAGGED
    assert any("low_adr" in f for f in r["flags"])
    assert r["inputs"]["adr_pct"] is not None
    assert r["inputs"]["adr_pct"] < 2.0


def test_normal_adr_is_ok():
    hist = _make_hist_adr(30, daily_range_pct=3.0)  # 3% ADR > 2%
    r = evaluate("ACTIVE", _surv(), turnover_cr=50.0, hist=hist, min_adr_pct=2.0)
    assert r["status"] == OK
    assert not any("low_adr" in f for f in r["flags"])


def test_no_hist_skips_adr():
    r = evaluate("NOHIST", _surv(), turnover_cr=50.0, hist=None)
    assert r["status"] == OK
    assert r["inputs"]["adr_pct"] is None
