"""
Market breadth: % of stocks above 20/50/200 DMA per index.
Indices: Nifty 50, Nifty Midcap 100, Nifty Smallcap 100.
Constituent lists sourced from data/sectors.json.
Cached 4 hours (EOD metric).
"""
from __future__ import annotations
import json
import logging
from pathlib import Path
import pandas as pd
from shared.cache import cache_get, cache_set
from shared.yfinance_client import get_bulk_daily

log = logging.getLogger(__name__)
_TTL = 14400  # 4h
_DATA_DIR = Path(__file__).parent.parent.parent / "data"

_INDEX_KEYS = [
    ("N50",        "Nifty 50"),
    ("MIDCAP100",  "Nifty Midcap 100"),
    ("SMALLCAP100","Nifty Smallcap 100"),
]


def _sma(series: pd.Series, window: int) -> float:
    return float(series.rolling(window).mean().iloc[-1])


def _load_constituents() -> dict[str, list[str]]:
    path = _DATA_DIR / "sectors.json"
    if not path.exists():
        return {}
    with open(path) as f:
        return json.load(f)


def _compute_breadth(symbols_ns: list[str], bulk: dict) -> dict:
    above20 = above50 = above200 = total = 0
    for sym_ns in symbols_ns:
        df = bulk.get(sym_ns)
        if df is None:
            continue
        try:
            s = df["Close"].dropna() if "Close" in df.columns else pd.Series()
            if len(s) < 20:
                continue
            price = float(s.iloc[-1])
            total += 1
            if price > _sma(s, 20):
                above20 += 1
            if len(s) >= 50 and price > _sma(s, 50):
                above50 += 1
            if len(s) >= 200 and price > _sma(s, 200):
                above200 += 1
        except (KeyError, ValueError, IndexError) as e:
            log.warning("breadth compute skip %s: %s", sym_ns, e)

    def pct(n: int) -> int:
        return round(n / total * 100) if total else 0

    def _css(v: int) -> str:
        return "green" if v >= 60 else ("gold-c" if v >= 40 else "red")

    p20, p50, p200 = pct(above20), pct(above50), pct(above200)
    return {
        "above_20dma":  p20,
        "above_50dma":  p50,
        "above_200dma": p200,
        "css_20dma":    _css(p20),
        "css_50dma":    _css(p50),
        "css_200dma":   _css(p200),
        "sample": total,
    }


def compute_breadth_fresh() -> dict:
    """Compute breadth without touching cache. Called by scheduler."""
    constituents = _load_constituents()
    if not constituents:
        return {"error": "sectors.json not found"}

    all_syms: set[str] = set()
    index_syms: dict[str, list[str]] = {}
    for idx_key, _ in _INDEX_KEYS:
        syms = constituents.get(idx_key, [])
        ns_syms = [s + ".NS" for s in syms if not s.endswith(".NS")]
        index_syms[idx_key] = ns_syms
        all_syms.update(ns_syms)

    if not all_syms:
        return {"error": "No constituents found"}

    bulk = get_bulk_daily(list(all_syms), period="1y")
    if not bulk:
        return {"error": "download failed"}

    indices = []
    overall_20 = overall_50 = overall_200 = overall_total = 0

    for idx_key, idx_label in _INDEX_KEYS:
        b = _compute_breadth(index_syms[idx_key], bulk)
        indices.append({"key": idx_key, "label": idx_label, **b})
        overall_total += b["sample"]
        overall_20    += round(b["above_20dma"] * b["sample"] / 100)
        overall_50    += round(b["above_50dma"] * b["sample"] / 100)
        overall_200   += round(b["above_200dma"] * b["sample"] / 100)

    def pct(n: int) -> float:
        return round(n / overall_total * 100, 1) if overall_total else 0.0

    above_200_pct = pct(overall_200)
    return {
        "indices": indices,
        "above_20dma":  {"pct": pct(overall_20)},
        "above_50dma":  {"pct": pct(overall_50)},
        "above_200dma": {"pct": pct(overall_200)},
        "breadth_signal": (
            "STRONG"   if above_200_pct >= 60
            else ("MODERATE" if above_200_pct >= 40 else "WEAK")
        ),
        "sample_size": overall_total,
    }


def get_market_breadth() -> dict:
    key = "market_breadth_v2"
    cached = cache_get(key, _TTL)
    if cached:
        return cached

    constituents = _load_constituents()
    if not constituents:
        return {"error": "sectors.json not found"}

    # Collect all unique symbols across the 3 indices to bulk-download once
    all_syms: set[str] = set()
    index_syms: dict[str, list[str]] = {}
    for idx_key, _ in _INDEX_KEYS:
        syms = constituents.get(idx_key, [])
        ns_syms = [s + ".NS" for s in syms if not s.endswith(".NS")]
        index_syms[idx_key] = ns_syms
        all_syms.update(ns_syms)

    if not all_syms:
        return {"error": "No constituents found"}

    bulk = get_bulk_daily(list(all_syms), period="1y")
    if not bulk:
        return {"error": "download failed"}

    indices = []
    overall_20 = overall_50 = overall_200 = overall_total = 0

    for idx_key, idx_label in _INDEX_KEYS:
        b = _compute_breadth(index_syms[idx_key], bulk)
        indices.append({"key": idx_key, "label": idx_label, **b})
        overall_total += b["sample"]
        overall_20    += round(b["above_20dma"] * b["sample"] / 100)
        overall_50    += round(b["above_50dma"] * b["sample"] / 100)
        overall_200   += round(b["above_200dma"] * b["sample"] / 100)

    def pct(n: int) -> float:
        return round(n / overall_total * 100, 1) if overall_total else 0.0

    # Legacy keys kept for backward compat with M2 breadth bars
    above_200_pct = pct(overall_200)
    result = {
        "indices": indices,
        "above_20dma":  {"pct": pct(overall_20)},
        "above_50dma":  {"pct": pct(overall_50)},
        "above_200dma": {"pct": pct(overall_200)},
        "breadth_signal": (
            "STRONG"   if above_200_pct >= 60
            else ("MODERATE" if above_200_pct >= 40 else "WEAK")
        ),
        "sample_size": overall_total,
    }
    cache_set(key, result)
    return result
