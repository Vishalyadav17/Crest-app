"""Weekend basket review — aggregate all deep-dive verdicts into a single basket assessment."""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

_SCHEMA = (
    '{"summary":"<3-5 sentences on basket quality and market stance>",'
    '"ranked_syms":["<sym>"],"skip_syms":["<sym>"],'
    '"lessons":["<learning from this basket>"],'
    '"market_stance":"risk-on|neutral|risk-off",'
    '"next_week_checklist":["<action item>"]}'
)

_SYSTEM = (
    "You are a senior portfolio manager reviewing a swing-trade basket. "
    "You receive per-pick deep-dive verdicts and closed outcomes. "
    "Synthesise the basket: which picks are highest conviction, which to skip, "
    "what the market is doing, and what to watch next week. "
    f"Reply ONLY with a single JSON object matching this schema:\n{_SCHEMA}"
)


def build_messages(picks_verdicts: list[dict], closed_outcomes: list[dict],
                   market_note: str | None, breadth: dict | None) -> list[dict]:
    payload = {
        "picks": picks_verdicts,
        "closed_last_week": closed_outcomes,
        "market_note": market_note,
        "breadth": breadth or {},
    }
    user = f"Basket data:\n{json.dumps(payload, default=str, indent=2)}"
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]


async def run(picks_verdicts: list[dict], closed_outcomes: list[dict],
              market_note: str | None, breadth: dict | None,
              *, tier: str = "system", user_id: int | None = None, db=None) -> dict | None:
    from services.llm import chat, NoFreeCapacity
    import json as _json

    messages = build_messages(picks_verdicts, closed_outcomes, market_note, breadth)
    try:
        result = await chat(
            messages,
            task="weekend_review",
            tier=tier,
            user_id=user_id,
            db=db,
            max_tokens=800,
            json_mode=True,
        )
        parsed = _json.loads(result["text"])
        parsed["model_used"] = result["model"]
        parsed["provider"] = result["provider"]
        return parsed
    except NoFreeCapacity:
        log.warning("weekend_review: no LLM capacity")
        return None
    except Exception as e:
        log.error("weekend_review error: %s", e)
        return None
