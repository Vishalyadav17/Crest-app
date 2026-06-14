"""
Ingest chartmaze/*.csv -> stock_master enrichment + index_membership(basic_industry).

One file per basic industry; industry name derived from filename. CSV columns:
Stock Name, RS Rating, Market Cap, 1 Month Returns(%), 3 Month Returns(%), % from 52W High.
"""
from __future__ import annotations
import logging
from pathlib import Path
import pandas as pd

from scripts.kb.common import (
    KB_SOURCE_DIR, industry_from_filename, norm_sym,
    upsert_stock, upsert_membership, clean_num, now_utc,
)

log = logging.getLogger(__name__)


def ingest(db, source_dir: Path = KB_SOURCE_DIR, dry_run: bool = False) -> dict:
    folder = source_dir / "chartmaze"
    if not folder.exists():
        log.warning("chartmaze folder not found at %s", folder)
        return {"files": 0, "stocks": 0}
    ts = now_utc()
    files = sorted(folder.glob("Stocks Data_*.csv"))
    n_stocks = 0
    for fp in files:
        industry = industry_from_filename(fp)
        try:
            df = pd.read_csv(fp)
        except Exception as e:
            log.warning("read failed %s: %s", fp.name, e)
            continue
        for _, r in df.iterrows():
            sym = norm_sym(r.get("Stock Name", ""))
            if not sym or sym == "NAN":
                continue
            if not dry_run:
                upsert_stock(
                    db, sym,
                    basic_industry=industry,
                    rs_rating_csv=clean_num(r.get("RS Rating")),
                    mcap_cr=clean_num(r.get("Market Cap")),
                    ret_1m_csv=clean_num(r.get("1 Month Returns(%)")),
                    ret_3m_csv=clean_num(r.get("3 Month Returns(%)")),
                    pct_from_52wh_csv=clean_num(r.get("% from 52W High")),
                    source="chartmaze",
                    csv_updated_at=ts,
                )
                upsert_membership(db, sym, industry, "basic_industry")
            n_stocks += 1
        if not dry_run:
            db.commit()
    log.info("chartmaze: %d files, %d stock rows", len(files), n_stocks)
    return {"files": len(files), "stocks": n_stocks}
