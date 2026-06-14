"""WS4 tests: global (US) + crypto holdings routes and snapshot bucket math."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent))

_TEST_USER = 2  # dev user id


@pytest.fixture(scope="module")
def client():
    with patch("auth.is_auth_enabled", return_value=False):
        from main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ── Global (US) holdings ──────────────────────────────────────────────────────

def test_global_list_empty(client):
    resp = client.get("/api/portfolio/global")
    assert resp.status_code == 200
    d = resp.json()
    assert "holdings" in d
    assert "summary" in d
    assert isinstance(d["holdings"], list)


def test_global_add_invalid_sym(client):
    with patch("modules.portfolio.routes.asyncio.to_thread", return_value=False):
        resp = client.post("/api/portfolio/global", json={
            "sym": "XXXXNOTREAL", "qty": 1, "avg_price_usd": 100,
        })
    assert resp.status_code == 422


def test_global_add_valid_sym(client):
    with patch("modules.portfolio.routes.asyncio.to_thread", return_value=True):
        resp = client.post("/api/portfolio/global", json={
            "sym": "AAPL", "qty": 2, "avg_price_usd": 150.0, "exchange": "NASDAQ",
        })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_global_list_after_add(client):
    resp = client.get("/api/portfolio/global")
    assert resp.status_code == 200
    d = resp.json()
    syms = [h["sym"] for h in d["holdings"]]
    assert "AAPL" in syms


def test_global_close(client):
    # get the id of AAPL holding
    resp = client.get("/api/portfolio/global")
    holdings = resp.json()["holdings"]
    aapl = next((h for h in holdings if h["sym"] == "AAPL"), None)
    assert aapl is not None
    resp = client.post(f"/api/portfolio/global/{aapl['id']}/close")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    # verify gone from active list
    resp = client.get("/api/portfolio/global")
    syms = [h["sym"] for h in resp.json()["holdings"]]
    assert "AAPL" not in syms


def test_global_close_wrong_user(client):
    resp = client.post("/api/portfolio/global/99999/close")
    assert resp.status_code == 404


# ── Crypto holdings ───────────────────────────────────────────────────────────

def test_crypto_list_empty(client):
    resp = client.get("/api/portfolio/crypto")
    assert resp.status_code == 200
    d = resp.json()
    assert "holdings" in d
    assert isinstance(d["holdings"], list)


def test_crypto_add_invalid_id(client):
    with patch("modules.portfolio.routes.asyncio.to_thread", return_value=False):
        resp = client.post("/api/portfolio/crypto", json={
            "sym": "XYZ", "coingecko_id": "notareal-coin-xyz", "qty": 1, "avg_price_usd": 1,
        })
    assert resp.status_code == 422


def test_crypto_add_valid(client):
    with patch("modules.portfolio.routes.asyncio.to_thread", return_value=True):
        resp = client.post("/api/portfolio/crypto", json={
            "sym": "BTC", "coingecko_id": "bitcoin", "qty": 0.1, "avg_price_usd": 40000.0,
        })
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_crypto_list_after_add(client):
    resp = client.get("/api/portfolio/crypto")
    d = resp.json()
    syms = [h["sym"] for h in d["holdings"]]
    assert "BTC" in syms


def test_crypto_close(client):
    resp = client.get("/api/portfolio/crypto")
    holdings = resp.json()["holdings"]
    btc = next((h for h in holdings if h["sym"] == "BTC"), None)
    assert btc is not None
    resp = client.post(f"/api/portfolio/crypto/{btc['id']}/close")
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    resp = client.get("/api/portfolio/crypto")
    syms = [h["sym"] for h in resp.json()["holdings"]]
    assert "BTC" not in syms


# ── Snapshot bucket math ──────────────────────────────────────────────────────

def test_snapshot_global_crypto_buckets():
    """recompute_portfolio_snapshot fills global_value + crypto_value from snapshots × fx."""
    from database import SessionLocal
    from models import GlobalHolding, CryptoHolding, PriceSnapshot, PortfolioSnapshot
    from services.portfolio_service import recompute_portfolio_snapshot

    db = SessionLocal()
    try:
        # Seed a global holding + snapshot
        gh = GlobalHolding(user_id=_TEST_USER, sym="MSFT", qty=1, avg_price_usd=300, status="active")
        db.add(gh)
        db.flush()

        ps = PriceSnapshot(sym="US:MSFT", ltp=320.0)
        db.add(ps)

        ch = CryptoHolding(user_id=_TEST_USER, sym="ETH", coingecko_id="ethereum", qty=1, avg_price_usd=2000, status="active")
        db.add(ch)
        db.flush()

        cps = PriceSnapshot(sym="CRYPTO:ethereum", ltp=2100.0)
        db.add(cps)
        db.commit()

        snap = recompute_portfolio_snapshot(_TEST_USER, db)
        assert float(snap.global_value) > 0, "global_value should be non-zero"
        assert float(snap.crypto_value) > 0, "crypto_value should be non-zero"
        # global_value = 1 qty × 320 USD × fx (≥84) ≥ 26880
        assert float(snap.global_value) >= 320 * 80, "global_value ≥ 320×80 INR"
        assert float(snap.crypto_value) >= 2100 * 80, "crypto_value ≥ 2100×80 INR"
    finally:
        # Cleanup test rows
        db.query(GlobalHolding).filter(GlobalHolding.sym == "MSFT", GlobalHolding.user_id == _TEST_USER).delete()
        db.query(CryptoHolding).filter(CryptoHolding.sym == "ETH", CryptoHolding.user_id == _TEST_USER).delete()
        db.query(PriceSnapshot).filter(PriceSnapshot.sym.in_(["US:MSFT", "CRYPTO:ethereum"])).delete()
        db.commit()
        db.close()
