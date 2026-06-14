"""Ingest Industry Analytics.csv -> industry_master (CSV seed: perf, ranks, RRG)."""
from __future__ import annotations
import logging
from pathlib import Path
import pandas as pd

from scripts.kb.common import (
    KB_SOURCE_DIR, upsert_industry, clean_num, clean_int, now_utc,
)

log = logging.getLogger(__name__)

_RRG_COL = "RRG Quadrant(Daily | Nifty 50)"


def ingest(db, source_dir: Path = KB_SOURCE_DIR, dry_run: bool = False) -> int:
    path = source_dir / "Industry Analytics.csv"
    if not path.exists():
        log.warning("Industry Analytics.csv not found at %s", path)
        return 0
    df = pd.read_csv(path)
    ts = now_utc()
    n = 0
    for _, r in df.iterrows():
        name = str(r["Basic Industry"]).strip()
        if not name or name.lower() == "nan":
            continue
        if not dry_run:
            upsert_industry(
                db, name,
                kind="basic_industry",
                num_stocks=clean_int(r.get("Number of Stocks")),
                group_mcap_cr=clean_num(r.get("Group Market Cap")),
                perf_1w=clean_num(r.get("Industry 1W Performance(%)")),
                perf_1m=clean_num(r.get("Industry 1M Performance(%)")),
                perf_3m=clean_num(r.get("Industry 3M Performance(%)")),
                rank_1w=clean_int(r.get("Industry 1W Rank")),
                rank_1m=clean_int(r.get("Industry 1M Rank")),
                rank_3m=clean_int(r.get("Industry 3M Rank")),
                rrg_quadrant=(str(r.get(_RRG_COL)).strip() or None),
                csv_updated_at=ts,
            )
        n += 1
    if not dry_run:
        db.commit()
    log.info("industry_analytics: %d industries", n)
    return n
