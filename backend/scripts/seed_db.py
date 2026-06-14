"""
Seed the Crest database from existing JSON files.
Idempotent — safe to run multiple times.

Usage: python backend/scripts/seed_db.py
"""
from __future__ import annotations
import json
import logging
import sys
from pathlib import Path

# Ensure backend/ is on path
_BACKEND = Path(__file__).parent.parent
sys.path.insert(0, str(_BACKEND))

from database import init_db, SessionLocal
from crud.users import get_or_create_default_user
from crud.stock import seed_from_csv, upsert_stock
from crud.portfolio import upsert_holdings, upsert_portfolio_meta, get_portfolio_meta
from crud.mf import upsert_mf_holdings, upsert_mf_watchpoints
from crud.swings import upsert_active_swings, upsert_closed_swings
from crud.scan import save_scan_run, list_scan_history
from crud.prefs import set_pref, get_dashboard_modules

_DATA_DIR = _BACKEND / "data"

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")


def auto_seed() -> None:
    """Called on app startup. Only seeds if the DB is empty."""
    db = SessionLocal()
    try:
        from models import User
        if db.query(User).count() > 0:
            return  # Already seeded
        log.info("Empty DB detected — running initial seed...")
        _run_seed(db)
    finally:
        db.close()


def _run_seed(db) -> None:
    cfg_path = _BACKEND / "config.json"
    cfg = {}
    if cfg_path.exists():
        with open(cfg_path) as f:
            cfg = json.load(f)

    email = cfg.get("auth", {}).get("allowed_email", "admin@crest.local")
    user_id = get_or_create_default_user(db, email)
    log.info("✓ User: %s (id=%d)", email, user_id)

    # stock_master from nifty500.csv
    csv_path = _DATA_DIR / "nifty500.csv"
    n = seed_from_csv(db, csv_path)
    log.info("✓ StockMaster: %d new stocks from nifty500.csv", n)

    # portfolio.json → equity_holdings + portfolio_meta
    portfolio_path = _DATA_DIR / "portfolio.json"
    if portfolio_path.exists():
        p = json.loads(portfolio_path.read_text())
        all_holdings = p.get("holdings", [])
        t0 = p.get("t_plus_0", [])
        # Tag t+0 entries
        for h in t0:
            h["hold_type"] = "t_plus_0"
        upsert_holdings(db, user_id, all_holdings + t0)
        score_raw = p.get("score", {})
        health = score_raw.get("overall") if isinstance(score_raw, dict) else score_raw
        upsert_portfolio_meta(db, user_id,
                              first_trade_date=p.get("first_trade_date"),
                              as_of=p.get("as_of"),
                              cash=p.get("cash", 0),
                              health_score=health,
                              score_json=json.dumps(score_raw) if isinstance(score_raw, dict) else None)
        log.info("✓ EquityHoldings: %d rows", len(all_holdings) + len(t0))
    else:
        log.warning("portfolio.json not found — skipping equity holdings")

    # mfs.json → mf_holdings + mf_watchpoints
    mf_path = _DATA_DIR / "mfs.json"
    if mf_path.exists():
        mf = json.loads(mf_path.read_text())
        upsert_mf_holdings(db, user_id, mf.get("holdings", []))
        wp = mf.get("watchpoints", {})
        if wp:
            upsert_mf_watchpoints(db, user_id, wp)
        log.info("✓ MFHoldings: %d rows", len(mf.get("holdings", [])))
    else:
        log.warning("mfs.json not found — skipping MF holdings")

    # swings.json → swing_trades + swing_budget preference
    swings_path = _DATA_DIR / "swings.json"
    if swings_path.exists():
        sw = json.loads(swings_path.read_text())
        upsert_active_swings(db, user_id, sw.get("active", []))
        upsert_closed_swings(db, user_id, sw.get("closed", []))
        set_pref(db, user_id, "swing_budget", str(sw.get("budget", 100000)))
        log.info("✓ SwingTrades: %d active, %d closed",
                 len(sw.get("active", [])), len(sw.get("closed", [])))
    else:
        log.warning("swings.json not found — skipping swing trades")

    # scan data — my_holdings list for flagging
    my_holdings = cfg.get("my_holdings", [])

    # last_scan.json → scan_runs + scan_picks
    last_scan_path = _DATA_DIR / "last_scan.json"
    if last_scan_path.exists():
        scan = json.loads(last_scan_path.read_text())
        # Enrich picks with name from stock_master
        _enrich_picks(db, scan.get("picks", []))
        save_scan_run(db, user_id, scan)
        log.info("✓ ScanRun (latest): %d picks", len(scan.get("picks", [])))

    # scan_history/ → additional scan runs
    scan_history_dir = _DATA_DIR / "scan_history"
    history_count = 0
    if scan_history_dir.exists():
        # Load existing scanned_at values to avoid duplicates
        existing = {r["scanned_at"] for r in list_scan_history(db, user_id, limit=500) if r["scanned_at"]}
        for path in sorted(scan_history_dir.glob("week_*.json")):
            try:
                scan = json.loads(path.read_text())
                scanned_at = scan.get("scanned_at", "")
                if scanned_at and str(scanned_at) in existing:
                    continue
                _enrich_picks(db, scan.get("picks", []))
                save_scan_run(db, user_id, scan)
                history_count += 1
            except Exception as e:
                log.warning("Skipping %s: %s", path.name, e)
        log.info("✓ ScanHistory: %d additional runs imported", history_count)

    # Default dashboard modules
    get_dashboard_modules(db, user_id)
    log.info("✓ DashboardModules: defaults created")

    log.info("✅ Seed complete for user_id=%d", user_id)


def _enrich_picks(db, picks: list[dict]) -> None:
    """Add name field to picks from stock_master."""
    from models import StockMaster
    for p in picks:
        sym = p.get("symbol", "")
        if sym and not p.get("name"):
            row = db.query(StockMaster).filter(StockMaster.sym == sym).first()
            if row:
                p["name"] = row.name


if __name__ == "__main__":
    init_db()
    db = SessionLocal()
    try:
        _run_seed(db)
    finally:
        db.close()
