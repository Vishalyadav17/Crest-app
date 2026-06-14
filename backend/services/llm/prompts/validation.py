"""Entry validation prompt — short verdict + thesis + risk flags for a fresh pick."""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)


def build_messages(pick: dict) -> list[dict]:
    sym = pick.get("symbol", "")
    sector = pick.get("sector", "")
    grade = pick.get("grade", "")
    score = pick.get("total_score", "")
    criteria = pick.get("criteria") or {}
    mcap = pick.get("mcap_cr")

    criteria_str = json.dumps(criteria, indent=2) if criteria else "N/A"
    mcap_str = f"₹{mcap:.0f} Cr" if mcap else "unknown"

    system = (
        "You are a swing-trade risk analyst. Evaluate this stock scan pick. "
        "Reply ONLY in this JSON format:\n"
        '{"verdict_short":"<20 words>","verdict_class":"pass|caution|fail",'
        '"thesis":"<2-3 sentences>","risk_flags":["<risk1>","<risk2>"]}'
    )
    user = (
        f"Stock: {sym} | Sector: {sector} | Grade: {grade} | Score: {score} | MCap: {mcap_str}\n"
        f"SEPA Criteria:\n{criteria_str}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def run(pick: dict) -> dict | None:
    from services.llm import chat, NoFreeCapacity
    messages = build_messages(pick)
    try:
        result = await chat(messages, task="validate_pick", tier="system", max_tokens=300, json_mode=True)
        import json as _json
        parsed = _json.loads(result["text"])
        parsed["model_used"] = result["model"]
        parsed["provider"] = result["provider"]
        return parsed
    except NoFreeCapacity:
        log.warning("validate_pick: no free LLM capacity for %s", pick.get("symbol"))
        return None
    except Exception as e:
        log.error("validate_pick error for %s: %s", pick.get("symbol"), e)
        return None
