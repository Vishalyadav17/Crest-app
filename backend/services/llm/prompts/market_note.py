"""Daily swing-landscape market note."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

log = logging.getLogger(__name__)


def build_messages(context: dict) -> list[dict]:
    date = context.get("date", datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    indices = context.get("indices", {})
    breadth = context.get("breadth", {})
    sector_heatmap = context.get("sector_heatmap", {})

    indices_str = ", ".join(f"{k}={v}" for k, v in list(indices.items())[:6]) if indices else "N/A"
    breadth_str = str(breadth) if breadth else "N/A"
    sectors_top = (
        sorted(sector_heatmap.items(), key=lambda x: x[1], reverse=True)[:5]
        if isinstance(sector_heatmap, dict) else []
    )
    sectors_str = ", ".join(f"{k}:{v:.1f}%" for k, v in sectors_top) if sectors_top else "N/A"

    system = (
        "You are a concise swing-trade market analyst. Write a brief daily note (3-4 sentences) "
        "on today's market breadth, sector leadership, and what it means for swing setups. "
        "Be specific and actionable. No bullet points — prose only."
    )
    user = (
        f"Date: {date}\n"
        f"Index levels/change: {indices_str}\n"
        f"Market breadth: {breadth_str}\n"
        f"Top sectors: {sectors_str}"
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


async def run(context: dict) -> dict | None:
    from services.llm import chat, NoFreeCapacity
    messages = build_messages(context)
    try:
        # gemini-2.5-flash is a thinking model; reasoning tokens count against max_tokens,
        # so keep generous headroom or the visible note gets truncated mid-sentence.
        result = await chat(messages, task="market_note", tier="system", max_tokens=800)
        return {
            "note": result["text"],
            "model_used": result["model"],
            "provider": result["provider"],
        }
    except NoFreeCapacity:
        log.warning("market_note: no free LLM capacity")
        return None
    except Exception as e:
        log.error("market_note error: %s", e)
        return None
