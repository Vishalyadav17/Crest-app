from __future__ import annotations

from services.llm.providers import PROVIDERS


class GuardrailViolation(Exception):
    pass


class CostIncurred(Exception):
    pass


_COST_SIGNALS = {
    "insufficient_quota",
    "billing",
    "payment",
    "credits",
    "credit_limit",
    "usage_limit",
    "payment_required",
    "insufficient_credits",
}


def validate_model(provider: str, model: str) -> None:
    cfg = PROVIDERS.get(provider)
    if not cfg:
        raise GuardrailViolation(f"Unknown provider: {provider}")
    if model not in cfg["allowlist"]:
        raise GuardrailViolation(f"{provider}: model '{model}' not in allowlist")
    if cfg.get("requires_free_suffix") and not model.endswith(":free"):
        raise GuardrailViolation(f"{provider}: model must end ':free', got '{model}'")
    for sub in cfg.get("block_substrings", set()):
        if sub in model.lower():
            raise GuardrailViolation(f"{provider}: model '{model}' contains blocked '{sub}'")


def assert_zero_cost(provider: str, body: dict) -> None:
    raw = str(body).lower()
    for sig in _COST_SIGNALS:
        if sig in raw:
            raise CostIncurred(f"{provider}: response signals cost — '{sig}'")
