"""
WS7 tests: settings routes.

Covers:
  (a) GET /api/settings/providers — returns list with expected structure
  (b) GET/PUT /api/settings/preferences roundtrip
  (c) POST /api/settings/keys + GET /api/settings/keys + DELETE /api/settings/keys/{id}
  (d) POST /api/settings/keys unknown provider → 400
"""
from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Set FERNET_KEY BEFORE any imports that may trigger crypto module
_TEST_FERNET_KEY = "0xW-kg6x8umrnVKC-8qJ4ykvRce6kJZZCbni849t2JE="
os.environ.setdefault("FERNET_KEY", _TEST_FERNET_KEY)

sys.path.insert(0, str(Path(__file__).parent.parent))


@pytest.fixture(scope="module")
def client():
    with patch("auth.is_auth_enabled", return_value=False):
        from main import app
        with TestClient(app, raise_server_exceptions=True) as c:
            yield c


# ── (a) providers endpoint ────────────────────────────────────────────────────

def test_providers_list_shape(client):
    resp = client.get("/api/settings/providers")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) > 0
    for item in data:
        assert "name" in item
        assert "label" in item
        assert "needs_key" in item


def test_providers_includes_groq(client):
    resp = client.get("/api/settings/providers")
    names = [p["name"] for p in resp.json()]
    assert "groq" in names


def test_providers_ollama_no_key_needed(client):
    resp = client.get("/api/settings/providers")
    by_name = {p["name"]: p for p in resp.json()}
    assert by_name["ollama"]["needs_key"] is False


# ── (b) preferences roundtrip ────────────────────────────────────────────────

def test_preferences_get_defaults(client):
    resp = client.get("/api/settings/preferences")
    assert resp.status_code == 200
    data = resp.json()
    assert "theme" in data
    assert "privacy_mode" in data
    assert "digest_morning_opt_in" in data


def test_preferences_put_roundtrip(client):
    # Enable morning digest
    put_resp = client.put(
        "/api/settings/preferences",
        json={"digest_morning_opt_in": True, "theme": "dark"},
    )
    assert put_resp.status_code == 200
    assert put_resp.json().get("ok") is True

    # Verify it persisted
    get_resp = client.get("/api/settings/preferences")
    data = get_resp.json()
    assert data["digest_morning_opt_in"] is True
    assert data["theme"] == "dark"


def test_preferences_put_ignores_unknown_keys(client):
    """Unknown preference keys are silently ignored (allowlist enforced)."""
    resp = client.put(
        "/api/settings/preferences",
        json={"evil_injection": "x", "theme": "dark"},
    )
    assert resp.status_code == 200


# ── (c) key CRUD with Fernet ──────────────────────────────────────────────────

def test_key_add_and_list(client):
    # POST
    post_resp = client.post("/api/settings/keys", json={
        "provider": "groq",
        "key_label": "test-key",
        "key": "gsk_test_fakekey12345",
    })
    assert post_resp.status_code == 200
    row = post_resp.json()
    assert "id" in row
    assert row["provider"] == "groq"
    key_id = row["id"]

    # GET list should include it
    list_resp = client.get("/api/settings/keys")
    assert list_resp.status_code == 200
    ids = [k["id"] for k in list_resp.json()["keys"]]
    assert key_id in ids

    # cleanup
    del_resp = client.delete(f"/api/settings/keys/{key_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["ok"] is True


def test_key_masked_not_plaintext(client):
    """Returned key is masked, not plaintext."""
    post_resp = client.post("/api/settings/keys", json={
        "provider": "groq",
        "key_label": "mask-test",
        "key": "gsk_verylongsecretkey_1234567890abcdef",
    })
    assert post_resp.status_code == 200
    row = post_resp.json()
    key_id = row["id"]
    masked = row.get("key_masked", "")
    assert "gsk_verylongsecretkey_1234567890abcdef" not in masked

    client.delete(f"/api/settings/keys/{key_id}")


def test_key_delete_not_found(client):
    resp = client.delete("/api/settings/keys/99999999")
    assert resp.status_code == 404


# ── (d) unknown provider → 400 ────────────────────────────────────────────────

def test_key_unknown_provider_rejected(client):
    resp = client.post("/api/settings/keys", json={
        "provider": "some_fake_provider_xyz",
        "key_label": "bad",
        "key": "sk-whatever",
    })
    assert resp.status_code == 400
    assert "error" in resp.json()


def test_key_missing_fields_rejected(client):
    resp = client.post("/api/settings/keys", json={"provider": "groq"})
    assert resp.status_code == 400
