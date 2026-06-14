"""Live action advisory for a pick the user is HOLDING (open traded position).

Answers the only question that matters once you're in: hold, tighten the stop, it's weakening,
or exit at target. Grounded in entry vs current price, distance to SL/target, days held vs the
suggested horizon, and live strength. Counterpart to winner/failure (which are post-close).
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

_SCHEMA = (
    '{"action":"HOLD|TIGHTEN_SL|EXIT_TARGET|EXIT_WEAK",'
    '"verdict_short":"<≤12 words, plain action + why>",'
    '"verdict_class":"hold|caution|exit_good|exit_bad",'
    '"reason":"<1-2 sentences>"}'
)

_SYSTEM = (
    "You are a swing-trade position manager. The user is ALREADY HOLDING this stock. "
    "Given entry, current price, stop-loss, target, days held vs suggested horizon and live strength, "
    "tell them exactly what to do now. Be decisive: HOLD if thesis intact and room to target; "
    "TIGHTEN_SL if extended/near target or stalling (lock gains); EXIT_TARGET if at/above target; "
    "EXIT_WEAK if thesis broken, strength gone, or horizon elapsed while flat. "
    f"Reply ONLY with one JSON object: {_SCHEMA}"
)


def build_messages(ctx: dict) -> list[dict]:
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": "Held position:\n" + json.dumps(ctx, default=str, indent=2)},
    ]


async def run(ctx: dict) -> dict | None:
    from services.llm import chat, NoFreeCapacity
    try:
        result = await chat(build_messages(ctx), task="validate_pick", tier="system",
                            max_tokens=300, json_mode=True)
        parsed = json.loads(result["text"])
        parsed["model_used"] = result["model"]
        parsed["provider"] = result["provider"]
        return parsed
    except NoFreeCapacity:
        log.warning("holding_advisory: no LLM capacity for %s", ctx.get("symbol"))
        return None
    except Exception as e:
        log.error("holding_advisory error for %s: %s", ctx.get("symbol"), e)
        return None
