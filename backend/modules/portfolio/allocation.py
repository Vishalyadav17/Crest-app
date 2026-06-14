"""
Sector, market-cap, and concentration breakdowns.
Accepts holdings list directly — no longer reads portfolio.json.
"""
from __future__ import annotations
from collections import defaultdict


def _equity_only(holdings: list[dict]) -> list[dict]:
    return [h for h in holdings if not h.get("is_etf", False) and h.get("hold_type") != "t_plus_0"]


def _total_equity(holdings: list[dict]) -> float:
    return sum(h["qty"] * h["ltp"] for h in holdings if h.get("qty") and h.get("ltp"))


def get_sector_allocation_from_holdings(holdings: list[dict]) -> dict:
    eq = _equity_only(holdings)
    total = _total_equity(eq)

    by_sector: dict[str, list[dict]] = defaultdict(list)
    for h in eq:
        by_sector[h.get("sector") or "Unknown"].append(h)

    sectors = []
    for sector, stocks in sorted(by_sector.items(), key=lambda x: -sum(s["qty"] * s["ltp"] for s in x[1] if s.get("qty") and s.get("ltp"))):
        sector_val = sum(s["qty"] * s["ltp"] for s in stocks if s.get("qty") and s.get("ltp"))
        sector_inv = sum(s["qty"] * s["avg"] for s in stocks if s.get("qty") and s.get("avg"))
        top_stock  = max(stocks, key=lambda s: (s.get("qty") or 0) * (s.get("ltp") or 0))
        sectors.append({
            "sector":          sector,
            "pct_of_equity":   round(sector_val / total * 100, 1) if total else 0,
            "capital":         round(sector_val),
            "invested":        round(sector_inv),
            "count":           len(stocks),
            "top_stock":       top_stock["sym"],
            "stocks": [
                {
                    "sym":                     s["sym"],
                    "capital":                 round((s.get("qty") or 0) * (s.get("ltp") or 0)),
                    "weight_in_sector_pct":    round((s.get("qty") or 0) * (s.get("ltp") or 0) / sector_val * 100, 1) if sector_val else 0,
                    "weight_in_portfolio_pct": round((s.get("qty") or 0) * (s.get("ltp") or 0) / total * 100, 1) if total else 0,
                }
                for s in sorted(stocks, key=lambda s: -(s.get("qty") or 0) * (s.get("ltp") or 0))
            ],
        })
    return {"total_equity": round(total), "sectors": sectors}


def get_mcap_allocation_from_holdings(holdings: list[dict]) -> dict:
    eq = _equity_only(holdings)
    total = _total_equity(eq)

    bucket_order = ["Large", "Mid", "Small", "Micro"]
    by_bucket: dict[str, list[dict]] = defaultdict(list)
    for h in eq:
        by_bucket[h.get("mcap_bucket") or "Small"].append(h)

    buckets = []
    for bucket in bucket_order:
        stocks = by_bucket.get(bucket, [])
        if not stocks:
            continue
        bucket_val = sum(s["qty"] * s["ltp"] for s in stocks if s.get("qty") and s.get("ltp"))
        buckets.append({
            "bucket":        bucket,
            "pct_of_equity": round(bucket_val / total * 100, 1) if total else 0,
            "capital":       round(bucket_val),
            "count":         len(stocks),
            "stocks": [
                {
                    "sym":        s["sym"],
                    "sector":     s.get("sector"),
                    "capital":    round((s.get("qty") or 0) * (s.get("ltp") or 0)),
                    "weight_pct": round((s.get("qty") or 0) * (s.get("ltp") or 0) / total * 100, 1) if total else 0,
                }
                for s in sorted(stocks, key=lambda s: -(s.get("qty") or 0) * (s.get("ltp") or 0))
            ],
        })
    return {"total_equity": round(total), "buckets": buckets}


def get_concentration_from_holdings(holdings: list[dict]) -> dict:
    eq = _equity_only(holdings)
    total = _total_equity(eq)

    items = sorted(
        [
            {
                "sym":        h["sym"],
                "sector":     h.get("sector"),
                "weight_pct": round((h.get("qty") or 0) * (h.get("ltp") or 0) / total * 100, 2) if total else 0,
                "capital":    round((h.get("qty") or 0) * (h.get("ltp") or 0)),
                "trim_flag":  ((h.get("qty") or 0) * (h.get("ltp") or 0) / total * 100) > 5 if total else False,
            }
            for h in eq
        ],
        key=lambda x: -x["weight_pct"],
    )
    return {"total_equity": round(total), "items": items}


# ── Legacy shims (kept for alpha.py which still reads portfolio.json) ──────────

def get_sector_allocation() -> dict:
    from pathlib import Path
    import json
    p = Path(__file__).parent.parent.parent / "data" / "portfolio.json"
    if not p.exists():
        return {"total_equity": 0, "sectors": []}
    portfolio = json.loads(p.read_text())
    holdings = [
        {**h, "avg": h.get("avg", 0), "ltp": h.get("ltp", h.get("avg", 0))}
        for h in portfolio.get("holdings", [])
    ]
    return get_sector_allocation_from_holdings(holdings)


def get_mcap_allocation() -> dict:
    from pathlib import Path
    import json
    p = Path(__file__).parent.parent.parent / "data" / "portfolio.json"
    if not p.exists():
        return {"total_equity": 0, "buckets": []}
    portfolio = json.loads(p.read_text())
    holdings = [
        {**h, "avg": h.get("avg", 0), "ltp": h.get("ltp", h.get("avg", 0))}
        for h in portfolio.get("holdings", [])
    ]
    return get_mcap_allocation_from_holdings(holdings)


def get_concentration() -> dict:
    from pathlib import Path
    import json
    p = Path(__file__).parent.parent.parent / "data" / "portfolio.json"
    if not p.exists():
        return {"total_equity": 0, "items": []}
    portfolio = json.loads(p.read_text())
    holdings = [
        {**h, "avg": h.get("avg", 0), "ltp": h.get("ltp", h.get("avg", 0))}
        for h in portfolio.get("holdings", [])
    ]
    return get_concentration_from_holdings(holdings)
