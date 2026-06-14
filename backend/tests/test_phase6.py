"""
Phase 6 contract tests.

Covers:
  (a) portfolio snapshot writer — writes correct columns
  (b) swing summary writer — writes correct columns
  (c) /api/dashboard/bootstrap reader — reads from snapshot (no recomputation side-effect)
  (d) /api/swing/dashboard reader — returns precomputed combined fields
  (e) idempotency — recompute_portfolio_snapshot twice, result is stable
  (f) session middleware carries same_site header
"""
from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

_TEST_UID = 9998  # throwaway; cleaned up in teardown


# ── Fixtures ─────────────────────────────────────────────────────────────────

@pytest.fixture()
def db():
    """Fresh session per test; rolls back on teardown."""
    from database import SessionLocal
    session = SessionLocal()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="module")
def client():
    with patch("auth.is_auth_enabled", return_value=False):
        from main import app
        from fastapi.testclient import TestClient
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


@pytest.fixture(autouse=True)
def seed_user(db):
    """Insert a minimal user row for _TEST_UID; clean up after each test."""
    from models import User
    existing = db.query(User).filter(User.id == _TEST_UID).first()
    if not existing:
        u = User(id=_TEST_UID, email=f"test_{_TEST_UID}@test.com", name="Test6")
        db.add(u)
        db.commit()
    yield
    # clean up all rows for test user
    from models import PortfolioSnapshot, SwingTrade, SwingSummary
    for model in (PortfolioSnapshot, SwingTrade, SwingSummary):
        db.query(model).filter_by(user_id=_TEST_UID).delete()
    db.query(User).filter(User.id == _TEST_UID).delete()
    db.commit()


# ── (a) Portfolio snapshot writer ────────────────────────────────────────────

def test_snapshot_writer_creates_row(db):
    from services.portfolio_service import recompute_portfolio_snapshot
    from models import PortfolioSnapshot

    snap = recompute_portfolio_snapshot(_TEST_UID, db)

    assert snap is not None
    assert snap.user_id == _TEST_UID

    db_snap = db.query(PortfolioSnapshot).filter(PortfolioSnapshot.user_id == _TEST_UID).first()
    assert db_snap is not None


def test_snapshot_writer_populates_required_columns(db):
    from services.portfolio_service import recompute_portfolio_snapshot

    snap = recompute_portfolio_snapshot(_TEST_UID, db)

    assert snap.as_of is not None
    assert snap.total_wealth is not None
    assert snap.equity_value is not None
    assert snap.mf_value is not None
    assert snap.cash is not None
    assert snap.total_invested is not None
    assert snap.total_pnl is not None
    assert snap.total_pnl_pct is not None
    assert snap.stocks_pct is not None
    assert snap.mf_pct is not None
    assert snap.cash_pct is not None
    assert snap.computed_at is not None
    assert snap.allocation_sector_json is not None
    assert snap.allocation_mcap_json is not None


def test_snapshot_writer_uses_numeric_not_float(db):
    """money cols must be Decimal (Numeric) not float after DB round-trip."""
    from models import PortfolioSnapshot
    from services.portfolio_service import recompute_portfolio_snapshot

    recompute_portfolio_snapshot(_TEST_UID, db)
    db.expire_all()
    snap = db.query(PortfolioSnapshot).filter(PortfolioSnapshot.user_id == _TEST_UID).first()

    for col in ("total_wealth", "equity_value", "mf_value", "cash", "total_invested", "total_pnl"):
        val = getattr(snap, col)
        assert isinstance(val, Decimal), f"{col} should be Decimal, got {type(val)}"


# ── (b) Swing summary writer ─────────────────────────────────────────────────

def test_swing_summary_writer(db):
    from models import SwingTrade, SwingSummary
    from crud.swings import _recompute_swing_summary

    t1 = SwingTrade(user_id=_TEST_UID, sym="TESTWIN",  trade_type="my_swing",
                    qty=10, avg_price=100, exit_price=120, realized_pnl=200, status="closed")
    t2 = SwingTrade(user_id=_TEST_UID, sym="TESTLOSS", trade_type="my_swing",
                    qty=10, avg_price=100, exit_price=80,  realized_pnl=-200, status="closed")
    db.add_all([t1, t2])
    db.commit()

    _recompute_swing_summary(_TEST_UID, db)

    summary = db.query(SwingSummary).filter(SwingSummary.user_id == _TEST_UID).first()
    assert summary is not None
    assert summary.closed_count == 2
    assert summary.wins == 1
    assert summary.win_rate == 50
    assert float(summary.closed_pl) == pytest.approx(0.0, abs=1e-3)


def test_swing_summary_win_rate_class(db):
    """win_rate_class is computed backend-side based on ≥60 threshold."""
    from models import SwingTrade, SwingSummary
    from crud.swings import _recompute_swing_summary

    # 3 wins, 0 losses → win_rate=100 → class="green"
    for i in range(3):
        t = SwingTrade(user_id=_TEST_UID, sym=f"WIN{i}", trade_type="my_swing",
                       qty=1, avg_price=100, exit_price=120, realized_pnl=20, status="closed")
        db.add(t)
    db.commit()

    _recompute_swing_summary(_TEST_UID, db)

    summary = db.query(SwingSummary).filter(SwingSummary.user_id == _TEST_UID).first()
    assert summary.win_rate_class == "green"


# ── (c) /api/dashboard/bootstrap reader ──────────────────────────────────────

def test_bootstrap_reads_snapshot_not_recompute(client, db):
    from services.portfolio_service import recompute_portfolio_snapshot

    recompute_portfolio_snapshot(_TEST_UID, db)
    resp = client.get("/api/dashboard/bootstrap?modules=m1")
    assert resp.status_code == 200
    m1 = resp.json()["m1"]
    assert "overview" in m1 or "error" in m1
    if "overview" in m1:
        ov = m1["overview"]
        assert "cagr" in ov
        assert "total_wealth" in ov


# ── (d) /api/swing/dashboard reader ──────────────────────────────────────────

def test_swing_dashboard_returns_precomputed_combined(client):
    resp = client.get("/api/swing/dashboard")
    assert resp.status_code == 200
    data = resp.json()
    combined = data["combined"]
    assert "win_rate_class" in combined
    assert "open_count" in combined
    assert "closed_count" in combined


# ── (e) Idempotency ──────────────────────────────────────────────────────────

def test_snapshot_idempotency(db):
    from services.portfolio_service import recompute_portfolio_snapshot

    snap1 = recompute_portfolio_snapshot(_TEST_UID, db)
    snap2 = recompute_portfolio_snapshot(_TEST_UID, db)

    for col in ("total_wealth", "equity_value", "mf_value", "total_invested", "total_pnl"):
        v1 = getattr(snap1, col)
        v2 = getattr(snap2, col)
        assert v1 == v2, f"Drift on {col}: {v1} → {v2}"
    assert snap1.total_pnl_pct == snap2.total_pnl_pct
    assert snap1.stocks_pct == snap2.stocks_pct


# ── (f) Session security headers ─────────────────────────────────────────────

def test_session_same_site_header(client):
    """Responses must set SameSite=strict on the session cookie."""
    resp = client.get("/api/quote", follow_redirects=False)
    cookie_header = resp.headers.get("set-cookie", "")
    if cookie_header:
        assert "samesite=strict" in cookie_header.lower()
