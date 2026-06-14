from __future__ import annotations
import hashlib
import time

from services.llm.config import COOLDOWN_SECONDS

_store: dict[tuple, float] = {}


def _fp(key: str) -> str:
    return hashlib.sha256(key.encode()).hexdigest()[:12]


def is_cooled(provider: str, key: str, model: str) -> bool:
    return time.time() < _store.get((provider, _fp(key), model), 0)


def set_cooldown(provider: str, key: str, model: str, seconds: int = COOLDOWN_SECONDS) -> None:
    _store[(provider, _fp(key), model)] = time.time() + seconds


def clear() -> None:
    _store.clear()
