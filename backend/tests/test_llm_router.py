"""
WS7 tests: LLM router.

Covers:
  (a) _build_candidates by task / by model / model-not-in-allowlist
  (b) validate_model guardrail rejection
  (c) chat() 200 success (system tier, mocked httpx)
  (d) chat() 429 → cooldown set → next candidate attempted → success
  (e) chat() 402 → provider added to skip set → NoFreeCapacity
  (f) chat() BYOK tier uses user_keys, not system_keys
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Helpers ───────────────────────────────────────────────────────────────────

def _mock_http_response(status: int, json_body: dict | None = None, text: str = ""):
    resp = MagicMock()
    resp.status_code = status
    resp.headers = {"content-type": "application/json"}
    resp.text = text
    if json_body is not None:
        resp.json = MagicMock(return_value=json_body)
    return resp


def _ok_resp():
    return _mock_http_response(200, {
        "choices": [{"message": {"content": "hello"}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    })


def _make_async_client(responses: list):
    """Build an AsyncClient mock that returns responses in sequence."""
    client = AsyncMock()
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    client.post = AsyncMock(side_effect=responses)
    return client


# ── (a) _build_candidates ─────────────────────────────────────────────────────

def test_build_candidates_by_task():
    from services.llm.router import _build_candidates
    candidates = _build_candidates("swing_failure", None)
    assert len(candidates) > 0
    for prov, mdl in candidates:
        assert isinstance(prov, str)
        assert isinstance(mdl, str)


def test_build_candidates_by_model():
    from services.llm.router import _build_candidates
    # groq model in allowlist
    candidates = _build_candidates(None, "llama-3.3-70b-versatile")
    assert len(candidates) == 1
    assert candidates[0][0] == "groq"
    assert candidates[0][1] == "llama-3.3-70b-versatile"


def test_build_candidates_model_not_in_allowlist():
    from services.llm.router import _build_candidates
    from services.llm.guardrails import GuardrailViolation
    with pytest.raises(GuardrailViolation):
        _build_candidates(None, "gpt-99-ultra-secret")


def test_build_candidates_no_task_no_model():
    from services.llm.router import _build_candidates
    with pytest.raises(ValueError):
        _build_candidates(None, None)


# ── (b) guardrail validate_model ─────────────────────────────────────────────

def test_validate_model_accepts_allowlisted():
    from services.llm.guardrails import validate_model
    validate_model("groq", "llama-3.3-70b-versatile")  # no exception


def test_validate_model_rejects_not_in_allowlist():
    from services.llm.guardrails import GuardrailViolation, validate_model
    with pytest.raises(GuardrailViolation):
        validate_model("groq", "some-proprietary-model")


def test_validate_model_rejects_non_free_on_openrouter():
    from services.llm.guardrails import GuardrailViolation, validate_model
    with pytest.raises(GuardrailViolation):
        validate_model("openrouter", "openai/gpt-4o")  # not in allowlist + no :free suffix


def test_validate_model_rejects_blocked_substring():
    """gemini provider blocks 'pro' substring."""
    from services.llm.guardrails import GuardrailViolation, validate_model
    # gemini-2.5-pro is not in the allowlist — this raises on allowlist check first
    with pytest.raises(GuardrailViolation):
        validate_model("gemini", "gemini-2.5-pro")


# ── (c) chat() 200 success ────────────────────────────────────────────────────

def test_chat_system_tier_success():
    """Basic happy path: groq returns 200, result has expected keys."""
    from services.llm import router
    from services.llm.cooldown import clear as clear_cooldowns

    clear_cooldowns()
    mock_client = _make_async_client([_ok_resp()])

    with patch.dict("os.environ", {"GROQ_API_KEY": "test-groq-key"}):
        with patch("services.llm.router.httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(router.chat(
                [{"role": "user", "content": "hi"}],
                task="swing_failure",
                tier="system",
            ))

    assert "text" in result
    assert result["text"] == "hello"
    assert result["provider"] == "groq"


# ── (d) 429 → cooldown → next candidate ──────────────────────────────────────

def test_chat_429_falls_through_to_next_candidate():
    """First candidate 429s (cooldown set), second candidate succeeds."""
    from services.llm import router
    from services.llm.cooldown import clear as clear_cooldowns

    clear_cooldowns()

    # swing_failure candidates span providers — first (groq) 429s, second (cerebras) 200s
    mock_client = _make_async_client([
        _mock_http_response(429),  # first candidate 429s
        _ok_resp(),                # next candidate succeeds
    ])

    with patch.dict("os.environ", {"GROQ_API_KEY": "test-key", "CEREBRAS_API_KEY": "test-key"}):
        with patch("services.llm.router.httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(router.chat(
                [{"role": "user", "content": "hi"}],
                task="swing_failure",
                tier="system",
            ))

    assert result["text"] == "hello"


def test_chat_429_sets_cooldown():
    """After a 429, the (provider, key, model) triple is cooled."""
    from services.llm import router
    from services.llm.cooldown import clear as clear_cooldowns, is_cooled

    clear_cooldowns()

    # Only one candidate for the task we'll construct via model=
    mock_client = _make_async_client([_mock_http_response(429)])

    from services.llm.router import NoFreeCapacity

    with patch.dict("os.environ", {"GROQ_API_KEY": "check-cooldown-key"}):
        with patch("services.llm.router.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(NoFreeCapacity):
                asyncio.run(router.chat(
                    [{"role": "user", "content": "test"}],
                    model="llama-3.3-70b-versatile",
                    tier="system",
                ))

    assert is_cooled("groq", "check-cooldown-key", "llama-3.3-70b-versatile")
    clear_cooldowns()


# ── (e) 402 → provider skip → NoFreeCapacity ─────────────────────────────────

def test_chat_402_skips_entire_provider():
    """402 payment_required marks provider skipped; all its candidates are skipped."""
    from services.llm import router
    from services.llm.cooldown import clear as clear_cooldowns
    from services.llm.router import NoFreeCapacity

    clear_cooldowns()

    # Use model= to force a single groq candidate; 402 → skip groq → NoFreeCapacity
    mock_client = _make_async_client([_mock_http_response(402)])

    with patch.dict("os.environ", {"GROQ_API_KEY": "test-key"}):
        with patch("services.llm.router.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(NoFreeCapacity):
                asyncio.run(router.chat(
                    [{"role": "user", "content": "test"}],
                    model="llama-3.3-70b-versatile",
                    tier="system",
                ))

    # verify post: exactly 1 HTTP call was made (no retry after 402)
    assert mock_client.post.call_count == 1


# ── (f) BYOK tier uses user_keys ─────────────────────────────────────────────

def test_chat_byok_tier_uses_user_keys():
    """tier='user' calls user_keys(db, user_id, provider) not system_keys."""
    from services.llm import router
    from services.llm.cooldown import clear as clear_cooldowns

    clear_cooldowns()

    mock_client = _make_async_client([_ok_resp()])
    fake_db = MagicMock()
    fake_user_id = 42

    with patch("services.llm.keys.user_keys", return_value=[(101, "byok-key")]) as mock_uk:
        with patch("services.llm.router.httpx.AsyncClient", return_value=mock_client):
            result = asyncio.run(router.chat(
                [{"role": "user", "content": "hi"}],
                task="swing_failure",
                tier="user",
                user_id=fake_user_id,
                db=fake_db,
            ))

    assert result["text"] == "hello"
    # user_keys must have been called with the right args
    mock_uk.assert_called()
    call_args = mock_uk.call_args_list[0]
    assert call_args[0][1] == fake_user_id  # positional: db, user_id, provider


def test_chat_byok_no_keys_raises():
    """tier='user' with no configured keys → NoFreeCapacity."""
    from services.llm import router
    from services.llm.cooldown import clear as clear_cooldowns
    from services.llm.router import NoFreeCapacity

    clear_cooldowns()

    with patch("services.llm.keys.user_keys", return_value=[]):
        with pytest.raises(NoFreeCapacity):
            asyncio.run(router.chat(
                [{"role": "user", "content": "hi"}],
                task="swing_failure",
                tier="user",
                user_id=99,
                db=MagicMock(),
            ))
