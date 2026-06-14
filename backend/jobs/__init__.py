"""
APScheduler jobs package for the Crest platform.

`create_scheduler()` and `get_scheduler()` are the public API consumed by main.py
and the scheduler.py shim.
"""
from __future__ import annotations

import os
import logging
from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

log = logging.getLogger(__name__)

_IST = timezone(timedelta(hours=5, minutes=30))
_scheduler: AsyncIOScheduler | None = None


def _is_market_hours() -> bool:
    now = datetime.now(_IST)
    if now.weekday() >= 5:
        return False
    t = now.hour * 60 + now.minute
    return 555 <= t <= 930  # 09:15–15:30


def create_scheduler() -> AsyncIOScheduler:
    global _scheduler

    from jobs.market_data import (
        job_refresh_price_snapshots, job_refresh_market_breadth,
        job_refresh_sector_heatmap, job_refresh_gainers_losers,
        job_refresh_indices, job_refresh_rs_universe, job_ingest_bhavcopy,
        job_refresh_mf_navs,
        job_refresh_us_prices, job_refresh_crypto_prices, job_refresh_fx,
        job_compute_custom_indices,
    )
    from jobs.alerts import (
        job_check_price_alerts, job_scan_price_bands,
        job_check_swing_exits, job_check_entry_active,
    )
    from jobs.digests import (
        job_send_morning_digests, job_send_eod_digests, job_poll_telegram,
    )
    from jobs.scan_jobs import (
        job_run_weekly_scan, job_monthly_basket, job_prune_open_recommendations,
        job_llm_market_note, job_llm_failure_analysis, job_weekend_lab_nudge,
        job_fill_deep_analysis, job_holding_advisory,
        job_refresh_kb, job_poll_order_announcements, job_pre_earnings_digest,
        job_backup_data,
    )
    from jobs.snapshots import job_recompute_portfolio_snapshots, job_cleanup_stale_cache

    s = AsyncIOScheduler(
        timezone="Asia/Kolkata",
        executors={"default": {"type": "threadpool", "max_workers": 20}},
    )

    s.add_job(job_refresh_price_snapshots,       IntervalTrigger(seconds=60),                       id="price_snapshots",    max_instances=1, coalesce=True)
    s.add_job(job_refresh_market_breadth,        CronTrigger(hour="*/4", minute=0),                 id="market_breadth",     max_instances=1, coalesce=True)
    s.add_job(job_refresh_market_breadth,        CronTrigger(hour=15, minute=35),                   id="market_breadth_eod", max_instances=1, coalesce=True)
    s.add_job(job_refresh_sector_heatmap,        IntervalTrigger(minutes=15),                       id="sector_heatmap",     max_instances=1, coalesce=True)
    s.add_job(job_refresh_gainers_losers,        IntervalTrigger(minutes=15),                       id="gainers_losers",     max_instances=1, coalesce=True)
    s.add_job(job_refresh_indices,               IntervalTrigger(minutes=5),                        id="indices",            max_instances=1, coalesce=True)
    s.add_job(job_refresh_rs_universe,           CronTrigger(hour=17, minute=0),                    id="rs_universe",        max_instances=1, coalesce=True)
    s.add_job(job_ingest_bhavcopy,               CronTrigger(hour=17, minute=30),                   id="bhavcopy",           max_instances=1, coalesce=True)
    s.add_job(job_refresh_mf_navs,               CronTrigger(hour=21, minute=0),                    id="mf_navs",            max_instances=1, coalesce=True)
    s.add_job(job_refresh_us_prices,             IntervalTrigger(minutes=30),                       id="us_prices",          max_instances=1, coalesce=True)
    s.add_job(job_refresh_crypto_prices,         IntervalTrigger(hours=1),                          id="crypto_prices",      max_instances=1, coalesce=True)
    s.add_job(job_refresh_fx,                    CronTrigger(hour=18, minute=0),                    id="fx_rate",            max_instances=1, coalesce=True)
    s.add_job(job_recompute_portfolio_snapshots, CronTrigger(hour=16, minute=0),                    id="portfolio_eod",      max_instances=1, coalesce=True)
    s.add_job(job_check_price_alerts,            IntervalTrigger(seconds=30),                       id="price_alerts",       max_instances=1, coalesce=True)
    s.add_job(job_run_weekly_scan,               CronTrigger(hour=21, minute=0),                    id="daily_scan",         max_instances=1, coalesce=True)
    s.add_job(job_monthly_basket,                CronTrigger(day=1, hour=12, minute=0),             id="monthly_basket",     max_instances=1, coalesce=True)
    s.add_job(job_check_entry_active,            IntervalTrigger(minutes=15),                       id="entry_active",       max_instances=1, coalesce=True)
    s.add_job(job_cleanup_stale_cache,           CronTrigger(hour=3, minute=0),                     id="cleanup_cache",      max_instances=1, coalesce=True)
    s.add_job(job_prune_open_recommendations,    CronTrigger(hour=21, minute=30),                   id="trade_pruner",       max_instances=1, coalesce=True)
    s.add_job(job_scan_price_bands,              IntervalTrigger(minutes=60),                       id="price_bands",        max_instances=1, coalesce=True)
    s.add_job(job_check_swing_exits,             IntervalTrigger(seconds=60),                       id="swing_exits",        max_instances=1, coalesce=True)
    s.add_job(job_llm_market_note,               CronTrigger(hour=16, minute=15),                   id="llm_market_note",    max_instances=1, coalesce=True)
    s.add_job(job_llm_failure_analysis,          CronTrigger(hour=17, minute=0),                    id="llm_failure",        max_instances=1, coalesce=True)
    s.add_job(job_fill_deep_analysis,            CronTrigger(hour=21, minute=45),                   id="deep_fill",          max_instances=1, coalesce=True)
    s.add_job(job_holding_advisory,              CronTrigger(hour=17, minute=15),                   id="holding_advisory",   max_instances=1, coalesce=True)
    s.add_job(job_weekend_lab_nudge,             CronTrigger(day_of_week="sat", hour=9, minute=0),  id="weekend_lab_nudge",   max_instances=1, coalesce=True)
    s.add_job(job_refresh_kb,                    CronTrigger(day_of_week="sat", hour=9, minute=5),  id="refresh_kb",          max_instances=1, coalesce=True)
    s.add_job(job_poll_order_announcements,      CronTrigger(hour="10,17", minute=30),              id="order_announcements", max_instances=1, coalesce=True)
    s.add_job(job_pre_earnings_digest,           CronTrigger(hour=8, minute=30),                    id="pre_earnings",        max_instances=1, coalesce=True)
    s.add_job(job_compute_custom_indices,        CronTrigger(hour=22, minute=0),                    id="custom_indices",      max_instances=1, coalesce=True)
    s.add_job(job_backup_data,                   CronTrigger(day_of_week="sun", hour=2, minute=0),  id="backup_data",         max_instances=1, coalesce=True)

    # Gate channel-dependent jobs on env presence
    has_telegram = bool(os.getenv("TELEGRAM_BOT_TOKEN"))
    has_smtp     = bool(os.getenv("SMTP_USER") and os.getenv("SMTP_PASS"))

    if has_telegram or has_smtp:
        s.add_job(job_send_morning_digests, CronTrigger(hour=7,  minute=30), id="morning_digest", max_instances=1, coalesce=True)
        s.add_job(job_send_eod_digests,     CronTrigger(hour=16, minute=30), id="eod_digest",     max_instances=1, coalesce=True)
    else:
        log.info("digest jobs skipped — no TELEGRAM_BOT_TOKEN or SMTP_USER+SMTP_PASS configured")

    if has_telegram:
        s.add_job(job_poll_telegram, IntervalTrigger(seconds=5), id="telegram_poll", max_instances=1, coalesce=True)
    else:
        log.info("telegram_poll skipped — no TELEGRAM_BOT_TOKEN configured")

    _scheduler = s
    return s


def get_scheduler() -> AsyncIOScheduler | None:
    return _scheduler
