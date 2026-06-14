from __future__ import annotations
import os

from services.llm.providers import PROVIDERS


def system_keys(provider: str) -> list[str]:
    env_var = PROVIDERS[provider]["env_var"]
    raw = os.environ.get(env_var, "").strip()
    return [k.strip() for k in raw.split(",") if k.strip()]


def user_keys(db, user_id: int, provider: str) -> list[tuple[int, str]]:
    from crud.credentials import get_active
    return get_active(db, user_id, provider)
