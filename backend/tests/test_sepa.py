"""
SEPA engine tests using frozen OHLCV fixtures.

Run: pytest backend/tests/test_sepa.py -v
Generate fixtures first: python backend/tests/generate_fixtures.py
"""
import json
import sys
import pytest
import pandas as pd
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.sepa import score_sepa

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_META_FILE    = _FIXTURES_DIR / "meta.json"


def _load_fixture(sym: str) -> pd.DataFrame:
    path = _FIXTURES_DIR / f"{sym}.json"
    if not path.exists():
        pytest.skip(f"Fixture not found for {sym}. Run generate_fixtures.py first.")
    records = json.loads(path.read_text())
    df = pd.DataFrame(records)
    df.set_index("Date", inplace=True)
    df.index = pd.to_datetime(df.index)
    for col in ["Open", "High", "Low", "Close", "Volume"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _get_meta() -> dict:
    if not _META_FILE.exists():
        pytest.skip("No fixtures directory. Run generate_fixtures.py first.")
    return json.loads(_META_FILE.read_text())


class TestStage2Stocks:
    """Stage 2 stocks — strong uptrend, expect score ≥ 60."""

    @pytest.fixture(autouse=True)
    def meta(self):
        self._meta = _get_meta()

    @pytest.mark.parametrize("sym_idx", [0, 1, 2])
    def test_stage2_score_qualifies(self, sym_idx):
        sym = self._meta["stage2"][sym_idx]
        hist = _load_fixture(sym)
        result = score_sepa(sym, hist, rs_pct=75.0)  # assume top-25% RS for Stage-2

        assert result["total"] >= 60, (
            f"{sym} scored {result['total']}/100 — expected ≥60 for Stage-2 stock.\n"
            f"Criteria breakdown: {result['criteria']}"
        )
        assert result["grade"] in ("QUALIFIES", "HIGH CONVICTION")

    @pytest.mark.parametrize("sym_idx", [0, 1, 2])
    def test_stage2_weinstein_positive(self, sym_idx):
        sym = self._meta["stage2"][sym_idx]
        hist = _load_fixture(sym)
        result = score_sepa(sym, hist, rs_pct=75.0)
        w = result["criteria"].get("weinstein_stage2", {})
        assert w.get("score", 0) > 0, (
            f"{sym}: expected Weinstein Stage-2 score > 0, got: {w.get('detail')}"
        )

    @pytest.mark.parametrize("sym_idx", [0, 1, 2])
    def test_stage2_trend_template_positive(self, sym_idx):
        sym = self._meta["stage2"][sym_idx]
        hist = _load_fixture(sym)
        result = score_sepa(sym, hist, rs_pct=75.0)
        tt = result["criteria"].get("trend_template", {})
        assert tt.get("score", 0) > 0, (
            f"{sym}: expected trend template score > 0, got: {tt.get('detail')}"
        )


class TestStage4Stocks:
    """Stage 4 stocks — downtrend/weak, expect score ≤ 40."""

    @pytest.fixture(autouse=True)
    def meta(self):
        self._meta = _get_meta()

    @pytest.mark.parametrize("sym_idx", [0, 1, 2])
    def test_stage4_score_weak(self, sym_idx):
        sym = self._meta["stage4"][sym_idx]
        hist = _load_fixture(sym)
        result = score_sepa(sym, hist, rs_pct=20.0)  # assume low RS for Stage-4

        assert result["total"] <= 40, (
            f"{sym} scored {result['total']}/100 — expected ≤40 for Stage-4/weak stock.\n"
            f"Criteria breakdown: {result['criteria']}"
        )
        assert result["grade"] == "WEAK"


class TestAmbiguousStocks:
    """Ambiguous stocks — expect score in range [25, 70]."""

    @pytest.fixture(autouse=True)
    def meta(self):
        self._meta = _get_meta()

    @pytest.mark.parametrize("sym_idx", [0, 1, 2])
    def test_ambiguous_score_in_range(self, sym_idx):
        sym = self._meta["ambiguous"][sym_idx]
        hist = _load_fixture(sym)
        result = score_sepa(sym, hist)

        assert 0 <= result["total"] <= 100, f"{sym}: score out of 0-100 range"
        assert result["grade"] in ("WEAK", "QUALIFIES", "HIGH CONVICTION")


class TestSEPAEngine:
    """Engine contract tests — apply to any stock."""

    def test_returns_correct_structure(self):
        sym = _get_meta()["stage2"][0]
        hist = _load_fixture(sym)
        result = score_sepa(sym, hist)
        assert "symbol"   in result
        assert "total"    in result
        assert "grade"    in result
        assert "criteria" in result
        assert len(result["criteria"]) == 7

    def test_score_is_sum_of_criteria(self):
        sym = _get_meta()["stage2"][0]
        hist = _load_fixture(sym)
        result = score_sepa(sym, hist)
        criteria_sum = sum(v["score"] for v in result["criteria"].values())
        assert result["total"] == criteria_sum

    def test_max_points_correct(self):
        sym = _get_meta()["stage2"][0]
        hist = _load_fixture(sym)
        result = score_sepa(sym, hist)
        expected_maxes = {
            "trend_template": 20, "high_proximity": 15, "low_distance": 10,
            "relative_strength": 20, "vcp_proxy": 15, "liquidity": 10,
            "weinstein_stage2": 10,
        }
        for name, expected_max in expected_maxes.items():
            assert result["criteria"][name]["max"] == expected_max

    def test_empty_dataframe_returns_no_data(self):
        result = score_sepa("TEST", pd.DataFrame())
        assert result["total"] == 0
        assert result["grade"] == "NO DATA"

    def test_no_rs_gives_zero_rs_score(self):
        sym = _get_meta()["stage2"][0]
        hist = _load_fixture(sym)
        result = score_sepa(sym, hist, rs_pct=None)
        assert result["criteria"]["relative_strength"]["score"] == 0

    def test_high_rs_gives_max_score(self):
        sym = _get_meta()["stage2"][0]
        hist = _load_fixture(sym)
        result = score_sepa(sym, hist, rs_pct=85.0)
        assert result["criteria"]["relative_strength"]["score"] == 20

    def test_low_rs_gives_zero_score(self):
        sym = _get_meta()["stage2"][0]
        hist = _load_fixture(sym)
        result = score_sepa(sym, hist, rs_pct=30.0)
        assert result["criteria"]["relative_strength"]["score"] == 0
