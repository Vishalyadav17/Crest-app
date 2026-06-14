"""Failure analysis — why a pick hit SL / closed red. Primary usecase."""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)


def build_messages(pick: dict) -> list[dict]:
    sym = pick.get("symbol", "")
    sector = pick.get("sector", "")
    result = pick.get("scan_result", "")
    grade = pick.get("grade", "")
    score = pick.get("total_score", "")
    criteria = pick.get("criteria") or {}
    outcomes = pick.get("outcomes") or []

    criteria_str = json.dumps(criteria, indent=2) if criteria else "N/A"
    outcomes_str = json.dumps(outcomes, indent=2) if outcomes else "N/A"

    system = (
        "You are a swing-trade post-mortem analyst. A stock pick failed (hit SL or closed red). "
        "Explain concisely why it failed using typical technical/market reasons. "
        "Reply ONLY in this JSON:\n"
        '{"verdict_short":"<15 words>","verdict_class":"fail",'
        '"failure_reason":"<2-3 sentences explaining why>","risk_flags":["<factor1>","<factor2>"],'
        '"thesis":"<original thesis recapped in 1 sentence>"}'
    )
    user = (
        f"Stock: {sym} | Sector: {sector} | Grade: {grade} | Score: {score}\n"
        f"Outcome: {result}\n"
        f"SEPA Criteria at entry:\n{criteria_str}\n"
        f"Trade outcomes:\n{outcomes_str}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def run(pick: dict) -> dict | None:
    from services.llm import chat, NoFreeCapacity
    messages = build_messages(pick)
    try:
        result = await chat(messages, task="failure_analysis", tier="system", max_tokens=400, json_mode=True)
        import json as _json
        parsed = _json.loads(result["text"])
        parsed["model_used"] = result["model"]
        parsed["provider"] = result["provider"]
        return parsed
    except NoFreeCapacity:
        log.warning("failure_analysis: no free LLM capacity for %s", pick.get("symbol"))
        return None
    except Exception as e:
        log.error("failure_analysis error for %s: %s", pick.get("symbol"), e)
        return None
