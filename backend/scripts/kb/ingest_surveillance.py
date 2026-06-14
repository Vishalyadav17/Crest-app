"""
Ingest NSE surveillance (ASM / GSM) -> stock_surveillance. CAPITAL PROTECTION.

NSE endpoints are cookie-gated and anti-bot; this is best-effort. On fetch
failure we log and leave existing rows untouched — the tradeability gate treats
MISSING surveillance as "unknown" (flag + warn), never as implicit "clean".

ChartMaze CSVs carry surveillance only as UI glyphs (not in the exported data),
so NSE is the sole source here.
"""
from __future__ import annotations
import logging

from scripts.kb.common import norm_sym, upsert_surveillance

log = logging.getLogger(__name__)

_HOME = "https://www.nseindia.com"
_ASM = "https://www.nseindia.com/api/reportASM"
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/regulations/exchange-surveillance-actions",
}


def _session():
    import requests  # local import: optional dependency for this script
    s = requests.Session()
    s.headers.update(_HEADERS)
    s.get(_HOME, timeout=10)  # bootstrap cookies
    return s


def _fetch_asm(s) -> list[dict]:
    r = s.get(_ASM, timeout=15)
    r.raise_for_status()
    data = r.json()
    # NSE returns {"longterm": {"data": [...]}, "shortterm": {"data": [...]}}
    out = []
    for horizon in ("longterm", "shortterm"):
        block = (data.get(horizon) or {}).get("data") or []
        for row in block:
            sym = row.get("symbol") or row.get("Symbol")
            if sym:
                out.append({"sym": norm_sym(sym), "horizon": horizon,
                            "stage": str(row.get("asmStage") or row.get("stage") or "ASM")})
    return out


def ingest(db, dry_run: bool = False) -> dict:
    try:
        s = _session()
        asm_rows = _fetch_asm(s)
    except Exception as e:
        log.warning("NSE surveillance fetch failed (%s); leaving stock_surveillance unchanged", e)
        return {"asm": 0, "ok": False}

    n = 0
    for row in asm_rows:
        if not dry_run:
            upsert_surveillance(
                db, row["sym"],
                asm_stage=row["stage"],
                is_t2t=("2" in row["stage"]),  # ASM Stage II+ moves to T2T
                source="nse_asm",
            )
        n += 1
    if not dry_run:
        db.commit()
    log.info("surveillance: %d ASM symbols", n)
    return {"asm": n, "ok": True}
