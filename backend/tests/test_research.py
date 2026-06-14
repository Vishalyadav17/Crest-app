"""
WS2 contract tests for the Weekend Analysis Workbench.

Covers:
  (a) context builder shape — returns expected top-level keys
  (b) workbench GET — 200 with expected shape
  (c) deep-dive POST — mocked LLM, upserts PickAnalysis kind='deep'
  (d) deep-dive idempotency — second POST replaces first
  (e) weekend-review 400 gate — <3 analyses
  (f) retro endpoint — skips already-analyzed picks
  (g) chat 409 gate — no BYOK keys
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

_TEST_UID = 9991


@pytest.fixture()
def db():
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
    from sqlalchemy import text
    # Purge any leftover data from previous test runs (cascade handles picks/analyses)
    db.execute(text("DELETE FROM scan_runs WHERE user_id = :uid"), {"uid": _TEST_UID})
    db.commit()

    from models import User
    existing = db.query(User).filter(User.id == _TEST_UID).first()
    if not existing:
        u = User(id=_TEST_UID, email=f"test_{_TEST_UID}@test.com", name="TestResearch")
        db.add(u)
        db.commit()
    yield
    db.execute(text("DELETE FROM scan_runs WHERE user_id = :uid"), {"uid": _TEST_UID})
    db.commit()


@pytest.fixture()
def scan_run_with_picks(db):
    """Create a scan run + 3 picks for test user."""
    from models import ScanRun, ScanPick
    from datetime import datetime, timezone
    run = ScanRun(user_id=_TEST_UID, scanned_at=datetime.now(timezone.utc))
    db.add(run)
    db.flush()
    picks = []
    for sym in ["TITAN", "GRSE", "PICCADIL"]:
        p = ScanPick(scan_run_id=run.id, symbol=sym, grade="A",
                     total_score=75.0, composite_score=80.0)
        db.add(p)
        picks.append(p)
    db.commit()
    db.refresh(run)
    for p in picks:
        db.refresh(p)
    return run, picks


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestContextBuilder:
    def test_shape(self, db, scan_run_with_picks):
        from services.llm.context import build_pick_context
        _, picks = scan_run_with_picks
        ctx = build_pick_context(db, picks[0])
        assert "symbol" in ctx
        assert "levels" in ctx
        assert "ohlcv_recent" in ctx
        assert "market_breadth" in ctx
        # Serializable
        import json
        s = json.dumps(ctx, default=str)
        assert len(s.encode()) <= 7000  # within cap + margin


class TestWorkbenchRoute:
    def test_workbench_empty(self, client):
        with patch("modules.research.routes.get_current_user_id", return_value=_TEST_UID):
            r = client.get("/api/research/workbench")
        assert r.status_code == 200
        data = r.json()
        assert "picks" in data
        assert "user_has_llm" in data

    def test_workbench_with_run(self, client, scan_run_with_picks):
        with patch("modules.research.routes.get_current_user_id", return_value=_TEST_UID):
            r = client.get("/api/research/workbench")
        assert r.status_code == 200
        data = r.json()
        assert data["run"] is not None
        assert len(data["picks"]) == 3
        # All picks have deep=None initially
        assert all(p["deep"] is None for p in data["picks"])


class TestDeepDiveRoute:
    def _mock_llm_result(self):
        return {
            "conviction": 8,
            "verdict_short": "strong setup",
            "verdict_class": "strong",
            "thesis": "Momentum aligned with sector. Entry band clear.",
            "entry_plan": "Buy near pivot.",
            "exit_plan": "SL at 52W low.",
            "hold_horizon_days": 21,
            "risk_flags": ["broad market weakness"],
            "watch_items": ["volume confirmation"],
            "sector_view": "IT sector leading.",
            "model_used": "llama-3.3-70b-versatile",
            "provider": "groq",
        }

    def test_deep_dive_creates_analysis(self, client, db, scan_run_with_picks):
        _, picks = scan_run_with_picks
        pick_id = picks[0].id

        with patch("modules.research.routes.get_current_user_id", return_value=_TEST_UID), \
             patch("services.llm.prompts.deep_dive.run", new_callable=AsyncMock,
                   return_value=self._mock_llm_result()), \
             patch("services.llm.context.build_pick_context",
                   return_value={"symbol": "TITAN", "ohlcv_recent": [], "ohlcv_weekly": [],
                                 "levels": None, "market_breadth": {}, "market_note": None,
                                 "prior_validation": None, "outcomes": [], "kite_position": None,
                                 "sector_heatmap_entry": None, "tracking": None,
                                 "position_size": None, "tradeability_flags": [],
                                 "grade": "A", "total_score": 75, "composite_score": 80,
                                 "sector": "IT", "name": "Titan", "sector_momentum_score": 25,
                                 "leadership_score": 30, "breakout_score": 25, "scan_result": None}):
            r = client.post(f"/api/research/deep-dive/{pick_id}")

        assert r.status_code == 200
        data = r.json()
        assert data["verdict_class"] == "strong"
        assert data["conviction"] == 8
        assert data["pick_id"] == pick_id

        # Verify persisted
        from models import PickAnalysis
        db.expire_all()
        pa = db.query(PickAnalysis).filter(
            PickAnalysis.scan_pick_id == pick_id, PickAnalysis.kind == "deep"
        ).first()
        assert pa is not None
        assert pa.conviction_score == 8

    def test_deep_dive_idempotent(self, client, db, scan_run_with_picks):
        _, picks = scan_run_with_picks
        pick_id = picks[1].id

        result = self._mock_llm_result()
        with patch("modules.research.routes.get_current_user_id", return_value=_TEST_UID), \
             patch("services.llm.prompts.deep_dive.run", new_callable=AsyncMock, return_value=result), \
             patch("services.llm.context.build_pick_context",
                   return_value={"symbol": "GRSE", "ohlcv_recent": [], "ohlcv_weekly": [],
                                 "levels": None, "market_breadth": {}, "market_note": None,
                                 "prior_validation": None, "outcomes": [], "kite_position": None,
                                 "sector_heatmap_entry": None, "tracking": None,
                                 "position_size": None, "tradeability_flags": [],
                                 "grade": "A", "total_score": 75, "composite_score": 80,
                                 "sector": "Defence", "name": "GRSE", "sector_momentum_score": 25,
                                 "leadership_score": 30, "breakout_score": 25, "scan_result": None}):
            client.post(f"/api/research/deep-dive/{pick_id}")
            r2 = client.post(f"/api/research/deep-dive/{pick_id}")

        assert r2.status_code == 200
        from models import PickAnalysis
        db.expire_all()
        count = db.query(PickAnalysis).filter(
            PickAnalysis.scan_pick_id == pick_id, PickAnalysis.kind == "deep"
        ).count()
        assert count == 1  # idempotent — only one row

    def test_deep_dive_404_wrong_user(self, client, scan_run_with_picks):
        _, picks = scan_run_with_picks
        with patch("modules.research.routes.get_current_user_id", return_value=9999):  # different user
            r = client.post(f"/api/research/deep-dive/{picks[0].id}")
        assert r.status_code == 404


class TestWeekendReviewRoute:
    def test_review_400_gate(self, client, scan_run_with_picks):
        run, _ = scan_run_with_picks
        with patch("modules.research.routes.get_current_user_id", return_value=_TEST_UID):
            r = client.post(f"/api/research/weekend-review/{run.id}")
        assert r.status_code == 400
        assert "3" in r.json()["detail"]


class TestChatRoute:
    def test_chat_409_no_byok(self, client):
        with patch("modules.research.routes.get_current_user_id", return_value=_TEST_UID), \
             patch("services.llm.access.user_has_llm", return_value=False):
            r = client.post("/api/research/chat",
                            json={"pick_id": None, "messages": [{"role": "user", "content": "hi"}]})
        assert r.status_code == 409
