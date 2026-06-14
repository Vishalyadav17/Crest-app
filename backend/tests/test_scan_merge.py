"""Survival-of-fittest weekly merge (crud.scan.merge_basket)."""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

_TEST_UID = 9992


@pytest.fixture()
def db():
    from database import SessionLocal
    from sqlalchemy import text
    from models import User
    session = SessionLocal()
    if not session.query(User).filter(User.id == _TEST_UID).first():
        session.add(User(id=_TEST_UID, email=f"merge_{_TEST_UID}@test.local"))
        session.commit()
    session.execute(text("DELETE FROM scan_runs WHERE user_id = :uid"), {"uid": _TEST_UID})
    session.commit()
    yield session
    session.execute(text("DELETE FROM scan_runs WHERE user_id = :uid"), {"uid": _TEST_UID})
    session.commit()
    session.rollback()
    session.close()


def _run_with(db, open_specs, closed_specs=None):
    from models import ScanRun, ScanPick
    run = ScanRun(user_id=_TEST_UID, scanned_at=datetime.now(timezone.utc))
    db.add(run)
    db.flush()
    for sym, comp in open_specs:
        db.add(ScanPick(scan_run_id=run.id, symbol=sym, total_score=comp, composite_score=comp))
    for sym, comp, res in (closed_specs or []):
        db.add(ScanPick(scan_run_id=run.id, symbol=sym, total_score=comp,
                        composite_score=comp, scan_result=res))
    db.commit()
    return run


def _cand(sym, comp):
    return {"symbol": sym, "composite_score": comp, "total": comp, "levels": {}, "criteria": {}}


def test_top_n_survival_and_churn(db):
    from crud.scan import merge_basket
    from models import ScanPick
    run = _run_with(db, [("A", 80), ("B", 70), ("C", 60)])
    res = merge_basket(db, run, [_cand("D", 85), _cand("E", 65)], top_n=3)

    assert res["added"] == ["D"]            # D(85) beats into top-3
    assert res["churned"] == ["C"]          # C(60) drops out; E(65) never entered
    picks = {p.symbol: p.scan_result for p in
             db.query(ScanPick).filter(ScanPick.scan_run_id == run.id).all()}
    assert picks["A"] is None and picks["B"] is None and picks["D"] is None
    assert picks["C"] == "CHURNED"
    assert "E" not in picks                 # losing new candidate is not persisted


def test_dedupe_existing_symbol_not_readded(db):
    from crud.scan import merge_basket
    from models import ScanPick
    run = _run_with(db, [("A", 50)])
    # A re-appears in fresh scan with a higher score → must NOT be inserted twice
    res = merge_basket(db, run, [_cand("A", 99)], top_n=5)
    assert res["added"] == []
    rows = db.query(ScanPick).filter(ScanPick.scan_run_id == run.id,
                                     ScanPick.symbol == "A").all()
    assert len(rows) == 1


def test_closed_picks_excluded_from_pool(db):
    from crud.scan import merge_basket
    from models import ScanPick
    run = _run_with(db, [("A", 80)], closed_specs=[("Z", 100, "SL_HIT")])
    res = merge_basket(db, run, [_cand("D", 90)], top_n=2)
    # pool is A(80)+D(90) only; Z is closed and ignored. Both survive, D added, nothing churned.
    assert res["added"] == ["D"]
    assert res["churned"] == []
    z = db.query(ScanPick).filter(ScanPick.scan_run_id == run.id, ScanPick.symbol == "Z").first()
    assert z.scan_result == "SL_HIT"        # untouched
