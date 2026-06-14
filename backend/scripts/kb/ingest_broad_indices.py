"""
Ingest data/sectors.json -> index_membership(index_type='broad').

Unifies the existing broad/thematic index membership (N50, N500, MIDCAP150,
SMALLCAP250, FMCG, IT, ...) into the single membership table.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path

from scripts.kb.common import norm_sym, upsert_membership

log = logging.getLogger(__name__)

_BACKEND = Path(__file__).parent.parent.parent
_SECTORS = _BACKEND / "data" / "sectors.json"


def ingest(db, dry_run: bool = False) -> dict:
    if not _SECTORS.exists():
        log.warning("sectors.json not found at %s", _SECTORS)
        return {"indices": 0, "rows": 0}
    with open(_SECTORS) as f:
        data = json.load(f)
    rows = 0
    for index_name, syms in data.items():
        for raw in syms:
            sym = norm_sym(raw)
            if not sym:
                continue
            if not dry_run:
                upsert_membership(db, sym, index_name, "broad")
            rows += 1
    if not dry_run:
        db.commit()
    log.info("broad_indices: %d indices, %d membership rows", len(data), rows)
    return {"indices": len(data), "rows": rows}
