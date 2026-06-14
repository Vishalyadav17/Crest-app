"""Agentic deep-dive — the analyst can pull extra data ONCE before deciding.

Two model calls max (hard cap, per design):
  loop 1 — model sees base context + a menu of fetchable data; it either asks for what it needs
           (one batch) OR answers directly.
  loop 2 — we fetch what it asked for, hand it back, and it returns the final analysis.

No third round: this bounds latency and free-tier usage, and keeps the conversation well inside
context limits so the model never hallucinates from an overflowing window. Output schema is
identical to the static deep_dive so hold_horizon_days etc. flow through unchanged.
"""
from __future__ import annotations

import json
import logging

from services.llm.prompts.deep_dive import _SCHEMA

log = logging.getLogger(__name__)

_TOOLS = {
    "order_flow": "QTD order wins vs guidance & prev-quarter revenue (earnings-setup signal)",
    "earnings_date": "next earnings date + sessions until (event risk before target)",
    "peer_strength": "relative-strength percentile vs the whole universe",
    "news": "up to 5 recent news headlines for the stock",
    "fundamentals": "management revenue/PAT guidance from the company's NotebookLM (if available)",
}

_MENU = "\n".join(f'  - "{k}": {v}' for k, v in _TOOLS.items())

_SYSTEM = (
    "You are a senior swing-trade analyst for Indian small/mid-caps. You get structured pick "
    "context from a momentum scanner. You may pull ONE batch of extra data before deciding — and "
    "only once. First reply with EXACTLY this JSON to request data:\n"
    '{"request_data":["<tool>", ...]}\n'
    f"Available tools:\n{_MENU}\n"
    "Request only what would change your verdict; if the context is already enough, skip the "
    "request and answer now. When you answer (either immediately or after receiving data), reply "
    f"ONLY with the analysis JSON:\n{_SCHEMA}"
)

_MAX_BYTES_PER_TOOL = 800


def _fetch_tool(db, sym: str, name: str) -> dict | str | None:
    try:
        if name == "order_flow":
            from services.earnings_setup import get_or_compute_setup
            s = get_or_compute_setup(db, sym)
            return {k: s.get(k) for k in ("qtd_orders_cr", "vs_prev_q", "vs_guidance", "score")} if s else "no order-flow data"
        if name == "earnings_date":
            from shared.earnings_calendar import get_next_earnings, sessions_until_earnings
            nd = get_next_earnings(sym, db=db)
            return {"next_earnings": str(nd) if nd else None,
                    "sessions_until": sessions_until_earnings(nd)} if nd else "no earnings date"
        if name == "peer_strength":
            from shared.rs_universe import get_rs_pct
            rs = get_rs_pct(sym)
            return {"rs_percentile": rs} if rs is not None else "no RS data"
        if name == "news":
            return _recent_headlines(sym)
        if name == "fundamentals":
            from services.notebooklm_connector import fetch_fundamentals
            return fetch_fundamentals(sym) or "no NotebookLM notebook mapped for this symbol"
    except Exception as e:
        log.debug("agentic tool %s failed for %s: %s", name, sym, e)
        return f"{name} unavailable"
    return None


def _recent_headlines(sym: str) -> list[str]:
    import httpx, urllib.parse
    from xml.etree import ElementTree as ET
    base = sym.replace(".NS", "").replace("^", "")
    q = urllib.parse.quote(f"{base} NSE stock India")
    url = f"https://news.google.com/rss/search?q={q}&hl=en-IN&gl=IN&ceid=IN:en"
    try:
        resp = httpx.get(url, timeout=8, follow_redirects=True,
                         headers={"User-Agent": "Mozilla/5.0 (compatible)"})
        root = ET.fromstring(resp.text)
        return [i.findtext("title") or "" for i in root.iter("item")][:5]
    except Exception:
        return []


async def run(pick_context: dict, *, db=None, tier: str = "system") -> dict | None:
    from services.llm import chat, NoFreeCapacity

    sym = pick_context.get("symbol", "?")
    messages = [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": "Pick context:\n" + json.dumps(pick_context, default=str, indent=2)},
    ]

    for loop in range(2):  # HARD CAP: 2 model calls
        try:
            result = await chat(messages, task="deep_analysis", tier=tier, db=db,
                                max_tokens=1000, json_mode=True)
            parsed = json.loads(result["text"])
        except NoFreeCapacity:
            log.info("agentic deep_dive: no capacity for %s (loop %d)", sym, loop)
            return None
        except json.JSONDecodeError:
            log.warning("agentic deep_dive: bad JSON for %s (loop %d)", sym, loop)
            return None
        except Exception as e:
            log.warning("agentic deep_dive error for %s: %s", sym, e)
            return None

        req = parsed.get("request_data")
        if loop == 0 and isinstance(req, list) and req:
            fetched = {}
            for t in req[:4]:
                if t in _TOOLS:
                    val = _fetch_tool(db, sym, t)
                    fetched[t] = json.loads(json.dumps(val, default=str)[:_MAX_BYTES_PER_TOOL]) \
                        if not isinstance(val, (str, type(None))) else val
            messages.append({"role": "assistant", "content": json.dumps({"request_data": req})})
            messages.append({"role": "user", "content":
                             "Requested data:\n" + json.dumps(fetched, default=str, indent=2) +
                             f"\nNow reply ONLY with the final analysis JSON:\n{_SCHEMA}"})
            continue  # loop 2 = final answer

        # got the analysis (or a stray request on the 2nd loop → treat as answer)
        if "conviction" in parsed or "verdict_short" in parsed:
            parsed["model_used"] = result["model"]
            parsed["provider"] = result["provider"]
            parsed["agentic_tools_used"] = req if isinstance(req, list) else []
            return parsed

    log.warning("agentic deep_dive: no analysis after 2 loops for %s", sym)
    return None
