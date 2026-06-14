"""Winner retro — why a pick closed green. Counterpart to failure.py."""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

_SYSTEM = (
    "You are a swing-trade post-mortem analyst. A stock pick closed green (target hit or exited profitable). "
    "Explain what worked: setup quality, market timing, sector tailwind. "
    "Reply ONLY in this JSON:\n"
    '{"verdict_short":"<15 words>","verdict_class":"pass",'
    '"thesis":"<what worked — 2-3 sentences>","risk_flags":["<what could have gone wrong>"]}'
)


def build_messages(pick: dict) -> list[dict]:
    user = (
        f"Stock: {pick.get('symbol')} | Sector: {pick.get('sector')} | "
        f"Grade: {pick.get('grade')} | Score: {pick.get('total_score')}\n"
        f"Outcome: {pick.get('scan_result')}\n"
        f"Criteria:\n{json.dumps(pick.get('criteria') or {}, indent=2)}\n"
        f"Trade outcomes:\n{json.dumps(pick.get('outcomes') or [], indent=2)}"
    )
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]


async def run(pick: dict) -> dict | None:
    from services.llm import chat, NoFreeCapacity
    import json as _json

    messages = build_messages(pick)
    try:
        result = await chat(messages, task="winner_review", tier="system", max_tokens=350, json_mode=True)
        parsed = _json.loads(result["text"])
        parsed["model_used"] = result["model"]
        parsed["provider"] = result["provider"]
        return parsed
    except NoFreeCapacity:
        log.warning("winner_review: no LLM capacity for %s", pick.get("symbol"))
        return None
    except Exception as e:
        log.error("winner_review error for %s: %s", pick.get("symbol"), e)
        return None
