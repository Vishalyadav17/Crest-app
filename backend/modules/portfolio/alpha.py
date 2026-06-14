"""
Index-relative portfolio alpha computation.

Method: time-weighted return using CURRENT weights held constant.
This is an approximation — not true XIRR. Labelled as such in the UI.
"""
from __future__ import annotations
import json
import logging
from pathlib import Path

import pandas as pd

from shared.yfinance_client import get_daily, get_bulk_daily
from shared.tickers import nse, ALPHA_INDICES

log = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"

_PERIODS = {
    "1M":  21,
    "3M":  63,
    "6M":  126,
    "1Y":  252,
    "3Y":  756,
}


def _pct_return(series: pd.Series, days: int) -> float | None:
    if len(series) < days:
        return None
    start = float(series.iloc[-days])
    end   = float(series.iloc[-1])
    if start == 0:
        return None
    return round((end - start) / start * 100, 2)


def compute_alpha(index_key: str = "N50") -> dict:
    index_ticker = ALPHA_INDICES.get(index_key, ALPHA_INDICES["N50"])

    with open(_DATA_DIR / "portfolio.json") as f:
        portfolio = json.load(f)

    holdings = [h for h in portfolio["holdings"] if not h.get("is_etf", False)]
    if not holdings:
        return {"index": index_key, "periods": {}, "note": "no holdings"}

    total_val = sum(h["qty"] * h["ltp"] for h in holdings)
    weights   = {h["sym"]: h["qty"] * h["ltp"] / total_val for h in holdings}

    # Fetch 3Y daily for all holdings + index
    syms_ns  = [nse(h["sym"]) for h in holdings]
    bulk     = get_bulk_daily(syms_ns, period="3y")
    idx_hist = get_daily(index_ticker, period="3y")

    periods_result = {}
    for label, days in _PERIODS.items():
        port_return = _portfolio_return(holdings, weights, bulk, days)
        idx_return  = _pct_return(idx_hist["Close"].dropna(), days) if not idx_hist.empty else None

        if port_return is None or idx_return is None:
            periods_result[label] = {"portfolio": None, "index": None, "alpha": None}
        else:
            periods_result[label] = {
                "portfolio": port_return,
                "index":     idx_return,
                "alpha":     round(port_return - idx_return, 2),
            }

    return {
        "index": index_key,
        "note":  "Approximate — current weights held constant, not true XIRR",
        "periods": periods_result,
    }


def _portfolio_return(holdings: list[dict], weights: dict[str, float],
                      bulk: dict[str, pd.DataFrame], days: int) -> float | None:
    weighted_ret = 0.0
    total_weight = 0.0

    for h in holdings:
        sym_ns = nse(h["sym"])
        df = bulk.get(sym_ns)
        if df is None or df.empty:
            continue
        close = df["Close"].dropna() if "Close" in df.columns else pd.Series()
        ret = _pct_return(close, days)
        if ret is None:
            continue
        w = weights.get(h["sym"], 0)
        weighted_ret  += ret * w
        total_weight  += w

    if total_weight < 0.5:  # less than 50% of portfolio has data
        return None
    return round(weighted_ret / total_weight, 2) if total_weight else None
