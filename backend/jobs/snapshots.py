"""
Snapshot jobs: portfolio EOD recompute, stale-cache cleanup, MarketSnapshotDaily upsert helper.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date

log = logging.getLogger(__name__)


# ── Helper: upsert MarketSnapshotDaily ────────────────────────────────────────

def _upsert_daily_snap(today: str, **kwargs) -> None:
    from database import SessionLocal
    from models import MarketSnapshotDaily

    db = SessionLocal()
    try:
        row = db.query(MarketSnapshotDaily).filter(MarketSnapshotDaily.date == today).first()
        if row is None:
            row = MarketSnapshotDaily(date=today)
            db.add(row)
        for col, val in kwargs.items():
            setattr(row, col, val)
        db.commit()
    finally:
        db.close()


# ── Job: EOD portfolio recompute (daily 16:00) ───────────────────────────────

async def job_recompute_portfolio_snapshots() -> None:
    try:
        await asyncio.to_thread(_sync_recompute_portfolio_snapshots)
    except Exception:
        log.exception("job_recompute_portfolio_snapshots failed")


def _sync_recompute_portfolio_snapshots() -> None:
    from database import SessionLocal
    from models import User
    from services.portfolio_service import recompute_portfolio_snapshot

    db = SessionLocal()
    try:
        users = db.query(User).all()
        for u in users:
            try:
                recompute_portfolio_snapshot(u.id, db)
            except Exception:
                log.exception("portfolio snapshot recompute failed for user %d", u.id)
        log.info("EOD portfolio snapshots recomputed for %d users", len(users))
    finally:
        db.close()


# ── Job: cleanup stale cache (daily 03:00) ────────────────────────────────────

async def job_cleanup_stale_cache() -> None:
    try:
        await asyncio.to_thread(_sync_cleanup_stale_cache)
    except Exception:
        log.exception("job_cleanup_stale_cache failed")


def _sync_cleanup_stale_cache() -> None:
    from shared.cache import cache_clear_stale
    deleted = cache_clear_stale(max_age_seconds=86400 * 7)
    log.info("stale cache cleaned: %d rows deleted", deleted)
