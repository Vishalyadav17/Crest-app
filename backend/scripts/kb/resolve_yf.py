"""
Validate every stock_master.sym resolves on yfinance; set yf_ok.

Reuses shared.yfinance_client.get_bulk_daily (chunk 50 + 1s sleep + retry + cache).
Writes a failure report so illiquid/new names that need ticker fixes are visible.
"""
from __future__ import annotations
import logging
from pathlib import Path

from models import StockMaster
from shared.tickers import nse
from shared.yfinance_client import get_bulk_daily

log = logging.getLogger(__name__)

_REPORT = Path(__file__).parent.parent.parent / "data" / "yf_resolution_failures.txt"


def ingest(db, dry_run: bool = False, period: str = "1mo") -> dict:
    syms = [s for (s,) in db.query(StockMaster.sym).all()]
    if not syms:
        return {"total": 0, "ok": 0, "failed": 0}

    ns_map = {nse(s): s for s in syms}
    bulk = get_bulk_daily(list(ns_map.keys()), period=period)

    ok, failed = 0, []
    for sym_ns, sym in ns_map.items():
        df = bulk.get(sym_ns)
        resolved = df is not None and not df.empty and "Close" in df.columns and df["Close"].dropna().shape[0] > 0
        if resolved:
            ok += 1
        else:
            failed.append(sym)
        if not dry_run:
            row = db.query(StockMaster).filter(StockMaster.sym == sym).one_or_none()
            if row is not None:
                row.yf_ok = bool(resolved)
    if not dry_run:
        db.commit()
        _REPORT.write_text("\n".join(sorted(failed)))
    log.info("resolve_yf: %d/%d resolved, %d failed (report: %s)",
             ok, len(syms), len(failed), _REPORT.name)
    return {"total": len(syms), "ok": ok, "failed": len(failed), "failures": failed}
