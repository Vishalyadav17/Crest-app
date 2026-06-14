"""
Ingest custom-index CSVs -> index_membership(index_type='custom') + is_custom_idx flag.

Drop one CSV per custom basket into <KB_SOURCE_DIR>/custom/. Index name = filename
stem. Symbol column = 'Stock Name' if present, else the first column. Optional
'Market Cap' column enriches mcap_cr. Folder is optional (user adds over time).
"""
from __future__ import annotations
import logging
from pathlib import Path
import pandas as pd

from scripts.kb.common import (
    KB_SOURCE_DIR, norm_sym, upsert_stock, upsert_membership, clean_num, now_utc,
)

log = logging.getLogger(__name__)


def ingest(db, source_dir: Path = KB_SOURCE_DIR, dry_run: bool = False) -> dict:
    folder = source_dir / "custom"
    if not folder.exists():
        log.info("custom/ folder absent (none yet) at %s", folder)
        return {"files": 0, "stocks": 0}
    ts = now_utc()
    files = sorted(folder.glob("*.csv"))
    n = 0
    for fp in files:
        index_name = fp.stem.strip()
        try:
            df = pd.read_csv(fp)
        except Exception as e:
            log.warning("read failed %s: %s", fp.name, e)
            continue
        sym_col = "Stock Name" if "Stock Name" in df.columns else df.columns[0]
        for _, r in df.iterrows():
            sym = norm_sym(r.get(sym_col, ""))
            if not sym or sym == "NAN":
                continue
            if not dry_run:
                fields = {"is_custom_idx": True, "source": "custom", "csv_updated_at": ts}
                mcap = clean_num(r.get("Market Cap"))
                if mcap is not None:
                    fields["mcap_cr"] = mcap
                upsert_stock(db, sym, **fields)
                upsert_membership(db, sym, index_name, "custom")
            n += 1
        if not dry_run:
            db.commit()
    log.info("custom_indices: %d files, %d stock rows", len(files), n)
    return {"files": len(files), "stocks": n}
