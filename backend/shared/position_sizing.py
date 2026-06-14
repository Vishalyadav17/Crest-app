"""
Position sizing — CAPITAL PROTECTION (recommend-only).

Turns a recommendation (entry / SL / target from key_levels) into a concrete,
risk-bounded order: how many shares such that a stop-out loses no more than a fixed
fraction of capital, capped by a max single-position weight and the portfolio's
mcap-fit rule (<= ceiling cr, ~one ₹25k slot).

Output is COPY-READY Kite order params. This module NEVER places an order — the human
places it on Kite. Kite MCP stays read-only (privacy + read-only project rules).
"""
from __future__ import annotations
import math


def size_position(
    entry: float,
    sl: float,
    target: float | None,
    *,
    capital: float,
    risk_pct: float,
    max_pct: float,
    mcap_cr: float | None = None,
    mcap_ceiling_cr: float = 30000.0,
    slot_size: float | None = None,
    symbol: str = "",
) -> dict:
    """
    qty = floor( (capital * risk_pct) / (entry - sl) ), then capped by:
      - max_pct of capital (max_value / entry)
      - slot_size, if given (nominal ₹/slot ceiling)
    Returns a full sizing breakdown + recommend-only order params.
    """
    invalid = None
    if entry is None or sl is None or entry <= 0:
        invalid = "missing entry/SL"
    elif entry <= sl:
        invalid = "entry <= SL (no risk distance)"

    if invalid:
        return {
            "symbol": symbol, "valid": False, "reason": invalid, "qty": 0,
            "position_value": 0.0, "pct_of_capital": 0.0, "risk_amount": 0.0,
            "risk_pct_actual": 0.0, "rr": None, "sl_distance_pct": None,
            "mcap_fit": None, "order": None,
        }

    risk_per_share = entry - sl
    risk_budget    = capital * risk_pct
    qty_risk       = math.floor(risk_budget / risk_per_share)

    # Caps
    max_value = capital * max_pct
    qty_cap   = math.floor(max_value / entry)
    caps = {"max_pct": qty_cap}
    if slot_size:
        qty_slot = math.floor(slot_size / entry)
        caps["slot_size"] = qty_slot

    qty = min([qty_risk] + list(caps.values()))
    binding = "risk" if qty == qty_risk else min(caps, key=lambda k: caps[k])
    qty = max(qty, 0)

    position_value = round(qty * entry, 2)
    risk_amount    = round(qty * risk_per_share, 2)

    rr = None
    if target is not None and target > entry:
        rr = round((target - entry) / risk_per_share, 2)

    mcap_fit = None
    if mcap_cr is not None:
        mcap_fit = bool(0 < mcap_cr <= mcap_ceiling_cr)

    order = {
        "symbol":      symbol,
        "side":        "BUY",
        "qty":         qty,
        "entry":       round(entry, 2),
        "stop_loss":   round(sl, 2),
        "target":      round(target, 2) if target is not None else None,
        "order_type":  "LIMIT",
        "product":     "CNC",
        "note":        "Recommend-only — place manually on Kite.",
    } if qty > 0 else None

    return {
        "symbol":          symbol,
        "valid":           qty > 0,
        "reason":          None if qty > 0 else "sizing collapsed to 0 shares",
        "qty":             qty,
        "binding_cap":     binding,
        "position_value":  position_value,
        "pct_of_capital":  round(position_value / capital * 100, 2) if capital else 0.0,
        "risk_amount":     risk_amount,
        "risk_pct_actual": round(risk_amount / capital * 100, 3) if capital else 0.0,
        "sl_distance_pct": round(risk_per_share / entry * 100, 2),
        "rr":              rr,
        "mcap_cr":         mcap_cr,
        "mcap_fit":        mcap_fit,
        "inputs": {
            "capital": capital, "risk_pct": risk_pct, "max_pct": max_pct,
            "slot_size": slot_size, "mcap_ceiling_cr": mcap_ceiling_cr,
        },
        "order": order,
    }
