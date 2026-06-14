"""
Ingest recent_IPOs/Recent IPOs.csv -> mark stock_master.is_ipo + listing_date.

CSV: Stock Name, Listing Date (dd/mm/yyyy), Basic Industry, ranks.
Cutoff (>= 2025-01-01) enforced by the source file itself; we also guard here.
"""
from __future__ import annotations
import logging
from datetime import datetime
from pathlib import Path
import pandas as pd

from scripts.kb.common import KB_SOURCE_DIR, norm_sym, upsert_stock, now_utc

log = logging.getLogger(__name__)

_CUTOFF = datetime(2025, 1, 1)


def _parse_date(raw) -> str | None:
    s = str(raw).strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def ingest(db, source_dir: Path = KB_SOURCE_DIR, dry_run: bool = False) -> int:
    path = source_dir / "recent_IPOs" / "Recent IPOs.csv"
    if not path.exists():
        log.warning("Recent IPOs.csv not found at %s", path)
        return 0
    df = pd.read_csv(path)
    ts = now_utc()
    n = 0
    for _, r in df.iterrows():
        sym = norm_sym(r.get("Stock Name", ""))
        if not sym or sym == "NAN":
            continue
        listing = _parse_date(r.get("Listing Date"))
        if listing and datetime.fromisoformat(listing) < _CUTOFF:
            continue
        industry = str(r.get("Basic Industry", "")).strip() or None
        if not dry_run:
            upsert_stock(
                db, sym,
                is_ipo=True,
                listing_date=listing,
                basic_industry=industry,
                source="recent_ipo",
                csv_updated_at=ts,
            )
        n += 1
    if not dry_run:
        db.commit()
    log.info("recent_ipos: %d IPO stocks flagged", n)
    return n
