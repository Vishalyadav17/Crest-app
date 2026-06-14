"""
News feed: ET Markets + Moneycontrol + Business Standard RSS.
Cached 30 min.
"""
from __future__ import annotations
import logging
from datetime import timezone
import email.utils
import feedparser
from shared.cache import cache_get, cache_set

log = logging.getLogger(__name__)
_TTL = 1800  # 30 min

_FEEDS = [
    {"name": "ET Markets",      "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms"},
    {"name": "Moneycontrol",    "url": "https://www.moneycontrol.com/rss/marketreports.xml"},
    {"name": "Business Std",    "url": "https://www.business-standard.com/rss/markets-106.rss"},
    {"name": "LiveMint",        "url": "https://www.livemint.com/rss/markets"},
]

_MAX_PER_FEED = 6
_MAX_TOTAL    = 20


def _parse_feed(feed_meta: dict) -> list[dict]:
    items = []
    try:
        parsed = feedparser.parse(feed_meta["url"])
        for entry in parsed.entries[:_MAX_PER_FEED]:
            pub = ""
            try:
                raw_date = entry.get("published", "")
                if raw_date:
                    dt = email.utils.parsedate_to_datetime(raw_date)
                    pub = dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                elif hasattr(entry, "published_parsed") and entry.published_parsed:
                    import time
                    ts = time.mktime(entry.published_parsed)
                    from datetime import datetime
                    pub = datetime.utcfromtimestamp(ts).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception as e:
                log.debug("news date parse failed: %s", e)
            if not pub:
                continue
            items.append({
                "source": feed_meta["name"],
                "title":  entry.get("title", "").strip(),
                "link":   entry.get("link", ""),
                "pub":    pub,
                "summary": entry.get("summary", "")[:200].strip(),
            })
    except Exception as e:
        log.warning("RSS feed failed %s: %s", feed_meta["name"], e)
    return items


def get_news() -> list[dict]:
    key = "market_news"
    cached = cache_get(key, _TTL)
    if cached:
        return cached

    all_items: list[dict] = []
    for feed in _FEEDS:
        all_items.extend(_parse_feed(feed))
        if len(all_items) >= _MAX_TOTAL:
            break

    result = all_items[:_MAX_TOTAL]
    if result:
        cache_set(key, result)
    return result
