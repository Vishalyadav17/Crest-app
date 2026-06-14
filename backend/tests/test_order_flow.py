"""
WS12 order-flow tests.

Rules:
  - Real PostgreSQL (no SQLite)
  - All LLM and yfinance calls mocked — never hit live providers
  - Covers: regex extraction, quarter window, score thresholds, CRUD routes
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with patch("auth.is_auth_enabled", return_value=False):
        from main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


@pytest.fixture(scope="module")
def db():
    from database import SessionLocal
    s = SessionLocal()
    yield s
    s.close()


# ── 1. Regex value extraction ─────────────────────────────────────────────────

def test_regex_crore():
    from shared.nse_announcements import _extract_value
    val, method = _extract_value("Company received order worth Rs. 250 crore")
    assert method == "regex"
    assert abs(val - 250.0) < 0.01


def test_regex_cr_abbrev():
    from shared.nse_announcements import _extract_value
    val, method = _extract_value("Value of the award is Rs. 489.98 cr.")
    assert method == "regex"
    assert abs(val - 489.98) < 0.01


def test_regex_lakh():
    from shared.nse_announcements import _extract_value
    val, method = _extract_value("Order of Rs. 5000 lakh")
    assert method == "regex"
    assert abs(val - 50.0) < 0.01  # 5000 lakh = 50 crore


def test_regex_million():
    from shared.nse_announcements import _extract_value
    val, method = _extract_value("USD 100 million deal")  # no rupee symbol → no match
    # only ₹/Rs patterns match
    val2, method2 = _extract_value("Rs 1000 million contract")
    assert method2 == "regex"
    assert abs(val2 - 100.0) < 0.01  # 1000 million / 10 = 100 crore


def test_regex_rupee_symbol():
    from shared.nse_announcements import _extract_value
    val, method = _extract_value("Contract valued at ₹1,200 crore")
    assert method == "regex"
    assert abs(val - 1200.0) < 0.01


def test_regex_no_match():
    from shared.nse_announcements import _extract_value
    val, method = _extract_value("Company has changed its registered office")
    assert method == "none"
    assert val is None


# ── 2. Order-win filter ───────────────────────────────────────────────────────

def test_order_win_filter_desc():
    from shared.nse_announcements import _is_order_win
    assert _is_order_win("Bagging/Receiving of orders/contracts")
    assert _is_order_win("Letter of Award from Ministry")
    assert _is_order_win("Contract Signed")
    assert not _is_order_win("Change in Director(s)")
    assert not _is_order_win("Quarterly Results")


# ── 3. Quarter window math ────────────────────────────────────────────────────

def test_quarter_start_april():
    from services.earnings_setup import _current_quarter_start
    assert _current_quarter_start(date(2026, 4, 15)) == date(2026, 4, 1)
    assert _current_quarter_start(date(2026, 6, 30)) == date(2026, 4, 1)


def test_quarter_start_july():
    from services.earnings_setup import _current_quarter_start
    assert _current_quarter_start(date(2026, 7, 1)) == date(2026, 7, 1)
    assert _current_quarter_start(date(2026, 9, 15)) == date(2026, 7, 1)


def test_quarter_start_october():
    from services.earnings_setup import _current_quarter_start
    assert _current_quarter_start(date(2026, 10, 1)) == date(2026, 10, 1)
    assert _current_quarter_start(date(2026, 12, 31)) == date(2026, 10, 1)


def test_quarter_start_jan():
    from services.earnings_setup import _current_quarter_start
    assert _current_quarter_start(date(2026, 1, 1)) == date(2026, 1, 1)
    assert _current_quarter_start(date(2026, 3, 31)) == date(2026, 1, 1)


# ── 4. Score thresholds ───────────────────────────────────────────────────────

def test_score_strong(db):
    """
    With qtd_orders >= prev_q AND >= guidance → strong.
    Uses mock objects instead of live DB rows.
    """
    from services.earnings_setup import compute_setup
    from unittest.mock import patch, MagicMock

    ann_mock = MagicMock()
    ann_mock.value_cr = 120.0
    ann_mock.ann_date = "2026-04-10"

    sm_mock = MagicMock()
    sm_mock.last_q_revenue_cr = 100.0

    guidance_mock = MagicMock()
    guidance_mock.q_revenue_guidance_cr = 110.0

    with patch("services.earnings_setup._current_quarter_start", return_value=date(2026, 4, 1)), \
         patch.object(db, "query") as mock_query:
        q_mock = MagicMock()
        q_mock.filter.return_value = q_mock
        q_mock.first.side_effect = [sm_mock, guidance_mock]
        q_mock.all.return_value = [ann_mock]
        mock_query.return_value = q_mock

        result = compute_setup(db, "GRSE")

    assert result["score"] == "strong"
    assert result["qtd_orders_cr"] == 120.0
    assert result["vs_prev_q"] is not None and result["vs_prev_q"] >= 1.0


def test_score_building(db):
    from services.earnings_setup import compute_setup
    from unittest.mock import patch, MagicMock

    ann_mock = MagicMock()
    ann_mock.value_cr = 75.0
    ann_mock.ann_date = "2026-04-10"

    sm_mock = MagicMock()
    sm_mock.last_q_revenue_cr = 100.0

    guidance_mock = MagicMock()
    guidance_mock.q_revenue_guidance_cr = 110.0

    with patch("services.earnings_setup._current_quarter_start", return_value=date(2026, 4, 1)), \
         patch.object(db, "query") as mock_query:
        q_mock = MagicMock()
        q_mock.filter.return_value = q_mock
        q_mock.first.side_effect = [sm_mock, guidance_mock]
        q_mock.all.return_value = [ann_mock]
        mock_query.return_value = q_mock

        result = compute_setup(db, "GRSE")

    assert result["score"] == "building"


def test_score_neutral_low(db):
    from services.earnings_setup import compute_setup
    from unittest.mock import patch, MagicMock

    ann_mock = MagicMock()
    ann_mock.value_cr = 20.0
    ann_mock.ann_date = "2026-04-10"

    sm_mock = MagicMock()
    sm_mock.last_q_revenue_cr = 100.0

    guidance_mock = MagicMock()
    guidance_mock.q_revenue_guidance_cr = 100.0

    with patch("services.earnings_setup._current_quarter_start", return_value=date(2026, 4, 1)), \
         patch.object(db, "query") as mock_query:
        q_mock = MagicMock()
        q_mock.filter.return_value = q_mock
        q_mock.first.side_effect = [sm_mock, guidance_mock]
        q_mock.all.return_value = [ann_mock]
        mock_query.return_value = q_mock

        result = compute_setup(db, "GRSE")

    assert result["score"] == "neutral"


def test_score_unknown_no_orders(db):
    from services.earnings_setup import compute_setup
    from unittest.mock import patch, MagicMock

    with patch("services.earnings_setup._current_quarter_start", return_value=date(2026, 4, 1)), \
         patch.object(db, "query") as mock_query:
        q_mock = MagicMock()
        q_mock.filter.return_value = q_mock
        q_mock.first.return_value = None
        q_mock.all.return_value = []
        mock_query.return_value = q_mock

        result = compute_setup(db, "NOORDER")

    assert result["score"] == "unknown"
    assert result["qtd_orders_cr"] == 0.0


# ── 5. API routes ─────────────────────────────────────────────────────────────

def test_order_flow_endpoint_returns_ok(client):
    resp = client.get("/api/settings/order-flow")
    assert resp.status_code == 200
    data = resp.json()
    assert "tracked_syms" in data


def test_guidance_upsert(client):
    resp = client.put(
        "/api/settings/order-flow/guidance/TESTXYZ",
        json={"fy_revenue_guidance_cr": 1000.0, "q_revenue_guidance_cr": 250.0, "guidance_note": "test"},
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_list_announcements_empty(client):
    resp = client.get("/api/settings/order-flow/announcements/NOSTOCK")
    assert resp.status_code == 200
    data = resp.json()
    assert data["sym"] == "NOSTOCK"
    assert data["announcements"] == []


def test_manual_announcement_add(client):
    resp = client.post(
        "/api/settings/order-flow/announcements/TESTXYZ/manual",
        json={
            "ann_date": "2026-04-15",
            "headline": "Bagging/Receiving of orders/contracts",
            "value_cr": 150.0,
            "body_excerpt": "Test order of Rs. 150 crore",
        },
    )
    assert resp.status_code in (200, 409)  # 409 if already exists from prior run


def test_list_announcements_after_add(client):
    resp = client.get("/api/settings/order-flow/announcements/TESTXYZ")
    assert resp.status_code == 200
    data = resp.json()
    assert data["sym"] == "TESTXYZ"


def test_parse_order_wins_filters_correctly():
    from shared.nse_announcements import parse_order_wins
    raw = [
        {
            "symbol": "GRSE", "desc": "Bagging/Receiving of orders/contracts",
            "attchmntText": "Order of Rs. 500 crore for construction.",
            "sort_date": "2026-04-10 10:00:00", "attchmntFile": "https://example.com/doc.pdf",
        },
        {
            "symbol": "GRSE", "desc": "Change in Director(s)",
            "attchmntText": "Director appointment", "sort_date": "2026-04-09 12:00:00", "attchmntFile": "",
        },
    ]
    results = parse_order_wins(raw)
    assert len(results) == 1
    assert results[0]["sym"] == "GRSE"
    assert results[0]["value_cr"] == 500.0
    assert results[0]["extraction"] == "regex"
    assert results[0]["ann_date"] == "2026-04-10"
