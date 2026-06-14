"""
Ingest indices/*.csv (official NSE index constituents) ->
  index_membership(index_type 'broad' for cap-tier indices, else 'sector')
  + industry_master row (kind 'broad'|'sector') so MCW can rank them
  + stock_master momentum enrichment (NOT basic_industry — that stays from chartmaze).

CSV schema matches chartmaze: Stock Name, RS Rating, Market Cap,
1 Month Returns(%), 3 Month Returns(%), % from 52W High.
"""
from __future__ import annotations
import logging
from pathlib import Path
import pandas as pd

from scripts.kb.common import (
    KB_SOURCE_DIR, norm_sym, upsert_stock, upsert_membership, upsert_industry,
    clean_num, now_utc,
)

log = logging.getLogger(__name__)

# Cap-tier (broad) indices; everything else in the folder is a sector index.
_BROAD = {
    "Nifty 50", "Nifty 100", "Nifty 500",
    "Nifty Midcap 150", "Nifty Smallcap 250", "Nifty Midsmallcap 400",
}


def _index_from_filename(path: Path) -> str:
    stem = path.stem
    prefix = "Stocks Data_"
    return stem[len(prefix):].strip() if stem.startswith(prefix) else stem.strip()


def ingest(db, source_dir: Path = KB_SOURCE_DIR, dry_run: bool = False) -> dict:
    folder = source_dir / "indices"
    if not folder.exists():
        log.warning("indices folder not found at %s", folder)
        return {"files": 0, "stocks": 0}
    ts = now_utc()
    files = sorted(folder.glob("Stocks Data_*.csv"))
    n_stocks = 0
    for fp in files:
        index_name = _index_from_filename(fp)
        kind = "broad" if index_name in _BROAD else "sector"
        mtype = kind  # membership index_type mirrors kind for NSE indices
        try:
            df = pd.read_csv(fp)
        except Exception as e:
            log.warning("read failed %s: %s", fp.name, e)
            continue
        if not dry_run:
            upsert_industry(db, index_name, kind=kind, num_stocks=int(len(df)))
        for _, r in df.iterrows():
            sym = norm_sym(r.get("Stock Name", ""))
            if not sym or sym == "NAN":
                continue
            if not dry_run:
                # Enrich momentum fields + mcap, but never set basic_industry here.
                upsert_stock(
                    db, sym,
                    rs_rating_csv=clean_num(r.get("RS Rating")),
                    mcap_cr=clean_num(r.get("Market Cap")),
                    ret_1m_csv=clean_num(r.get("1 Month Returns(%)")),
                    ret_3m_csv=clean_num(r.get("3 Month Returns(%)")),
                    pct_from_52wh_csv=clean_num(r.get("% from 52W High")),
                    csv_updated_at=ts,
                )
                upsert_membership(db, sym, index_name, mtype)
            n_stocks += 1
        if not dry_run:
            db.commit()
    log.info("nse_indices: %d files, %d membership rows", len(files), n_stocks)
    return {"files": len(files), "stocks": n_stocks}
