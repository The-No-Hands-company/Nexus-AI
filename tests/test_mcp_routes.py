"""Tests for src/routes/mcp.py.

Covers tool loading from env, JSON-RPC protocol, server status, and tool dispatch.
"""

from __future__ import annotations

import json
from unittest.mock import ANY, MagicMock, patch

from src.routes.mcp import (
    _call_mcp_tool,
    _load_mcp_tools_from_env,
    _mcp_jsonrpc_error,
    _mcp_jsonrpc_success,
    _mcp_server_allowed_tools,
)


# ── _load_mcp_tools_from_env ────────────────────────────────────────────────


def test_load_tools_empty_env(monkeypatch):
    monkeypatch.delenv("MCP_TOOLS", raising=False)
    assert _load_mcp_tools_from_env() == []


def test_load_tools_invalid_json(monkeypatch):
    monkeypatch.setenv("MCP_TOOLS", "not-json")
    assert _load_mcp_tools_from_env() == []


def test_load_tools_not_a_list(monkeypatch):
    monkeypatch.setenv("MCP_TOOLS", '{"name": "foo"}')
    assert _load_mcp_tools_from_env() == []


def test_load_tools_skips_missing_name_or_url(monkeypatch):
    monkeypatch.setenv(
        "MCP_TOOLS",
        json.dumps([
            {"name": "valid", "url": "https://example.com/tool"},
            {"name": "", "url": "https://example.com/bad"},
            {"url": "https://example.com/noname"},
            {"name": "nourl"},
        ]),
    )
    tools = _load_mcp_tools_from_env()
    assert len(tools) == 1
    assert tools[0]["name"] == "valid"


def test_load_tools_defaults_method_and_timeout(monkeypatch):
    monkeypatch.setenv(
        "MCP_TOOLS",
        json.dumps([{"name": "foo", "url": "https://example.com/foo"}]),
    )
    tools = _load_mcp_tools_from_env()
    assert tools[0]["method"] == "POST"
    assert tools[0]["timeout_s"] == 15


def test_load_tools_caps_timeout(monkeypatch):
    monkeypatch.setenv(
        "MCP_TOOLS",
        json.dumps([
            {"name": "foo", "url": "https://example.com", "timeout_s": 999},
        ]),
    )
    tools = _load_mcp_tools_from_env()
    assert tools[0]["timeout_s"] == 60


# ── _call_mcp_tool ─────────────────────────────────────────────────────────


def test_call_mcp_tool_not_found(monkeypatch):
    monkeypatch.delenv("MCP_TOOLS", raising=False)
    result = _call_mcp_tool("nonexistent")
    assert result["ok"] is False
    assert result["error"] == "mcp_tool_not_found"


def test_call_mcp_tool_found_uses_get(monkeypatch):
    monkeypatch.setenv(
        "MCP_TOOLS",
        json.dumps([
            {"name": "search", "url": "https://api.example.com/search", "method": "GET"},
        ]),
    )
    mock_http = MagicMock(return_value={"ok": True, "status": 200, "json": {"results": []}})
    with patch("src.routes.mcp._http_json_request", mock_http):
        result = _call_mcp_tool("search", args={"q": "test"})
    assert result["ok"] is True
    _, kwargs = mock_http.call_args
    assert kwargs["method"] == "GET"
    assert "q=test" in kwargs["url"]


def test_call_mcp_tool_found_uses_post(monkeypatch):
    monkeypatch.setenv(
        "MCP_TOOLS",
        json.dumps([
            {"name": "chat", "url": "https://api.example.com/chat", "method": "POST"},
        ]),
    )
    mock_http = MagicMock(return_value={"ok": True, "status": 200, "json": {"reply": "hello"}})
    with patch("src.routes.mcp._http_json_request", mock_http):
        result = _call_mcp_tool("chat", args={"message": "hi"})
    assert result["ok"] is True
    _, kwargs = mock_http.call_args
    assert kwargs["method"] == "POST"
    assert kwargs["payload"]["arguments"]["message"] == "hi"


# ── _mcp_server_allowed_tools ──────────────────────────────────────────────


def _make_mock_tools(tool_names):
    return {t: {"description": t} for t in tool_names}


def test_allowed_tools_excludes_high_risk_by_default(monkeypatch):
    monkeypatch.delenv("MCP_SERVER_ALLOWED_TOOLS", raising=False)
    monkeypatch.setenv("MCP_SERVER_ALLOW_HIGH_RISK", "false")

    mock_list = MagicMock(return_value=_make_mock_tools(
        ["read_file", "write_file", "run_command", "list_files", "search_text"]
    ))
    with patch("src.tools_builtin.list_tool_schemas", mock_list):
        allowed = _mcp_server_allowed_tools()
    assert "read_file" in allowed
    assert "write_file" not in allowed
    assert "run_command" not in allowed
    assert "list_files" in allowed


def test_allowed_tools_allows_high_risk_when_env_set(monkeypatch):
    monkeypatch.delenv("MCP_SERVER_ALLOWED_TOOLS", raising=False)
    monkeypatch.setenv("MCP_SERVER_ALLOW_HIGH_RISK", "true")

    mock_list = MagicMock(return_value=_make_mock_tools(
        ["read_file", "write_file", "run_command"]
    ))
    with patch("src.tools_builtin.list_tool_schemas", mock_list):
        allowed = _mcp_server_allowed_tools()
    assert "write_file" in allowed
    assert "run_command" in allowed


def test_allowed_tools_custom_list(monkeypatch):
    monkeypatch.setenv("MCP_SERVER_ALLOWED_TOOLS", "read_file, list_files")

    mock_list = MagicMock(return_value=_make_mock_tools(
        ["read_file", "write_file", "list_files", "run_command"]
    ))
    with patch("src.tools_builtin.list_tool_schemas", mock_list):
        allowed = _mcp_server_allowed_tools()
    assert allowed == {"read_file", "list_files"}


# ── JSON-RPC helpers ────────────────────────────────────────────────────────


def test_jsonrpc_success():
    result = _mcp_jsonrpc_success(1, {"ok": True})
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 1
    assert result["result"]["ok"] is True


def test_jsonrpc_error():
    result = _mcp_jsonrpc_error(2, -32601, "method not found")
    assert result["jsonrpc"] == "2.0"
    assert result["id"] == 2
    assert result["error"]["code"] == -32601
    assert result["error"]["message"] == "method not found"


def test_jsonrpc_error_with_data():
    result = _mcp_jsonrpc_error(None, -32001, "denied", data={"tool": "write_file"})
    assert result["error"]["data"]["tool"] == "write_file"
