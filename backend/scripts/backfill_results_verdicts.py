"""One-time backfill: close missed/flat picks + regenerate outcome-aware verdicts & reviews.

Run once after the accuracy fixes land:
    .venv/bin/python -m scripts.backfill_results_verdicts

Steps per user:
  1. breach sweep   — close picks that hit SL/target while the server was down
  2. month-end close — TIME_EXIT untraded picks whose basket month is over (Craftsman etc.)
  3. reconcile      — winner/failure verdict per closed pick + outcome-aware ScanReview
"""
from __future__ import annotations

import asyncio
import logging

logging.basicConfig(level=logging.INFO)


async def main() -> None:
    from database import SessionLocal
    from models import User, ScanRun
    from services.breach_sweep import sweep_user_open_runs
    from services.month_close import time_exit_user_past_months
    from services.verdict_reconcile import reconcile_run

    db = SessionLocal()
    try:
        for u in db.query(User).all():
            swept = sweep_user_open_runs(db, u.id)
            timed = time_exit_user_past_months(db, u.id)
            print(f"user {u.id}: swept={swept} time_exit={timed}")
            for run in db.query(ScanRun).filter(ScanRun.user_id == u.id).all():
                counts = await reconcile_run(db, run)
                print(f"  run {run.id} ({run.scanned_at:%Y-%m}): {counts}")
    finally:
        db.close()


if __name__ == "__main__":
    asyncio.run(main())
