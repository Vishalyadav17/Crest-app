"""
NSE corporate announcements fetcher.

Endpoint: https://www.nseindia.com/api/corporate-announcements?index=equities&symbol=X
  - No session warmup needed (home returns 403 but API works directly)
  - Response: list of objects with ann_dt, desc, attchmntText, sort_date, seq_id, symbol
  - Filter by desc for order-win subjects; extract value from attchmntText via regex

Date params: from_date=DD-MM-YYYY&to_date=DD-MM-YYYY (both optional but use both for incremental polls)
"""
from __future__ import annotations

import logging
import re
from datetime import date, datetime

import requests

log = logging.getLogger(__name__)

_BASE = "https://www.nseindia.com/api/corporate-announcements"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.nseindia.com/",
}

# desc values that signal order wins (exact or substring match, case-insensitive)
_ORDER_DESC_KEYWORDS = {
    "bagging", "receiving of orders", "order", "contract", "loi",
    "letter of award", "letter of intent", "award",
}

# regex patterns to extract monetary value (₹ or Rs) in crore, lakh, million, billion
_VALUE_RE = re.compile(
    r"(?:₹|rs\.?\s*)(\d[\d,\.]*)\s*(crore|cr\.?|lakh|lac|million|mn|bn|billion)",
    re.IGNORECASE,
)

_LAKH_FACTOR = 1 / 100       # lakh → crore
_MILLION_FACTOR = 1 / 10      # million → crore (1 million ≈ 10 lakh = 0.1 crore)
_BILLION_FACTOR = 100         # billion → crore (1 billion = 100 crore)


def _is_order_win(desc: str) -> bool:
    desc_l = (desc or "").lower()
    return any(kw in desc_l for kw in _ORDER_DESC_KEYWORDS)


def _extract_value(text: str) -> tuple[float | None, str]:
    """Return (value_cr, method) from announcement text. method = 'regex' or 'none'."""
    m = _VALUE_RE.search(text or "")
    if not m:
        return None, "none"
    raw = float(m.group(1).replace(",", ""))
    unit = m.group(2).lower().rstrip(".")
    if unit in ("lakh", "lac"):
        raw *= _LAKH_FACTOR
    elif unit in ("million", "mn"):
        raw *= _MILLION_FACTOR
    elif unit in ("billion", "bn"):
        raw *= _BILLION_FACTOR
    # else already crore
    return round(raw, 4), "regex"


def fetch_announcements(sym: str, from_date: date | None = None, to_date: date | None = None) -> list[dict]:
    """
    Fetch corporate announcements for `sym` from NSE.
    Returns list of raw announcement dicts.
    Raises requests.RequestException on network failure.
    """
    params: dict = {"index": "equities", "symbol": sym}
    if from_date:
        params["from_date"] = from_date.strftime("%d-%m-%Y")
    if to_date:
        params["to_date"] = to_date.strftime("%d-%m-%Y")

    r = requests.get(_BASE, headers=_HEADERS, params=params, timeout=15)
    r.raise_for_status()
    return r.json() or []


def parse_order_wins(raw: list[dict]) -> list[dict]:
    """
    Filter raw NSE announcements to order-win events and extract value.
    Returns list of dicts ready for upsert into OrderAnnouncement.
    """
    results = []
    for item in raw:
        desc = item.get("desc") or ""
        if not _is_order_win(desc):
            continue
        body = (item.get("attchmntText") or "")[:1000]
        value_cr, extraction = _extract_value(body)
        # parse sort_date "YYYY-MM-DD HH:MM:SS"
        sort_date_str = (item.get("sort_date") or "")[:10]
        try:
            ann_date = sort_date_str  # keep as YYYY-MM-DD string
        except Exception:
            ann_date = ""
        attachment_url = item.get("attchmntFile") or ""
        results.append({
            "sym": item.get("symbol") or "",
            "ann_date": ann_date,
            "headline": desc,
            "body_excerpt": body[:500],
            "value_cr": value_cr,
            "extraction": extraction,
            "source_url": attachment_url,
        })
    return results
