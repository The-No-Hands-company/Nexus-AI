"""Tests for src/routes/_helpers.py.

Covers error builders, JSON validation, token/auth helpers,
rate limiting, provider capabilities, and HTTP helpers.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from src.routes._helpers import (
    _api_error,
    _builtin_chat_fallback,
    _client_ip,
    _hash_api_key,
    _hash_pw,
    _is_truthy_env,
    _json_type_matches,
    _normalize_response_format,
    _provider_capabilities_list,
    _provider_capability_flags,
    _resolve_request_timeout_seconds,
    _safe_int,
    _validate_json_output,
    _verify_pw,
    _v1_error,
)


# ── Error builders ─────────────────────────────────────────────────────


def test_api_error_defaults():
    resp = _api_error("something broke")
    assert resp.status_code == 400
    body = json.loads(resp.body)
    assert body["error"] == "something broke"
    assert body["type"] == "invalid_request"


def test_api_error_custom():
    resp = _api_error("not found", code="not_found", status_code=404)
    assert resp.status_code == 404
    body = json.loads(resp.body)
    assert body["type"] == "not_found"


def test_v1_error_defaults():
    resp = _v1_error("bad request")
    assert resp.status_code == 400
    body = json.loads(resp.body)
    assert body["error"]["message"] == "bad request"
    assert body["error"]["type"] == "invalid_request_error"


def test_v1_error_custom():
    resp = _v1_error("rate limit", err_type="rate_limit_error", status_code=429, code="rate_limited")
    assert resp.status_code == 429
    body = json.loads(resp.body)
    assert body["error"]["code"] == "rate_limited"


import asyncio

def _make_async_func(return_value):
    async def _coro():
        return return_value
    return _coro

def test_read_json_body_valid():
    mock_req = MagicMock()
    mock_req.json = _make_async_func({"key": "value"})
    from src.routes._helpers import _read_json_body
    loop = asyncio.new_event_loop()
    try:
        result = loop.run_until_complete(_read_json_body(mock_req))
    finally:
        loop.close()
    assert result == {"key": "value"}


def test_read_json_body_raises_on_non_dict():
    mock_req = MagicMock()
    mock_req.json = _make_async_func(["not", "a", "dict"])
    from src.routes._helpers import _read_json_body
    loop = asyncio.new_event_loop()
    try:
        with pytest.raises(HTTPException) as exc:
            loop.run_until_complete(_read_json_body(mock_req))
        assert exc.value.status_code == 400
    finally:
        loop.close()


# ── _resolve_request_timeout_seconds ───────────────────────────────────


def test_timeout_default():
    assert _resolve_request_timeout_seconds({}) > 0


def test_timeout_from_data():
    assert _resolve_request_timeout_seconds({"request_timeout_s": 60}) == 60.0


def test_timeout_clamped_low():
    assert _resolve_request_timeout_seconds({"request_timeout_s": 1}) == 10.0


def test_timeout_clamped_high():
    assert _resolve_request_timeout_seconds({"request_timeout_s": 1000}) == 600.0


# ── _normalize_response_format ─────────────────────────────────────────


def test_normalize_none():
    assert _normalize_response_format(None) == {"mode": None, "schema": None}


def test_normalize_json_string():
    assert _normalize_response_format("json") == {"mode": "json", "schema": None}


def test_normalize_json_object_string():
    assert _normalize_response_format("json_object") == {"mode": "json", "schema": None}


def test_normalize_dict_json_object():
    assert _normalize_response_format({"type": "json_object"}) == {"mode": "json", "schema": None}


def test_normalize_dict_json_schema():
    result = _normalize_response_format({
        "type": "json_schema",
        "json_schema": {"schema": {"type": "object"}},
    })
    assert result["mode"] == "json"
    assert result["schema"] == {"type": "object"}


def test_normalize_raises_on_bad_string():
    with pytest.raises(ValueError, match="response_format must be"):
        _normalize_response_format("xml")


def test_normalize_raises_on_bad_type():
    with pytest.raises(ValueError, match="response_format.type must be"):
        _normalize_response_format({"type": "xml"})


# ── _builtin_chat_fallback ─────────────────────────────────────────────


def test_fallback_provider_unavailable():
    msg = _builtin_chat_fallback("test", reason="provider_unavailable")
    assert "provider" in msg


def test_fallback_timeout():
    msg = _builtin_chat_fallback("test")
    assert "timed out" in msg


# ── _json_type_matches ─────────────────────────────────────────────────


def test_json_type_object():
    assert _json_type_matches({"a": 1}, "object") is True
    assert _json_type_matches([], "object") is False


def test_json_type_array():
    assert _json_type_matches([1, 2], "array") is True
    assert _json_type_matches({}, "array") is False


def test_json_type_string():
    assert _json_type_matches("hello", "string") is True
    assert _json_type_matches(42, "string") is False


def test_json_type_number():
    assert _json_type_matches(42.5, "number") is True
    assert _json_type_matches(42, "number") is True
    assert _json_type_matches("42", "number") is False
    assert _json_type_matches(True, "number") is False


def test_json_type_integer():
    assert _json_type_matches(42, "integer") is True
    assert _json_type_matches(42.5, "integer") is False
    assert _json_type_matches(True, "integer") is False


def test_json_type_boolean():
    assert _json_type_matches(True, "boolean") is True
    assert _json_type_matches(False, "boolean") is True
    assert _json_type_matches(1, "boolean") is False


def test_json_type_null():
    assert _json_type_matches(None, "null") is True
    assert _json_type_matches(0, "null") is False


def test_json_type_unknown_defaults_true():
    assert _json_type_matches("any", "unknown_type") is True


# ── _validate_json_output ──────────────────────────────────────────────


def test_validate_json_valid():
    assert _validate_json_output('{"a": 1}') == {"a": 1}


def test_validate_json_fence():
    assert _validate_json_output('```json\n{"a": 1}\n```') == {"a": 1}


def test_validate_json_fence_no_lang():
    assert _validate_json_output('```\n{"a": 1}\n```') == {"a": 1}


def test_validate_json_invalid_raises():
    with pytest.raises(ValueError):
        _validate_json_output("not json at all")


def test_validate_json_extracts_nested():
    result = _validate_json_output('some text {"b": 2} more text')
    assert result == {"b": 2}


def test_validate_json_extracts_nested_array():
    result = _validate_json_output('prefix [1, 2, 3] suffix')
    assert result == [1, 2, 3]


def test_validate_json_with_schema():
    schema = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
    result = _validate_json_output('{"name": "test"}', schema)
    assert result["name"] == "test"


def test_validate_json_schema_violation():
    schema = {"type": "object", "properties": {"age": {"type": "integer"}}}
    with pytest.raises(ValueError):
        _validate_json_output('{"age": "not-a-number"}', schema)


# ── _client_ip ─────────────────────────────────────────────────────────


def test_client_ip_forwarded():
    req = MagicMock()
    req.headers = {"X-Forwarded-For": "203.0.113.1, 10.0.0.1"}
    assert _client_ip(req) == "203.0.113.1"


def test_client_ip_direct():
    req = MagicMock()
    req.headers = {}
    req.client.host = "192.168.1.1"
    assert _client_ip(req) == "192.168.1.1"


def test_client_ip_unknown():
    req = MagicMock()
    req.headers = {}
    req.client = None
    assert _client_ip(req) == "unknown"


# ── Password / key helpers ─────────────────────────────────────────────


def test_hash_pw_roundtrip():
    pw = "my-secret"
    hashed = _hash_pw(pw)
    assert "$" in hashed
    assert _verify_pw(pw, hashed) is True


def test_verify_pw_wrong():
    hashed = _hash_pw("correct")
    assert _verify_pw("wrong", hashed) is False


def test_verify_pw_malformed():
    assert _verify_pw("any", "no-delimiter") is False


def test_verify_pw_short():
    assert _verify_pw("any", "ab$c") is False


def test_hash_api_key():
    key = "nxk_" + "a" * 40
    h = _hash_api_key(key)
    assert len(h) == 64  # sha256 hex
    assert isinstance(h, str)
    assert _hash_api_key(key) == _hash_api_key(key)  # deterministic


# ── _safe_int ──────────────────────────────────────────────────────────


def test_safe_int_normal():
    assert _safe_int("42", default=10, min_value=0, max_value=100) == 42


def test_safe_int_clamped_low():
    assert _safe_int("-5", default=10, min_value=0, max_value=100) == 0


def test_safe_int_clamped_high():
    assert _safe_int("999", default=10, min_value=0, max_value=100) == 100


def test_safe_int_invalid():
    assert _safe_int("not-a-number", default=10, min_value=0, max_value=100) == 10


def test_safe_int_none():
    assert _safe_int(None, default=5, min_value=0, max_value=100) == 5


# ── _is_truthy_env ────────────────────────────────────────────────────


def test_is_truthy_true_values(monkeypatch):
    for val in ("1", "true", "yes", "on", "TRUE", "YES"):
        monkeypatch.setenv("TEST_VAR", val)
        assert _is_truthy_env("TEST_VAR") is True


def test_is_truthy_false_values(monkeypatch):
    for val in ("0", "false", "no", "off", "", "random"):
        monkeypatch.setenv("TEST_VAR", val)
        assert _is_truthy_env("TEST_VAR") is False


def test_is_truthy_missing_default():
    assert _is_truthy_env("NONEXISTENT_VAR") is False


def test_is_truthy_missing_custom_default():
    assert _is_truthy_env("NONEXISTENT_VAR", default=True) is True


# ── Provider capability helpers ────────────────────────────────────────


def test_provider_capability_flags_tools():
    flags = _provider_capability_flags({"id": "openai", "model": "gpt-4"})
    assert flags["tools"] is True


def test_provider_capability_flags_vision():
    flags = _provider_capability_flags({"id": "gemini", "model": "gemini-pro"})
    assert flags["vision"] is True


def test_provider_capability_flags_no_vision():
    flags = _provider_capability_flags({"id": "openai", "model": "gpt-3.5-turbo"})
    assert flags["vision"] is False


def test_provider_capability_flags_reasoning():
    flags = _provider_capability_flags({"id": "claude", "model": "claude-3-opus"})
    assert flags["reasoning"] is True


def test_provider_capability_flags_embeddings():
    flags = _provider_capability_flags({"id": "openai", "model": "text-embedding-3", "openai_compat": True})
    assert flags["embeddings"] is True


def test_provider_capabilities_list():
    flags = {"tools": True, "vision": False, "json_mode": True}
    caps = _provider_capabilities_list(flags)
    assert "tools" in caps
    assert "json_mode" in caps
    assert "vision" not in caps
