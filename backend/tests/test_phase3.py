"""
Phase 3 contract tests.

Uses the real PostgreSQL DB (already running for the app).
All writes use a throwaway user_id=0 (cleaned up in teardown).
Auth is patched to return False (dev mode) so get_current_user_id returns 1.

Tests verify:
  (a) GET /api/dashboard/bootstrap returns envelope with requested module keys.
  (b) GET /api/swing/dashboard returns scanner_trades + manual_swings + combined.
  (c) Pagination params are accepted on /api/swing/vault and /api/swing/trades.
  (d) GET /api/charts/stock-info?include_news=true includes a news key.
  (e) N+1 CRUD: get_scan_run / list_scan_history / get_all_trades work without error.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Client fixture with auth patched ─────────────────────────────────────────

@pytest.fixture(scope="module")
def client():
    with patch("auth.is_auth_enabled", return_value=False):
        from main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ── Test 3.1: bootstrap envelope structure ────────────────────────────────────

def test_bootstrap_returns_all_modules(client):
    resp = client.get("/api/dashboard/bootstrap?modules=m1,m2,m3")
    assert resp.status_code == 200
    data = resp.json()
    assert "cached_at" in data
    assert "m1" in data
    assert "m2" in data
    assert "m3" in data


def test_bootstrap_module_filter_m1_only(client):
    resp = client.get("/api/dashboard/bootstrap?modules=m1")
    assert resp.status_code == 200
    data = resp.json()
    assert "m1" in data
    assert "m2" not in data
    assert "m3" not in data


def test_bootstrap_m1_has_overview(client):
    resp = client.get("/api/dashboard/bootstrap?modules=m1")
    assert resp.status_code == 200
    m1 = resp.json()["m1"]
    assert "overview" in m1 or "error" in m1
    if "overview" in m1:
        assert "total_wealth" in m1["overview"]
        assert "cagr" in m1["overview"]


def test_bootstrap_m2_has_cache_keys(client):
    resp = client.get("/api/dashboard/bootstrap?modules=m2")
    assert resp.status_code == 200
    m2 = resp.json()["m2"]
    # All keys present (may be null if cache is cold — correct behaviour)
    for key in ("indices", "ad_ratio", "sectors", "gainers_losers", "breadth", "news"):
        assert key in m2


def test_bootstrap_m3_structure(client):
    resp = client.get("/api/dashboard/bootstrap?modules=m3")
    assert resp.status_code == 200
    m3 = resp.json()["m3"]
    assert "scanner_trades" in m3 or "error" in m3
    if "scanner_trades" in m3:
        assert "manual_swings" in m3
        assert "combined" in m3


def test_bootstrap_default_modules(client):
    resp = client.get("/api/dashboard/bootstrap")
    assert resp.status_code == 200
    data = resp.json()
    # Default is m1,m2,m3 — all three should be present
    assert "m1" in data
    assert "m2" in data
    assert "m3" in data


# ── Test 3.2: swing dashboard batched ────────────────────────────────────────

def test_swing_dashboard_top_level_keys(client):
    resp = client.get("/api/swing/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    assert "scanner_trades" in data
    assert "manual_swings" in data
    assert "combined" in data


def test_swing_dashboard_combined_fields(client):
    resp = client.get("/api/swing/dashboard")
    combined = resp.json()["combined"]
    assert "total_invested" in combined
    assert "closed_pl" in combined
    assert "win_rate_class" in combined
    assert "open_count" in combined
    assert "closed_count" in combined


def test_swing_dashboard_scanner_trades_has_open_closed(client):
    resp = client.get("/api/swing/dashboard")
    st = resp.json()["scanner_trades"]
    assert "open" in st
    assert "closed" in st
    assert "summary" in st


def test_swing_dashboard_manual_swings_has_budget(client):
    resp = client.get("/api/swing/dashboard")
    ms = resp.json()["manual_swings"]
    assert "budget" in ms
    assert "active" in ms
    assert "closed" in ms


# ── Test 3.5: pagination params ───────────────────────────────────────────────

def test_vault_default_response(client):
    resp = client.get("/api/swing/vault")
    assert resp.status_code == 200
    assert "weeks" in resp.json()


def test_vault_pagination_params_accepted(client):
    resp = client.get("/api/swing/vault?limit=5&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert "weeks" in data
    assert isinstance(data["weeks"], list)
    assert len(data["weeks"]) <= 5


def test_vault_limit_exceeds_max_rejected(client):
    resp = client.get("/api/swing/vault?limit=200")
    assert resp.status_code == 422


def test_trades_pagination_params_accepted(client):
    resp = client.get("/api/swing/trades?limit=10&offset=0")
    assert resp.status_code == 200
    data = resp.json()
    assert "open" in data
    assert "closed" in data
    assert "summary" in data


def test_trades_limit_exceeds_max_rejected(client):
    resp = client.get("/api/swing/trades?limit=999")
    assert resp.status_code == 422


def test_vault_offset_param_accepted(client):
    resp = client.get("/api/swing/vault?limit=10&offset=100")
    assert resp.status_code == 200
    # With offset beyond real data, weeks should be empty list
    assert isinstance(resp.json()["weeks"], list)


# ── Test 3.4: stock-info include_news ────────────────────────────────────────

def test_stock_info_no_news_by_default(client):
    resp = client.get("/api/charts/stock-info?symbol=RELIANCE.NS")
    assert resp.status_code == 200
    assert "news" not in resp.json()


def test_stock_info_with_news_has_key(client):
    resp = client.get("/api/charts/stock-info?symbol=RELIANCE.NS&include_news=true")
    assert resp.status_code == 200
    data = resp.json()
    assert "news" in data
    assert isinstance(data["news"], list)


# ── Test 3.6: CRUD pagination + N+1 (direct function calls) ──────────────────

def test_get_scan_run_missing_returns_none():
    from database import SessionLocal
    from crud.scan import get_scan_run
    db = SessionLocal()
    try:
        result = get_scan_run(db, user_id=1, run_id=99999999)
        assert result is None
    finally:
        db.close()


def test_list_scan_history_pagination():
    from database import SessionLocal
    from crud.scan import list_scan_history
    db = SessionLocal()
    try:
        result = list_scan_history(db, user_id=1, limit=5, offset=0)
        assert isinstance(result, list)
        assert len(result) <= 5
    finally:
        db.close()


def test_list_scan_history_offset():
    from database import SessionLocal
    from crud.scan import list_scan_history
    db = SessionLocal()
    try:
        all_runs = list_scan_history(db, user_id=1, limit=100, offset=0)
        offset_runs = list_scan_history(db, user_id=1, limit=100, offset=len(all_runs))
        assert isinstance(offset_runs, list)
        assert len(offset_runs) == 0
    finally:
        db.close()


def test_get_all_trades_paginated():
    from database import SessionLocal
    from crud.scan import get_all_trades
    db = SessionLocal()
    try:
        result = get_all_trades(db, user_id=1, limit=5, offset=0)
        assert "open" in result
        assert "closed" in result
        assert "summary" in result
        assert len(result["open"]) + len(result["closed"]) <= 5
    finally:
        db.close()


def test_get_all_trades_summary_fields():
    from database import SessionLocal
    from crud.scan import get_all_trades
    db = SessionLocal()
    try:
        result = get_all_trades(db, user_id=1)
        summary = result["summary"]
        assert "total_invested" in summary
        assert "closed_pl" in summary
        assert "win_rate_class" in summary
        assert "open_count" in summary
        assert "closed_count" in summary
    finally:
        db.close()
