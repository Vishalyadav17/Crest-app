"""Deep-dive per-pick analysis — BYOK first, system-tier fallback."""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)

_SCHEMA = (
    '{"conviction":<1-10>,"verdict_short":"<≤6 words>",'
    '"verdict_class":"strong|ok|weak|avoid",'
    '"thesis":"<4-6 sentences>","entry_plan":"<2-3 sentences referencing entry band>",'
    '"exit_plan":"<SL/target reasoning>","hold_horizon_days":<int>,'
    '"risk_flags":["..."],"watch_items":["<what to check before entering>"],'
    '"sector_view":"<1-2 sentences>"}'
)

_SYSTEM = (
    "You are a senior swing-trade analyst specialising in Indian smallcap and midcap equities. "
    "You receive structured pick context from a momentum scanner. "
    "Analyse the opportunity rigorously: assess the setup quality, risk/reward, and market context. "
    "Be specific — reference actual levels, scores, and flags from the context. "
    f"Reply ONLY with a single JSON object matching this schema:\n{_SCHEMA}"
)


def build_messages(pick_context: dict) -> list[dict]:
    ctx_str = json.dumps(pick_context, default=str, indent=2)
    user = f"Pick context:\n{ctx_str}"
    return [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}]


async def run(pick_context: dict, *, tier: str = "user", user_id: int | None = None, db=None) -> dict | None:
    from services.llm import chat, NoFreeCapacity
    import json as _json

    messages = build_messages(pick_context)
    sym = pick_context.get("symbol", "?")

    # Try BYOK first, then system keys. chat() itself iterates every model within a tier;
    # we fall through to the next tier on ANY failure (rate-limit, network, bad JSON) so a
    # single flaky model never sinks the whole analysis.
    tiers = ["user", "system"] if tier == "user" else [tier]
    for t in tiers:
        for attempt in range(2):  # one JSON-format retry per tier
            try:
                result = await chat(
                    messages,
                    task="deep_analysis",
                    tier=t,
                    user_id=user_id if t == "user" else None,
                    db=db if t == "user" else None,
                    max_tokens=900,
                    json_mode=True,
                )
                parsed = _json.loads(result["text"])
                parsed["model_used"] = result["model"]
                parsed["provider"] = result["provider"]
                return parsed
            except _json.JSONDecodeError:
                if attempt == 0:
                    messages.append({"role": "assistant", "content": result.get("text", "")})
                    messages.append({"role": "user", "content": "Reply with ONLY the JSON object, no other text."})
                    continue
                log.warning("deep_dive: JSON decode failed (tier=%s) for %s", t, sym)
                break  # next tier
            except NoFreeCapacity:
                log.info("deep_dive: no capacity at tier=%s for %s", t, sym)
                break  # next tier
            except Exception as e:
                log.warning("deep_dive error (tier=%s) for %s: %s", t, sym, e)
                break  # next tier
    return None
