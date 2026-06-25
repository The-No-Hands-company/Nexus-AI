"""MCP (Model Context Protocol) routes.

Extracted from src/api/routes.py for maintainability.
Covers: MCP server status, JSON-RPC, tool listing, and tool invocation.
"""

from __future__ import annotations

import json
import os
from urllib import parse as _urlparse

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from ._helpers import _api_error, _http_json_request, _is_truthy_env, _safe_int

router = APIRouter(prefix="", tags=["mcp"])


def _load_mcp_tools_from_env() -> list[dict]:
    raw = os.getenv("MCP_TOOLS", "").strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except Exception:
        return []
    if not isinstance(parsed, list):
        return []
    tools = []
    for item in parsed:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("url") or "").strip()
        if not name or not url:
            continue
        method = str(item.get("method") or "POST").strip().upper()
        headers = item.get("headers") if isinstance(item.get("headers"), dict) else {}
        timeout_s = _safe_int(item.get("timeout_s", 15), default=15, min_value=1, max_value=60)
        tools.append(
            {
                "name": name,
                "url": url,
                "method": method if method in {"GET", "POST", "PUT", "PATCH", "DELETE"} else "POST",
                "headers": {str(k): str(v) for k, v in headers.items()},
                "timeout_s": timeout_s,
            }
        )
    return tools


def _call_mcp_tool(name: str, args: dict | None = None) -> dict:
    args = args if isinstance(args, dict) else {}
    tools = _load_mcp_tools_from_env()
    selected = next((t for t in tools if t.get("name") == name), None)
    if not selected:
        return {"ok": False, "error": "mcp_tool_not_found", "available": [t.get("name") for t in tools]}

    method = selected.get("method", "POST")
    url = selected.get("url", "")
    payload = None
    if method == "GET" and args:
        query = _urlparse.urlencode({k: str(v) for k, v in args.items()})
        url = url + ("&" if "?" in url else "?") + query
    elif args:
        payload = {"arguments": args}

    resp = _http_json_request(
        method=method,
        url=url,
        payload=payload,
        headers=selected.get("headers") or {},
        timeout=int(selected.get("timeout_s", 15)),
    )
    return {
        "ok": bool(resp.get("ok")),
        "status": resp.get("status", 0),
        "tool": name,
        "response": resp.get("json") if resp.get("json") else resp.get("text"),
    }


def _mcp_server_allowed_tools() -> set[str]:
    from ..tools_builtin import list_tool_schemas

    raw = os.getenv("MCP_SERVER_ALLOWED_TOOLS", "").strip()
    all_tools = set(list_tool_schemas().keys())
    high_risk = {
        "run_command",
        "write_file",
        "delete_file",
        "commit_push",
        "create_repo",
        "git_checkout",
        "git_pull",
    }
    if raw:
        return {part.strip() for part in raw.split(",") if part.strip()}
    if _is_truthy_env("MCP_SERVER_ALLOW_HIGH_RISK", default=False):
        return all_tools
    return all_tools - high_risk


def _mcp_jsonrpc_success(req_id, result: dict):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _mcp_jsonrpc_error(req_id, code: int, message: str, data=None):
    payload = {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}
    if data is not None:
        payload["error"]["data"] = data
    return payload


@router.get("/mcp/server/status")
def mcp_server_status():
    return {
        "enabled": _is_truthy_env("MCP_SERVER_MODE", default=False),
        "allow_high_risk": _is_truthy_env("MCP_SERVER_ALLOW_HIGH_RISK", default=False),
        "allowed_tools": sorted(_mcp_server_allowed_tools()),
    }


@router.post("/mcp/server")
async def mcp_server_rpc(request: Request):
    if not _is_truthy_env("MCP_SERVER_MODE", default=False):
        return _api_error("MCP server mode is disabled", "not_found", 404)

    try:
        body = await request.json()
    except HTTPException as exc:
        return _mcp_jsonrpc_error(None, -32700, str(exc.detail))

    req_id = body.get("id")
    method = str(body.get("method") or "").strip()
    params = body.get("params") if isinstance(body.get("params"), dict) else {}

    from ..tools_builtin import dispatch_builtin, list_tool_schemas, validate_tool_args

    if method == "tools/list":
        schemas = list_tool_schemas()
        allowed = _mcp_server_allowed_tools()
        tools = []
        for name, schema in schemas.items():
            if name not in allowed:
                continue
            tools.append(
                {
                    "name": name,
                    "description": str(schema.get("description") or ""),
                    "inputSchema": dict(schema),
                }
            )
        return _mcp_jsonrpc_success(req_id, {"tools": tools})

    if method == "tools/call":
        name = str(params.get("name") or "").strip()
        arguments = params.get("arguments") if isinstance(params.get("arguments"), dict) else {}
        if not name:
            return _mcp_jsonrpc_error(req_id, -32602, "tool name is required")
        if name not in _mcp_server_allowed_tools():
            return _mcp_jsonrpc_error(req_id, -32001, "tool is not allowed", {"tool": name})

        action = {"action": name, **arguments}
        arg_err = validate_tool_args(action)
        if arg_err:
            return _mcp_jsonrpc_error(req_id, -32602, arg_err)

        trace = dispatch_builtin(action, session_id=f"mcp_{req_id or 'call'}")
        if not trace:
            return _mcp_jsonrpc_error(req_id, -32601, "unknown tool")

        return _mcp_jsonrpc_success(
            req_id,
            {
                "content": [{"type": "text", "text": str(trace.get("result", ""))}],
                "metadata": trace.get("metadata", {}),
                "status": trace.get("status", "done"),
            },
        )

    return _mcp_jsonrpc_error(req_id, -32601, "method not found")


@router.get("/mcp/tools")
def mcp_tools_list():
    tools = _load_mcp_tools_from_env()
    return {
        "tools": [
            {
                "name": t.get("name"),
                "url": t.get("url"),
                "method": t.get("method"),
                "timeout_s": t.get("timeout_s"),
            }
            for t in tools
        ],
        "count": len(tools),
    }


@router.post("/mcp/tools/call")
async def mcp_tools_call(request: Request):
    try:
        body = await request.json()
    except HTTPException as exc:
        return _api_error(str(exc.detail), "validation_error", exc.status_code)

    name = str(body.get("name") or "").strip()
    args = body.get("args") if isinstance(body.get("args"), dict) else {}
    if not name:
        return _api_error("name is required", "validation_error", 422)

    result = _call_mcp_tool(name, args)
    if not result.get("ok"):
        return JSONResponse(result, status_code=404 if result.get("error") == "mcp_tool_not_found" else 502)
    return result
