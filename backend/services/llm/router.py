from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from services.llm.config import REQUEST_TIMEOUT
from services.llm.cooldown import is_cooled, set_cooldown
from services.llm.guardrails import (
    CostIncurred,
    GuardrailViolation,
    assert_zero_cost,
    validate_model,
)
from services.llm.providers import ORDER, PROVIDERS, TASK_MODELS

log = logging.getLogger(__name__)


class NoFreeCapacity(Exception):
    pass


def _ollama_base() -> str:
    return os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1").rstrip("/")


def _build_candidates(
    task: str | None, model: str | None
) -> list[tuple[str, str]]:
    if model:
        for pname in ORDER:
            if model in PROVIDERS[pname]["allowlist"]:
                return [(pname, model)]
        raise GuardrailViolation(f"model '{model}' not in any provider allowlist")
    if task:
        return TASK_MODELS.get(task, [])
    raise ValueError("chat() requires either task= or model=")


def _url(provider: str) -> str:
    if provider == "ollama":
        return f"{_ollama_base()}/chat/completions"
    base = PROVIDERS[provider]["base_url"].rstrip("/")
    return f"{base}/chat/completions"


def _headers(provider: str, key: str) -> dict[str, str]:
    hdrs = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }
    if provider == "openrouter":
        hdrs["HTTP-Referer"] = "https://crest.app"
        hdrs["X-Title"] = "Crest"
    return hdrs


def _parse_sse(raw: str) -> dict:
    """Accumulate a streamed SSE completion into one OpenAI-style envelope.

    The previous version returned the FIRST `data:` chunk only, which truncated streamed
    replies to their opening token(s). We now concatenate every chunk's delta/message content.
    """
    import json
    parts: list[str] = []
    last: dict = {}
    for line in raw.splitlines():
        if not line.startswith("data: ") or line == "data: [DONE]":
            continue
        try:
            obj = json.loads(line[6:])
        except Exception:
            continue
        last = obj
        ch = (obj.get("choices") or [{}])[0]
        piece = (ch.get("delta") or {}).get("content") or (ch.get("message") or {}).get("content") or ""
        if piece:
            parts.append(piece)
    if parts and last:
        choices = last.get("choices") or [{}]
        choices[0] = {**choices[0], "message": {"role": "assistant", "content": "".join(parts)}}
        last["choices"] = choices
    return last


async def chat(
    messages: list[dict],
    *,
    task: str | None = None,
    model: str | None = None,
    tier: str = "system",
    user_id: int | None = None,
    db: Any = None,
    max_tokens: int = 1024,
    temperature: float = 0.3,
    json_mode: bool = False,
) -> dict:
    """
    Route chat to the best available free model.
    Returns {text, provider, model, key_fp, usage}.
    Raises NoFreeCapacity when all free tiers are exhausted.
    """
    from services.llm.keys import system_keys, user_keys

    candidates = _build_candidates(task, model)
    if not candidates:
        raise NoFreeCapacity(f"No candidates for task={task}")

    import hashlib

    skip_providers: set[str] = set()

    for provider, mdl in candidates:
        if provider in skip_providers:
            continue
        try:
            validate_model(provider, mdl)
        except GuardrailViolation as e:
            log.warning("guardrail skip: %s", e)
            continue

        cfg = PROVIDERS[provider]

        if tier == "system":
            raw_keys = [(None, k) for k in system_keys(provider)]
        else:
            raw_keys = [(cid, k) for cid, k in user_keys(db, user_id, provider)]

        if not raw_keys:
            log.debug("no keys for %s/%s — skip", provider, tier)
            continue

        for cred_id, key in raw_keys:
            if is_cooled(provider, key, mdl):
                log.debug("cooled: %s %s", provider, mdl)
                continue

            url = _url(provider)
            headers = _headers(provider, key)
            body: dict = {
                "model": mdl,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            if json_mode:
                body["response_format"] = {"type": "json_object"}

            try:
                async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
                    resp = await client.post(url, headers=headers, json=body)

                if resp.status_code == 200:
                    ct = resp.headers.get("content-type", "")
                    if "text/event-stream" in ct:
                        data = _parse_sse(resp.text)
                    else:
                        data = resp.json()
                    assert_zero_cost(provider, data)
                    text = (
                        data.get("choices", [{}])[0]
                        .get("message", {})
                        .get("content", "")
                    )
                    # A 200 with empty content (e.g. a reasoning model that spent its whole token
                    # budget thinking) is useless — caller's json.loads would fail with no retry.
                    # Treat it as a soft failure and fall through to the next candidate.
                    if not (text or "").strip():
                        log.warning("empty content: %s/%s — falling through", provider, mdl)
                        continue
                    key_fp = hashlib.sha256(key.encode()).hexdigest()[:12]
                    log.info("llm ok: %s/%s fp=%s", provider, mdl, key_fp)

                    if tier == "user" and cred_id:
                        try:
                            from crud.credentials import mark_used
                            mark_used(db, cred_id)
                        except Exception as e:
                            log.debug("mark_used failed cred_id=%s: %s", cred_id, e)

                    return {
                        "text": text,
                        "provider": provider,
                        "model": mdl,
                        "key_fp": key_fp,
                        "usage": data.get("usage", {}),
                    }

                elif resp.status_code == 429:
                    log.warning("rate-limit: %s/%s", provider, mdl)
                    set_cooldown(provider, key, mdl)
                    if tier == "user" and cred_id:
                        try:
                            from crud.credentials import mark_rate_limited
                            from datetime import datetime, timezone, timedelta
                            until = datetime.now(timezone.utc) + timedelta(seconds=60)
                            mark_rate_limited(db, cred_id, until)
                        except Exception as e:
                            log.debug("mark_rate_limited failed cred_id=%s: %s", cred_id, e)
                    if cfg.get("hard_stop_on_429"):
                        log.warning("github hard-stop on 429 — skipping provider")
                        skip_providers.add(provider)
                        break
                    continue

                elif resp.status_code == 402:
                    log.error("payment required: %s/%s — skipping provider", provider, mdl)
                    skip_providers.add(provider)
                    break

                else:
                    log.warning("%s/%s status %d: %s", provider, mdl, resp.status_code, resp.text[:200])
                    continue

            except CostIncurred as e:
                log.error("cost incurred signal: %s — abort provider", e)
                skip_providers.add(provider)
                break
            except httpx.TimeoutException:
                log.warning("timeout: %s/%s", provider, mdl)
                continue
            except Exception as e:
                log.error("%s/%s error: %s", provider, mdl, e)
                continue

    raise NoFreeCapacity("All free LLM tiers exhausted")
