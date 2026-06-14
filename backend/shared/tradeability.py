"""
Tradeability / risk gate — CAPITAL PROTECTION.

Runs AFTER composite scoring, BEFORE the final top-N is emitted, so a high-momentum
name that is structurally un-tradeable (trade-to-trade, GSM, ESM-Stage-II) is never
recommended for real money. Softer concerns (ASM, tight circuit band, thin delivery,
sub-floor turnover, low ADR) FLAG the pick — it can still surface, but with a visible
warning.

Inputs come from `stock_surveillance` (NSE ASM/GSM/ESM + price-band feed, populated by
scripts/kb/ingest_surveillance.py) plus a live turnover figure the scanner computes from
the same OHLC it already downloaded. No network here — pure, testable decision logic.

Status precedence: EXCLUDED > FLAGGED > OK.
"""
from __future__ import annotations
from typing import Optional

import pandas as pd

OK       = "OK"
FLAGGED  = "FLAGGED"
EXCLUDED = "EXCLUDED"


def _norm(v) -> str:
    return (str(v).strip().upper()) if v else ""


def _is_stage_two(stage: str) -> bool:
    """ESM Stage II (highest surveillance) — matches 'II', 'STAGE 2', 'ESM-II' etc."""
    s = stage.replace("-", " ").replace("_", " ")
    return ("II" in s.split()) or ("STAGE 2" in s) or s.endswith(" 2") or s == "2"


def _compute_adr(hist: Optional[pd.DataFrame], days: int = 20) -> Optional[float]:
    """Average Daily Range % over last `days` sessions. None if insufficient data."""
    if hist is None or not hasattr(hist, "columns"):
        return None
    required = {"High", "Low", "Close"}
    if not required.issubset(hist.columns):
        return None
    if len(hist) < days:
        return None
    recent = hist.tail(days)
    h, l, c = recent["High"], recent["Low"], recent["Close"].shift(1)
    c = c.fillna(recent["Close"])
    ranges = ((h - l) / c.replace(0, float("nan"))) * 100.0
    valid = ranges.dropna()
    return float(valid.mean()) if len(valid) >= days // 2 else None


def evaluate(
    sym: str,
    surv,                       # StockSurveillance row or None
    *,
    turnover_cr: float | None = None,
    min_turnover_cr: float = 1.0,
    min_delivery_pct: float = 25.0,
    min_circuit_band_pct: float = 5.0,
    hist: pd.DataFrame | None = None,
    min_adr_pct: float = 2.0,
) -> dict:
    """
    Returns {status, reasons, hard, flags, inputs}.
    `status == EXCLUDED` means NEVER recommend. `FLAGGED` means show with warning.

    `hist` — raw OHLCV DataFrame (optional). When supplied, computes ADR and adds
             `low_adr` flag if ADR < `min_adr_pct`% (dead-money momentum names).
    """
    hard: list[str] = []
    flags: list[str] = []

    asm = _norm(getattr(surv, "asm_stage", None)) if surv else ""
    gsm = _norm(getattr(surv, "gsm_stage", None)) if surv else ""
    esm = _norm(getattr(surv, "esm_stage", None)) if surv else ""
    is_t2t = bool(getattr(surv, "is_t2t", False)) if surv else False
    circuit = getattr(surv, "circuit_band_pct", None) if surv else None
    delivery = getattr(surv, "delivery_pct", None) if surv else None

    # ── HARD EXCLUDE — structurally un-tradeable for a swing ──────────────────
    if is_t2t:
        hard.append("trade-to-trade (T2T) settlement")
    if gsm:
        hard.append(f"GSM ({gsm})")
    if esm and _is_stage_two(esm):
        hard.append(f"ESM Stage-II ({esm})")

    # ── FLAGS — tradeable but elevated risk ──────────────────────────────────
    if asm:
        flags.append(f"ASM ({asm})")
    if esm and not _is_stage_two(esm):
        flags.append(f"ESM Stage-I ({esm})")
    if circuit is not None and circuit <= min_circuit_band_pct:
        flags.append(f"tight circuit band ({circuit}%)")
    if delivery is not None and delivery < min_delivery_pct:
        flags.append(f"low delivery ({delivery}%)")
    if turnover_cr is not None and turnover_cr < min_turnover_cr:
        flags.append(f"sub-floor turnover (₹{turnover_cr:.2f}cr < ₹{min_turnover_cr}cr)")

    # ── ADR gate — dead-money names with tiny daily range ─────────────────────
    adr = _compute_adr(hist)
    if adr is not None and adr < min_adr_pct:
        flags.append(f"low_adr ({adr:.1f}% < {min_adr_pct}%)")

    status = EXCLUDED if hard else (FLAGGED if flags else OK)

    return {
        "symbol": sym,
        "status": status,
        "reasons": hard + flags,
        "hard": hard,
        "flags": flags,
        "inputs": {
            "asm_stage": asm or None,
            "gsm_stage": gsm or None,
            "esm_stage": esm or None,
            "is_t2t": is_t2t,
            "circuit_band_pct": circuit,
            "delivery_pct": delivery,
            "turnover_cr": round(turnover_cr, 2) if turnover_cr is not None else None,
            "adr_pct": round(adr, 2) if adr is not None else None,
            "surveillance_known": surv is not None,
        },
    }
