"""
Batch SEPA scorer — wraps shared sepa.py for bulk scanning.
Used by scanner.py for both Pass 1 (sector stocks) and Pass 2 (N500 residual).
"""
from __future__ import annotations
import logging
from pathlib import Path
import pandas as pd
from shared.sepa import score_sepa
from shared.tickers import nse
from shared.rs_universe import compute_universe
from shared.yfinance_client import get_bulk_daily

log = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"
_MIN_SCORE = 60


def _load_n500_symbols() -> list[str]:
    csv = _DATA_DIR / "nifty500.csv"
    if not csv.exists():
        return []
    df = pd.read_csv(csv).dropna(subset=["symbol"])
    return df["symbol"].drop_duplicates().tolist()


def score_stocks_batch(
    symbols: list[str],
    rs_universe: dict[str, float] | None = None,
    min_score: int = _MIN_SCORE,
) -> list[dict]:
    """
    Score a list of NSE symbols in batch.
    Downloads 1Y data, scores each stock via SEPA.

    Args:
        symbols:      NSE symbols WITHOUT .NS suffix
        rs_universe:  Precomputed {symbol: rs_pct_rank} dict. If None, computes it.
        min_score:    Only return stocks with total >= min_score.

    Returns:
        List of score dicts sorted by total score descending.
    """
    if rs_universe is None:
        log.info("Computing RS universe for %d symbols", len(symbols))
        rs_universe = compute_universe(symbols)

    nse_syms = [nse(s) for s in symbols]
    log.info("Bulk downloading %d symbols for SEPA scoring", len(nse_syms))

    bulk = get_bulk_daily(nse_syms, period="1y")
    if not bulk:
        log.error("bulk download returned no data in stock_scorer")
        return []

    results = []
    for sym in symbols:
        sym_ns = nse(sym)
        try:
            hist = bulk.get(sym_ns, pd.DataFrame())
            hist = hist.dropna(how="all")
            if hist.empty or len(hist) < 50:
                continue
            rs_pct = rs_universe.get(sym) if rs_universe else None
            score = score_sepa(sym, hist, rs_pct)
            if score["total"] >= min_score:
                results.append(score)
        except Exception as e:
            log.debug("score failed for %s: %s", sym, e)

    results.sort(key=lambda x: x["total"], reverse=True)
    return results


def get_n500_residual_symbols(exclude: set[str]) -> list[str]:
    """Return Nifty 500 symbols not already in the exclude set (Pass 2)."""
    all_syms = _load_n500_symbols()
    return [s for s in all_syms if s not in exclude]


def _load_microcap_idx_symbols() -> set[str]:
    """Return NIFTY Microcap 250 symbols from DB. Falls back to microcap_ext.json."""
    import json
    try:
        from database import SessionLocal
        from models import StockMaster
        db = SessionLocal()
        try:
            rows = db.query(StockMaster.sym).filter(StockMaster.is_microcap_idx.is_(True)).all()
            if rows:
                return {r.sym for r in rows}
        finally:
            db.close()
    except Exception as e:
        log.warning("DB microcap query failed, falling back to file: %s", e)
    # fallback: microcap_ext.json built by build_microcap_ext.py
    micro_path = _DATA_DIR / "microcap_ext.json"
    if micro_path.exists():
        try:
            with open(micro_path) as f:
                return {entry["symbol"] for entry in json.load(f)}
        except Exception:
            pass
    return set()


def get_microcap_idx_symbols() -> set[str]:
    return _load_microcap_idx_symbols()


def get_extended_universe(exclude: set[str]) -> list[str]:
    """
    Pass 2 universe: N500 + thematic index stocks + NIFTY Microcap 250 (DB-backed).
    """
    import json
    n500 = set(_load_n500_symbols())

    thematic: set[str] = set()
    sectors_path = _DATA_DIR / "sectors.json"
    if sectors_path.exists():
        try:
            with open(sectors_path) as f:
                data = json.load(f)
            for syms in data.values():
                thematic.update(syms)
        except Exception as e:
            log.warning("sectors.json read failed: %s", e)

    microcap = _load_microcap_idx_symbols()

    all_syms = list(n500 | thematic | microcap)
    return [s for s in all_syms if s not in exclude]
