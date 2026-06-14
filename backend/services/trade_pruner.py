"""
Nightly trade pruning service — runs at 21:30 IST.
Walks open scanner-recommended trades and marks ones whose thesis broke.

Pruning rules (in priority order):
  sl_hit          — ScanPick.scan_result == 'SL_HIT' (already set by price-alert checker)
  pruned_earnings — bad earnings day (yesterday earnings + day drop ≥ 5%)
  pruned_macro    — sharp day drop (> SHARP_DROP_PCT) in PriceSnapshot
  pruned_news     — LLM news check (max 10 calls per nightly run; skips on NoFreeCapacity)

Marks the pick via ScanPick.scan_result. Idempotent: skips picks already marked.
"""
from __future__ import annotations

import logging
from datetime import datetime, date, timezone

log = logging.getLogger(__name__)

SHARP_DROP_PCT: float = -5.0  # day_change_pct threshold
_NEWS_LLM_BUDGET_PER_RUN = 10


# ── Main entry ─────────────────────────────────────────────────────────────────

def prune_open_recommendations(user_id: int) -> list[dict]:
    """
    Returns list of {pick_id, sym, reason} for picks pruned in this run.
    Safe to call multiple times — already-marked picks are skipped.
    """
    from database import SessionLocal
    from models import ScanPick, ScanRun, PriceSnapshot

    db = SessionLocal()
    try:
        open_picks = (
            db.query(ScanPick)
            .join(ScanRun, ScanPick.scan_run_id == ScanRun.id)
            .filter(
                ScanRun.user_id == user_id,
                ScanPick.scan_result.is_(None),
            )
            .all()
        )

        snap_map = {
            r.sym: r for r in
            db.query(PriceSnapshot).filter(
                PriceSnapshot.sym.in_([p.symbol for p in open_picks])
            ).all()
        }

        results: list[dict] = []
        news_calls_remaining = _NEWS_LLM_BUDGET_PER_RUN

        for pick in open_picks:
            snap = snap_map.get(pick.symbol)
            reason: str | None = None

            if _is_sl_already_hit(pick):
                reason = "sl_hit"
            elif _had_bad_earnings_today(pick.symbol):
                reason = "pruned_earnings"
            elif _sharp_drop(snap):
                reason = "pruned_macro"
            elif news_calls_remaining > 0:
                broke, used_call = _news_indicates_thesis_break(pick.symbol)
                if used_call:
                    news_calls_remaining -= 1
                if broke:
                    reason = "pruned_news"

            if reason:
                pick.scan_result = reason
                results.append({"pick_id": pick.id, "sym": pick.symbol, "reason": reason})
                log.info("pruned pick %s (%s) reason=%s", pick.symbol, pick.id, reason)

        if results:
            db.commit()
            log.info("pruner: %d picks pruned for user %d", len(results), user_id)
        return results
    except Exception:
        db.rollback()
        log.exception("prune_open_recommendations failed for user %d", user_id)
        return []
    finally:
        db.close()


# ── Rule helpers ───────────────────────────────────────────────────────────────

def _is_sl_already_hit(pick) -> bool:
    return pick.scan_result == "SL_HIT"


def _had_bad_earnings_today(sym: str) -> bool:
    """
    True if the stock reported earnings YESTERDAY and dropped ≥5% on the day.
    Uses earnings_calendar cache + price_snapshots.
    """
    try:
        from shared.earnings_calendar import get_next_earnings
        from shared.cache import cache_get

        # Check cache for previously fetched earnings date
        import json as _json
        raw = cache_get(f"earnings|{sym}", 3 * 86400)
        if raw is None:
            return False
        next_date_str = raw.get("next_earnings")
        if not next_date_str:
            return False
        earnings_date = date.fromisoformat(next_date_str)
        yesterday = date.today().replace(day=date.today().day - 1)
        # Simple: if cached earnings date was yesterday
        if earnings_date != yesterday:
            return False

        # Check price drop
        from database import SessionLocal
        from models import PriceSnapshot
        db = SessionLocal()
        try:
            snap = db.query(PriceSnapshot).filter(PriceSnapshot.sym == sym).first()
            if snap and snap.day_change_pct is not None:
                return float(snap.day_change_pct) <= SHARP_DROP_PCT
        finally:
            db.close()
    except Exception as e:
        log.warning("_had_bad_earnings_today %s: %s", sym, e)
    return False


def _sharp_drop(snap) -> bool:
    if snap is None or snap.day_change_pct is None:
        return False
    return float(snap.day_change_pct) <= SHARP_DROP_PCT


def _news_indicates_thesis_break(sym: str) -> tuple[bool, bool]:
    """
    Check if recent news headlines break the swing thesis via LLM.
    Returns (thesis_broken: bool, llm_call_made: bool).

    Fetches headlines for the symbol; if any exist in last 48h, calls LLM.
    Caps at _NEWS_LLM_BUDGET_PER_RUN calls per run (caller enforces).
    """
    try:
        # Reuse charts news fetch (cached 10min separately, safe for pruner)
        import httpx
        import urllib.parse
        from xml.etree import ElementTree as ET
        from datetime import timedelta
        import email.utils

        base = sym.replace(".NS", "").replace("^", "")
        query = urllib.parse.quote(f"{base} NSE stock India")
        url = f"https://news.google.com/rss/search?q={query}&hl=en-IN&gl=IN&ceid=IN:en"
        resp = httpx.get(url, timeout=8, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 (compatible)"})
        root = ET.fromstring(resp.text)

        cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
        recent_headlines: list[str] = []
        for item in root.findall(".//item")[:6]:
            pub = item.findtext("pubDate", "")
            try:
                pub_dt = email.utils.parsedate_to_datetime(pub)
                if pub_dt < cutoff:
                    continue
            except Exception:
                continue
            title = item.findtext("title", "").split(" - ")[0].strip()
            if title:
                recent_headlines.append(title)

        if not recent_headlines:
            return False, False

        # LLM call
        import asyncio
        from services.llm.router import chat

        prompt = (
            f"Symbol: {sym}\n"
            f"Headlines (last 48h):\n" +
            "\n".join(f"- {h}" for h in recent_headlines) +
            "\n\nDo these headlines structurally break a short-term momentum-swing thesis? "
            "Reply ONLY with JSON: {\"break\": true/false, \"reason\": \"<one sentence>\"}"
        )
        messages = [
            {"role": "system", "content": "You are a swing-trade risk analyst. Answer in JSON only."},
            {"role": "user", "content": prompt},
        ]

        result = asyncio.run(
            chat(messages, task="swing_failure", tier="system", json_mode=True)
        )
        if isinstance(result, dict) and result.get("break"):
            log.info("news thesis-break for %s: %s", sym, result.get("reason", ""))
            return True, True
        return False, True

    except Exception as e:
        log.warning("_news_indicates_thesis_break %s: %s", sym, e)
        return False, False
