"""
Position sizing tests — capital protection. Pure math, no fixtures.

Run: pytest backend/tests/test_position_sizing.py -v
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from shared.position_sizing import size_position

_CAP = 650000.0


def test_risk_bound_qty():
    # entry 100, sl 95 → ₹5 risk/share. 1% of 6.5L = ₹6500 budget → 1300 shares,
    # but 15% cap = ₹97500 / 100 = 975 shares → max-pct binds.
    r = size_position(100, 95, 130, capital=_CAP, risk_pct=0.01, max_pct=0.15,
                      mcap_cr=5000, slot_size=None, symbol="X")
    assert r["valid"] is True
    assert r["qty"] == 975
    assert r["binding_cap"] == "max_pct"
    assert r["risk_amount"] == round(975 * 5, 2)
    assert r["rr"] == 6.0


def test_risk_binds_when_stop_is_wide():
    # entry 100, sl 50 → ₹50 risk/share. budget ₹6500 → 130 shares (risk binds).
    r = size_position(100, 50, 200, capital=_CAP, risk_pct=0.01, max_pct=0.15,
                      mcap_cr=5000, symbol="W")
    assert r["qty"] == 130
    assert r["binding_cap"] == "risk"
    assert abs(r["risk_pct_actual"] - 1.0) < 0.05


def test_slot_size_cap_binds():
    r = size_position(100, 95, 130, capital=_CAP, risk_pct=0.01, max_pct=0.15,
                      mcap_cr=5000, slot_size=25000, symbol="S")
    assert r["qty"] == 250  # 25000/100
    assert r["binding_cap"] == "slot_size"


def test_invalid_entry_below_sl():
    r = size_position(100, 105, 130, capital=_CAP, risk_pct=0.01, max_pct=0.15)
    assert r["valid"] is False
    assert r["qty"] == 0
    assert r["order"] is None


def test_mcap_fit_flag():
    fit = size_position(100, 95, 130, capital=_CAP, risk_pct=0.01, max_pct=0.15,
                        mcap_cr=10000, mcap_ceiling_cr=30000)
    big = size_position(100, 95, 130, capital=_CAP, risk_pct=0.01, max_pct=0.15,
                        mcap_cr=80000, mcap_ceiling_cr=30000)
    assert fit["mcap_fit"] is True
    assert big["mcap_fit"] is False


def test_order_is_recommend_only():
    r = size_position(100, 95, 130, capital=_CAP, risk_pct=0.01, max_pct=0.15,
                      mcap_cr=5000, symbol="ORD")
    o = r["order"]
    assert o["side"] == "BUY" and o["product"] == "CNC"
    assert "manually" in o["note"].lower()
