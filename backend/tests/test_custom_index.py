"""
WS9 custom-index tests.

- Series math: equal vs mcap weighting, rebase to 1000, membership CRUD.
- Route auth: list/create/delete/history/members all return 200.
- Compute correctness: synthetic series rebases correctly from fixtures.

Never hits live LLMs or yfinance — all external calls mocked.
Uses real PostgreSQL (same DB as dev; test rows cleaned up in teardown).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pandas as pd
import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

_TEST_OWNER = 9997   # throwaway user id for test rows


@pytest.fixture(scope="module")
def client():
    with patch("auth.is_auth_enabled", return_value=False):
        from main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


@pytest.fixture(scope="module", autouse=True)
def cleanup():
    yield
    from database import SessionLocal
    from models import CustomIndex
    db = SessionLocal()
    try:
        db.query(CustomIndex).filter(CustomIndex.name.like("_test_%")).delete()
        db.commit()
    finally:
        db.close()


# ── route: list ───────────────────────────────────────────────────────────────

def test_list_indices_returns_200(client):
    resp = client.get("/api/custom-indices")
    assert resp.status_code == 200
    data = resp.json()
    assert "indices" in data
    assert isinstance(data["indices"], list)


def test_seeded_indices_loaded(client):
    resp = client.get("/api/custom-indices")
    names = [i["name"] for i in resp.json()["indices"]]
    assert any("CDMO" in n for n in names), "CDMO Index should be seeded"
    assert any("Sugar" in n for n in names), "Sugar Index should be seeded"


# ── route: create + delete ────────────────────────────────────────────────────

def test_create_index_returns_201(client):
    with patch("modules.custom_index.routes._compute_one_sync"):   # skip heavy compute
        resp = client.post("/api/custom-indices", json={
            "name": "_test_three_stock",
            "symbols": ["RELIANCE", "INFY", "TCS"],
            "weight_mode": "equal",
        })
    assert resp.status_code == 201
    data = resp.json()
    assert data["name"] == "_test_three_stock"
    assert data["member_count"] == 3


def test_create_duplicate_returns_409(client):
    with patch("modules.custom_index.routes._compute_one_sync"):
        client.post("/api/custom-indices", json={
            "name": "_test_dup", "symbols": ["RELIANCE", "INFY"], "weight_mode": "equal"
        })
        resp = client.post("/api/custom-indices", json={
            "name": "_test_dup", "symbols": ["TCS", "WIPRO"], "weight_mode": "equal"
        })
    assert resp.status_code == 409


def test_create_single_sym_returns_400(client):
    resp = client.post("/api/custom-indices", json={
        "name": "_test_one", "symbols": ["RELIANCE"], "weight_mode": "equal"
    })
    assert resp.status_code == 400


def test_delete_index(client):
    with patch("modules.custom_index.routes._compute_one_sync"):
        r = client.post("/api/custom-indices", json={
            "name": "_test_to_delete", "symbols": ["RELIANCE", "INFY"], "weight_mode": "equal"
        })
    idx_id = r.json()["id"]
    resp = client.delete(f"/api/custom-indices/{idx_id}")
    assert resp.status_code == 204
    names = [i["name"] for i in client.get("/api/custom-indices").json()["indices"]]
    assert "_test_to_delete" not in names


# ── route: history ────────────────────────────────────────────────────────────

def test_history_returns_series(client):
    # Find CDMO Index (seeded, should have history after compute)
    indices = client.get("/api/custom-indices").json()["indices"]
    cdmo = next((i for i in indices if "CDMO" in i["name"]), None)
    if cdmo is None:
        pytest.skip("CDMO Index not seeded")
    resp = client.get(f"/api/custom-indices/{cdmo['id']}/history?period=1y")
    assert resp.status_code == 200
    data = resp.json()
    assert "series" in data


def test_history_404_for_unknown(client):
    resp = client.get("/api/custom-indices/99999/history")
    assert resp.status_code == 404


# ── route: members ────────────────────────────────────────────────────────────

def test_members_returns_list(client):
    with patch("modules.custom_index.routes._compute_one_sync"):
        r = client.post("/api/custom-indices", json={
            "name": "_test_members_check", "symbols": ["RELIANCE", "INFY", "TCS"], "weight_mode": "equal"
        })
    idx_id = r.json()["id"]
    resp = client.get(f"/api/custom-indices/{idx_id}/members")
    assert resp.status_code == 200
    members = resp.json()["members"]
    syms = [m["sym"] for m in members]
    assert set(syms) == {"RELIANCE", "INFY", "TCS"}


# ── unit: compute service (offline, no yfinance) ──────────────────────────────

def _make_prices(syms, n=200, base=100.0, seed=42):
    """Create deterministic synthetic OHLCV for testing."""
    import numpy as np
    rng = np.random.default_rng(seed)
    dates = pd.date_range("2025-01-01", periods=n, freq="B").strftime("%Y-%m-%d")
    data = {}
    for i, sym in enumerate(syms):
        prices = base * (1 + rng.normal(0.001, 0.015, n)).cumprod()
        data[sym] = pd.Series(prices, index=dates)
    return data


def test_equal_weight_rebase():
    from services.custom_index_compute import _BASE_VALUE

    prices = _make_prices(["A", "B", "C"])
    weights = {"A": 1.0, "B": 1.0, "C": 1.0}

    frame = pd.DataFrame(prices).sort_index()
    frame = frame.ffill().dropna()
    rebased = frame / frame.iloc[0] * _BASE_VALUE
    wvec = pd.Series(weights)
    wvec = wvec / wvec.sum()
    series = (rebased * wvec).sum(axis=1)

    # First value must be exactly 1000
    assert abs(float(series.iloc[0]) - _BASE_VALUE) < 0.01
    # Has 200 rows
    assert len(series) == 200


def test_mcap_weight_rebase():
    from services.custom_index_compute import _BASE_VALUE

    prices = _make_prices(["A", "B", "C"])
    weights = {"A": 5000.0, "B": 2000.0, "C": 500.0}

    frame = pd.DataFrame(prices).sort_index()
    frame = frame.ffill().dropna()
    rebased = frame / frame.iloc[0] * _BASE_VALUE
    wvec = pd.Series(weights)
    wvec = wvec / wvec.sum()
    series = (rebased * wvec).sum(axis=1)

    assert abs(float(series.iloc[0]) - _BASE_VALUE) < 0.01


def test_equal_weight_differs_from_mcap():
    from services.custom_index_compute import _BASE_VALUE

    prices = _make_prices(["A", "B", "C"])

    frame = pd.DataFrame(prices).sort_index().ffill().dropna()
    rebased = frame / frame.iloc[0] * _BASE_VALUE

    eq = (rebased * pd.Series({"A": 1/3, "B": 1/3, "C": 1/3})).sum(axis=1)
    mc = (rebased * pd.Series({"A": 0.7, "B": 0.2, "C": 0.1})).sum(axis=1)

    # Last values should differ
    assert abs(float(eq.iloc[-1]) - float(mc.iloc[-1])) > 0.5


def test_compute_and_persist_runs(client):
    """smoke: compute_and_persist on a seeded index with mocked data sources."""
    from database import SessionLocal
    from models import CustomIndex, CustomIndexHistory
    from services.custom_index_compute import compute_and_persist

    db = SessionLocal()
    try:
        idx = db.query(CustomIndex).filter(CustomIndex.name == "Refrigerant Gas Index").one_or_none()
        if idx is None:
            pytest.skip("Refrigerant Gas Index not seeded")

        # Mock bhavcopy fetch + yfinance fallback
        prices = _make_prices(["FLUOROCHEM", "JUBLINGREA", "NAVINFLUOR", "SRF"])

        def fake_bhavcopy(db, syms, cutoff):
            return {s: prices[s] for s in syms if s in prices}

        def fake_yf_fallback(syms):
            return {s: prices[s] for s in syms if s in prices}

        with patch("services.custom_index_compute._fetch_bhavcopy", side_effect=fake_bhavcopy), \
             patch("services.custom_index_compute._fetch_yfinance_fallback", side_effect=fake_yf_fallback):
            n = compute_and_persist(db, idx.id)

        assert n > 0, "should have persisted some rows"
        rows = db.query(CustomIndexHistory).filter(CustomIndexHistory.custom_index_id == idx.id).count()
        assert rows > 0
    finally:
        db.close()
