"""Batch scan review — aggregate per scan_run.

Best/Worst are computed deterministically from ACTUAL outcome returns (not the LLM's guess
from entry-time scores — that produced "best CRAFTSMAN / worst HFCL" while HFCL actually won
+4.5%). The LLM only writes the prose summary; best_sym/worst_sym are overridden in run().
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)


def _eff_return(p: dict) -> float | None:
    """Effective return for ranking: realised when closed, else unrealised from entry baseline."""
    r = p.get("return_pct")
    if r is not None:
        return float(r)
    if p.get("scan_result") == "TARGET_HIT":
        return p.get("target_pct")
    if p.get("scan_result") == "SL_HIT":
        return p.get("sl_pct")
    return p.get("unrealized_pct")


def build_messages(picks: list[dict]) -> list[dict]:
    total = len(picks)
    sectors = list({p.get("sector", "Unknown") for p in picks if p.get("sector")})

    lines = []
    for p in picks[:30]:
        r = _eff_return(p)
        rtxt = f"{r:+.1f}%" if r is not None else "open/flat"
        lines.append(
            f"{p.get('symbol')} ({p.get('sector','?')}, composite={p.get('composite_score','?')}, "
            f"result={p.get('scan_result') or 'OPEN'}, return={rtxt})"
        )

    closed = [p for p in picks if _eff_return(p) is not None and p.get("scan_result")]
    wins = sum(1 for p in closed if (_eff_return(p) or 0) >= 0)
    losses = len(closed) - wins

    system = (
        "You are a swing-trade scan reviewer. You are given this basket's picks WITH their actual "
        "outcomes (return %, win/loss). Summarise how the basket performed and what the wins/losses "
        "had in common — sectors, setup quality, market timing. Ground every claim in the outcomes given; "
        "do NOT call a losing pick high-conviction or a winning pick weak. "
        "Reply ONLY in this JSON:\n"
        '{"summary":"<2-3 sentences grounded in actual outcomes>","strong_count":<int wins>,'
        '"weak_count":<int losses>,"themes":["<theme1>","<theme2>"]}'
    )
    user = (
        f"Total picks: {total} | Closed: {len(closed)} ({wins}W / {losses}L)\n"
        f"Sectors present: {', '.join(sectors)}\n"
        f"Picks with outcomes (up to 30):\n" + "\n".join(lines)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def run(picks: list[dict]) -> dict | None:
    from services.llm import chat, NoFreeCapacity
    messages = build_messages(picks)

    # rank CLOSED picks only — an open pick's unrealised move is not a decided win/loss
    rated = sorted(
        ((p, _eff_return(p)) for p in picks if p.get("scan_result") and _eff_return(p) is not None),
        key=lambda x: -x[1],
    )
    best_sym = rated[0][0].get("symbol") if rated else None
    worst_sym = rated[-1][0].get("symbol") if rated else None
    wins = sum(1 for _, r in rated if r >= 0)
    losses = len(rated) - wins

    try:
        result = await chat(messages, task="scan_review", tier="system", max_tokens=300, json_mode=True)
        parsed = json.loads(result["text"])
        parsed["model_used"] = result["model"]
        parsed["provider"] = result["provider"]
    except NoFreeCapacity:
        log.warning("scan_review: no free LLM capacity")
        return None
    except Exception as e:
        log.error("scan_review error: %s", e)
        return None

    # outcome-derived facts always win over the model's narrative
    parsed["best_sym"] = best_sym
    parsed["worst_sym"] = worst_sym
    if rated:
        parsed["strong_count"] = wins
        parsed["weak_count"] = losses
    return parsed
