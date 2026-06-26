"""Agent routes.

Extracted from src/api/routes.py for maintainability.
Covers: agent execution, streaming, code agent, specialist agents,
agent bus, lineage, marketplace, multi-agent reasoning, orchestration.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, Response, StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["agent"])

from ._helpers import (
    _api_error,
    _builtin_chat_fallback,
    _builtin_coding_fallback,
    _read_json_body,
    _principal_from_request,
    _evaluate_rate_limit,
    _quota_error_response,
    _resolve_request_timeout_seconds,
)
from ..agent import (
    _config,
    _push_safety_event,
    activity_log,
    call_llm_with_fallback,
    get_providers_list,
    get_session_safety_profile,
    run_agent_task,
    warmup_agent,
)
from ..db import (
    load_execution_trace as db_load_execution_trace,
    load_pref as db_load_pref,
    save_execution_trace as db_save_execution_trace,
    save_pref as db_save_pref,
    save_self_review as db_save_self_review,
    list_self_reviews as db_list_self_reviews,
    db_set_shared_memory,
    save_ft_training_sample as db_save_ft_training_sample,
    save_autonomy_trace as db_save_autonomy_trace,
    load_autonomy_trace as db_load_autonomy_trace,
)
from ..execution_trace import (
    save_checkpoint as _save_checkpoint,
    list_traces as _list_traces,
)
from ..safety import GuardrailViolation, check_user_task

from ..api.state import (
    _active_streams,
    autonomy_traces,
    execution_traces,
    sessions,
)


def _light_provider_precheck() -> dict:
    providers = get_providers_list() or []
    ready = [p for p in providers if p.get("available")]
    cooling = [p for p in providers if p.get("rate_limited")]
    no_key = [p for p in providers if (not p.get("has_key") and not p.get("keyless"))]
    return {
        "total": len(providers),
        "ready": len(ready),
        "cooling": len(cooling),
        "no_key": len(no_key),
        "ready_labels": [str(p.get("label") or p.get("id") or "provider") for p in ready],
        "ts": time.time(),
    }


def _precheck_status_message(precheck: dict | None) -> str:
    if not precheck:
        return "Processing request..."
    ready = int(precheck.get("ready", 0) or 0)
    cooling = int(precheck.get("cooling", 0) or 0)
    if ready <= 0:
        return "Provider precheck: no providers currently ready. Request may fallback."
    return f"Provider precheck: {ready} ready" + (f", {cooling} cooling" if cooling else "") + "."


# ── Feedback trace helpers ────────────────────────────────────────────────────

_FEEDBACK_TRACE_STORE_KEY = "feedback_trace_store_v1"
_FEEDBACK_TRACE_CONSENT_KEY = "feedback_trace_opt_in"
_AUTO_TEST_CASES_KEY = "auto_generated_test_cases"
_BUG_FIX_CHECKPOINTS_KEY = "agent_bug_fix_checkpoints_v1"


def _load_feedback_trace_events(limit: int = 5000) -> list[dict]:
    raw = db_load_pref(_FEEDBACK_TRACE_STORE_KEY, [])
    rows: list[dict] = []
    if isinstance(raw, list):
        rows = raw
    elif isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, list):
                rows = parsed
        except Exception:
            rows = []
    safe_limit = max(1, min(int(limit or 5000), 50000))
    return list(reversed(rows))[:safe_limit]


def _keywords_from_response(response: str, limit: int = 6) -> list[str]:
    counts: dict[str, int] = {}
    for token in str(response or "").lower().replace("\n", " ").split(" "):
        clean = "".join(ch for ch in token if ch.isalnum())
        if len(clean) < 4:
            continue
        counts[clean] = counts.get(clean, 0) + 1
    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)
    return [word for word, _ in ranked[: max(1, limit)]]


def _derive_test_tags(prompt: str, response: str) -> list[str]:
    text = f"{prompt} {response}".lower()
    tags: list[str] = []
    if any(k in text for k in ("code", "python", "bug", "refactor", "function")):
        tags.append("coding")
    if any(k in text for k in ("reason", "logic", "why", "explain", "math")):
        tags.append("reasoning")
    if any(k in text for k in ("policy", "safe", "guardrail", "compliance")):
        tags.append("safety")
    if any(k in text for k in ("rag", "retrieve", "document", "source")):
        tags.append("retrieval")
    return tags or ["general"]


def _build_auto_test_cases(rows: list[dict], max_cases: int = 100) -> list[dict]:
    cases: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        prompt = str(row.get("prompt") or "").strip()
        response = str(row.get("response") or "").strip()
        if len(prompt) < 12 or len(response) < 12:
            continue
        key = f"{prompt[:160]}::{response[:160]}"
        if key in seen:
            continue
        seen.add(key)
        expected_keywords = _keywords_from_response(response, limit=5)
        case_id = f"atc_{uuid.uuid4().hex[:10]}"
        cases.append(
            {
                "id": case_id,
                "created_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "prompt": prompt[:2000],
                "expected_keywords": expected_keywords,
                "tags": _derive_test_tags(prompt, response),
                "source": {
                    "trace_id": row.get("id"),
                    "chat_id": row.get("chat_id"),
                    "message_idx": row.get("message_idx"),
                    "provider": row.get("provider"),
                    "model": row.get("model"),
                },
            }
        )
        if len(cases) >= max_cases:
            break
    return cases


# ── Bug fix checkpoint helpers ────────────────────────────────────────────────

def _load_bug_fix_checkpoints() -> list[dict[str, Any]]:
    raw = db_load_pref(_BUG_FIX_CHECKPOINTS_KEY, "[]")
    if isinstance(raw, list):
        return [row for row in raw if isinstance(row, dict)]
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw) if raw.strip() else []
            if isinstance(parsed, list):
                return [row for row in parsed if isinstance(row, dict)]
        except Exception:
            return []
    return []


def _save_bug_fix_checkpoints(rows: list[dict[str, Any]]) -> None:
    db_save_pref(_BUG_FIX_CHECKPOINTS_KEY, json.dumps(rows[-1000:], separators=(",", ":")))


# ═══════════════════════════════════════════════════════════════════════════════
#  Core agent execution
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/agent/stream/live")
async def agent_live_stream():
    """SSE stream of all agent events (activity_log) for the Live Trace panel."""
    import asyncio as _aio
    import json as _json

    async def _generate():
        last_seen = len(activity_log)
        while True:
            await _aio.sleep(0.3)
            current = len(activity_log)
            if current > last_seen:
                for ev in activity_log[last_seen:current]:
                    yield f"data: {_json.dumps(ev)}\n\n"
                last_seen = current

    return StreamingResponse(
        _generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/agent")
async def agent_post(request: Request):
    data   = await _read_json_body(request, "invalid JSON body for /agent")
    task   = data.get("task","").strip()
    sid    = data.get("session_id")
    files  = data.get("files",[])
    images = data.get("images", [])
    if task=="__restore__" and "_history" in data:
        if sid: sessions[sid]=data["_history"]
        return {"result":"restored","provider":"-","model":"-"}
    if not task:
        return _api_error("task is required", "validation_error", 422)

    principal = _principal_from_request(request, sid=sid or "")
    rate_result = _evaluate_rate_limit(principal)
    if not rate_result.get("allowed", True):
        return _quota_error_response(rate_result)

    try:
        task = check_user_task(task, policy_profile=get_session_safety_profile(sid or ""))
    except GuardrailViolation as exc:
        _push_safety_event("block", {
            "scope": "input",
            "tool": "agent_task",
            "label": task[:120],
            "session": sid,
            "profile": get_session_safety_profile(sid or ""),
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
        return _api_error(exc.reason, exc.code, 422)

    history = sessions.get(sid,[]) if sid else []
    provider_precheck = _light_provider_precheck() if not history else None
    if images:
        _content: list = [{"type": "text", "text": task}]
        for _img in images:
            if not isinstance(_img, dict):
                continue
            if _img.get("url"):
                _content.append({"type": "image_url", "image_url": {"url": _img["url"]}})
            elif _img.get("b64"):
                _mime = _img.get("mime_type", "image/png")
                _content.append({"type": "image_url", "image_url": {"url": f"data:{_mime};base64,{_img['b64']}"}})
        try:
            _vresp, _vpid = call_llm_with_fallback([{"role": "user", "content": _content}], task="vision")
            _vout = _vresp.get("content", str(_vresp))
        except Exception as _exc:
            return _api_error(str(_exc), "vision_error", 500)
        return {"result": _vout, "provider": _vpid, "model": "", "session_id": sid}
    kwargs: dict = {}
    try:
        if data.get("max_tool_calls") is not None:
            kwargs["max_tool_calls"] = int(data.get("max_tool_calls"))
        if data.get("max_time_s") is not None:
            kwargs["max_time_s"] = float(data.get("max_time_s"))
        if data.get("max_tokens_out") is not None:
            kwargs["budget_tokens_out"] = int(data.get("max_tokens_out"))
    except (TypeError, ValueError):
        return _api_error("invalid numeric controls: max_tool_calls, max_time_s, max_tokens_out", "validation_error", 422)

    timeout_s = _resolve_request_timeout_seconds(data)
    loop = asyncio.get_running_loop()
    try:
        result = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: run_agent_task(task, history, files, sid=sid or "", usage_principal=principal, **kwargs),
            ),
            timeout=timeout_s,
        )
    except asyncio.TimeoutError:
        fallback = _builtin_coding_fallback(task, reason="timeout") or _builtin_chat_fallback(task, reason="timeout")
        result = {
            "result": fallback,
            "provider": "Built-in",
            "model": "timeout-fallback",
            "fallback_reason": "timeout",
            "provider_precheck": provider_precheck,
            "history": history + [
                {"role": "user", "content": task},
                {"role": "assistant", "content": fallback},
            ],
        }

    if result.get("fallback_reason") in {"provider_unavailable", "timeout"}:
        assisted = _builtin_coding_fallback(task, reason=str(result.get("fallback_reason") or "timeout"))
        if assisted:
            result["result"] = assisted
            result["provider"] = "Built-in"
            result["model"] = "coding-fallback"
    if sid:
        sessions[sid]=result["history"]
        db_set_shared_memory(f"session_history:{sid}", result["history"])
    return {
        "result": result.get("result", ""),
        "provider": result.get("provider", ""),
        "model": result.get("model", ""),
        "fallback_reason": result.get("fallback_reason", ""),
        "provider_attempt_chain": result.get("provider_attempt_chain", ""),
        "provider_attempts": result.get("provider_attempts", []),
        "provider_precheck": result.get("provider_precheck") or provider_precheck,
        "session_id": sid,
    }


@router.post("/agent/stream")
async def agent_stream(request: Request):
    data      = await _read_json_body(request, "invalid JSON body for /agent/stream")
    task      = data.get("task","").strip()
    sid       = data.get("session_id")
    files     = data.get("files",[])
    images    = data.get("images", [])
    stream_id = data.get("stream_id", str(uuid.uuid4()))
    trace_id  = data.get("trace_id", str(uuid.uuid4()))
    if not task:
        return _api_error("task is required", "validation_error", 422)

    principal = _principal_from_request(request, sid=sid or "")
    rate_result = _evaluate_rate_limit(principal)
    if not rate_result.get("allowed", True):
        return _quota_error_response(rate_result)

    try:
        task = check_user_task(task, policy_profile=get_session_safety_profile(sid or ""))
    except GuardrailViolation as exc:
        _push_safety_event("block", {
            "scope": "input",
            "tool": "agent_stream",
            "label": task[:120],
            "session": sid,
            "profile": get_session_safety_profile(sid or ""),
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
        return _api_error(exc.reason, exc.code, 422)

    execution_traces[trace_id] = []
    db_save_execution_trace(trace_id, execution_traces[trace_id])

    history  = sessions.get(sid,[]) if sid else []
    provider_precheck = _light_provider_precheck() if not history else None

    if images:
        _vcontent: list = [{"type": "text", "text": task}]
        for _img in images:
            if not isinstance(_img, dict): continue
            if _img.get("url"):
                _vcontent.append({"type": "image_url", "image_url": {"url": _img["url"]}})
            elif _img.get("b64"):
                _vmime = _img.get("mime_type", "image/png")
                _vcontent.append({"type": "image_url", "image_url": {"url": f"data:{_vmime};base64,{_img['b64']}"}})

        async def _vision_gen():
            try:
                _vr, _vp = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: call_llm_with_fallback([{"role": "user", "content": _vcontent}], task="vision")
                )
                _vc = _vr.get("content", str(_vr))
                _evt = json.dumps({"type": "done", "content": _vc, "provider": _vp})
                yield f"data: {_evt}\n\n"
            except Exception as _exc:
                _err = json.dumps({"type": "error", "message": str(_exc)})
                yield f"data: {_err}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(_vision_gen(), media_type="text/event-stream",
                                  headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    try:
        kwargs: dict = {}
        if data.get("max_tool_calls") is not None:
            kwargs["max_tool_calls"] = int(data.get("max_tool_calls"))
        if data.get("max_time_s") is not None:
            kwargs["max_time_s"] = float(data.get("max_time_s"))
        if data.get("max_tokens_out") is not None:
            kwargs["budget_tokens_out"] = int(data.get("max_tokens_out"))
        timeout_s = _resolve_request_timeout_seconds(data)

        loop = asyncio.get_running_loop()
        try:
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None,
                    lambda: run_agent_task(task, history, files, sid=sid or "", usage_principal=principal, **kwargs),
                ),
                timeout=timeout_s,
            )
        except asyncio.TimeoutError:
            fallback = _builtin_coding_fallback(task, reason="timeout") or _builtin_chat_fallback(task, reason="timeout")
            result = {
                "result": fallback,
                "provider": "Built-in",
                "model": "timeout-fallback",
                "fallback_reason": "timeout",
                "provider_precheck": provider_precheck,
                "history": history + [
                    {"role": "user", "content": task},
                    {"role": "assistant", "content": fallback},
                ],
            }

        if result.get("fallback_reason") in {"provider_unavailable", "timeout"}:
            assisted = _builtin_coding_fallback(task, reason=str(result.get("fallback_reason") or "timeout"))
            if assisted:
                result["result"] = assisted
                result["provider"] = "Built-in"
                result["model"] = "coding-fallback"

        status_evt = {
            "type": "status",
            "message": _precheck_status_message(provider_precheck),
            "provider_precheck": provider_precheck,
        }
        execution_traces[trace_id].append(status_evt)

        if sid and result.get("history"):
            sessions[sid] = result["history"]
            db_set_shared_memory(f"session_history:{sid}", result["history"])

        done_evt = {
            "type": "done",
            "content": result.get("result", "") or "I could not produce a full reply for this turn. Please retry.",
            "provider": result.get("provider", "Built-in"),
            "model": result.get("model", "buffered-stream"),
            "fallback_reason": result.get("fallback_reason", ""),
            "provider_attempt_chain": result.get("provider_attempt_chain", ""),
            "provider_attempts": result.get("provider_attempts", []),
            "provider_precheck": result.get("provider_precheck") or provider_precheck,
        }

        clarify_evt = None
        if isinstance(result.get("clarify_event"), dict):
            clarify_evt = result.get("clarify_event")
            execution_traces[trace_id].append(clarify_evt)

        diagnostic_evt = None
        if done_evt.get("fallback_reason") or done_evt.get("provider_attempt_chain"):
            diagnostic_evt = {
                "type": "diagnostic",
                "fallback_reason": done_evt.get("fallback_reason", ""),
                "provider_attempt_chain": done_evt.get("provider_attempt_chain", ""),
                "provider_attempts": done_evt.get("provider_attempts", []),
                "provider_precheck": done_evt.get("provider_precheck"),
            }
            execution_traces[trace_id].append(diagnostic_evt)

        execution_traces[trace_id].append(done_evt)
        db_save_execution_trace(trace_id, execution_traces[trace_id])
        parts = [f"data: {json.dumps(status_evt)}\n\n"]
        if diagnostic_evt is not None:
            parts.append(f"data: {json.dumps(diagnostic_evt, default=str)}\n\n")
        if clarify_evt is not None:
            parts.append(f"data: {json.dumps(clarify_evt, default=str)}\n\n")
        parts.append(f"data: {json.dumps(done_evt, default=str)}\n\n")
        parts.append("data: [DONE]\n\n")
        body = "".join(parts)
    except Exception as exc:
        import traceback as _tb
        _exc_detail = _tb.format_exc()
        print(f"[agent/stream ERROR] {type(exc).__name__}: {exc}\n{_exc_detail}", flush=True)
        friendly = (
            "I started processing your request but could not finish this turn with a model response. "
            "Please retry, or simplify the request into smaller steps."
        )
        err_evt = {
            "type": "done",
            "content": friendly,
            "provider": "Built-in",
            "model": "buffered-stream-fallback",
        }
        try:
            execution_traces[trace_id].append({"type": "error", "message": str(exc), "detail": _exc_detail})
            execution_traces[trace_id].append(err_evt)
            db_save_execution_trace(trace_id, execution_traces[trace_id])
        except Exception:
            pass
        body = (
            f"data: {json.dumps(err_evt)}\n\n"
            "data: [DONE]\n\n"
        )

    return Response(
        content=body,
        media_type="text/event-stream",
        headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no", "X-Trace-Id": trace_id},
    )


@router.post("/agent/stop/{stream_id}")
def stop_stream(stream_id: str):
    evt = _active_streams.get(stream_id)
    if evt:
        evt.set()
        db_set_shared_memory(f"stream_stop:{stream_id}", {"stopped": True, "stopped_at": time.time()})
        return {"stopped":stream_id}
    return {"not_found":stream_id}


@router.get("/agent/trace/{trace_id}")
def get_agent_trace(trace_id: str):
    trace = execution_traces.get(trace_id) or db_load_execution_trace(trace_id)
    if trace is None:
        return _api_error("trace not found", "not_found", 404)
    return {"trace_id": trace_id, "events": trace}


# ═══════════════════════════════════════════════════════════════════════════════
#  Agent warmup & self-review
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/agent/warmup")
async def agent_warmup(request: Request):
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    sid = str(body.get("session_id") or body.get("sid") or "")
    persona = str(body.get("persona") or "")
    mode = str(body.get("mode") or "full").strip().lower()
    if mode not in {"off", "critical", "background", "full"}:
        mode = "full"

    raw_providers = body.get("providers")
    provider_order: list[str] = []
    if isinstance(raw_providers, list):
        for item in raw_providers:
            p = str(item).strip().lower()
            if p and p not in provider_order:
                provider_order.append(p)

    if mode == "off":
        return JSONResponse({"warmed": False, "cached": False, "mode": "off", "skipped": True})

    if mode == "critical" and not provider_order:
        provider_order = ["ollama", "openrouter", "gemini", "groq"]

    if mode == "background":
        async def _bg_warmup() -> None:
            await asyncio.to_thread(
                warmup_agent,
                sid=sid,
                persona=persona,
                provider_order=provider_order or None,
                task="warmup_full",
            )

        asyncio.create_task(_bg_warmup())
        return JSONResponse({
            "warmed": False,
            "cached": False,
            "mode": "background",
            "scheduled": True,
            "providers": provider_order,
        })

    result = warmup_agent(
        sid=sid,
        persona=persona,
        provider_order=provider_order if mode == "critical" else None,
        task="warmup_critical" if mode == "critical" else "warmup_full",
    )
    result["mode"] = mode
    if provider_order:
        result["providers"] = provider_order
    return JSONResponse(result)


def _build_self_review_prompt(traces: list[dict]) -> str:
    if not traces:
        return "No execution traces available to review."
    lines = [
        "You are an AI self-improvement analyst. The following are summaries of recent agent "
        "execution traces. Analyze them and respond with a JSON object:\n"
        '{\n'
        '  "insights": ["<insight 1>", ...],\n'
        '  "suggestions": ["<improvement suggestion 1>", ...]\n'
        '}\n\n'
        "Include 3-7 insights (patterns you observed) and 3-5 actionable suggestions for improving "
        "agent prompts, tool selection, or task handling. Be specific.\n\n"
        "Traces:\n"
    ]
    for t in traces[:10]:
        lines.append(
            f"- trace_id={t.get('trace_id','?')} steps={t.get('steps',0)} "
            f"task={str(t.get('task',''))[:120]} started={t.get('started_at','?')[:19]}"
        )
    return "\n".join(lines)


@router.post("/agent/self-review")
async def agent_self_review(request: Request):
    body = {}
    try:
        body = await request.json()
    except Exception:
        pass
    limit = body.get("limit", 20)
    try:
        limit = max(1, min(int(limit), 100))
    except Exception:
        limit = 20

    traces = _list_traces(limit=limit)
    if not traces:
        return {"review_id": None, "traces_analyzed": 0,
                "insights": [], "suggestions": [],
                "message": "No traces available to review."}

    prompt = _build_self_review_prompt(traces)
    resp, provider = call_llm_with_fallback(
        [{"role": "user", "content": prompt}], prompt
    )
    raw = resp.get("content") or str(resp)

    import re as _re
    insights: list = []
    suggestions: list = []
    try:
        cleaned = _re.sub(r"```(?:json)?", "", raw).strip().strip("`")
        parsed = json.loads(cleaned)
        insights    = parsed.get("insights", []) or []
        suggestions = parsed.get("suggestions", []) or []
    except Exception:
        suggestions = [l.strip("- •") for l in raw.splitlines() if l.strip()][:10]

    review_id = "review_" + secrets.token_hex(6)
    db_save_self_review(
        review_id=review_id,
        traces_analyzed=len(traces),
        insights=insights,
        suggestions=suggestions,
        provider=provider,
    )

    return {
        "review_id": review_id,
        "traces_analyzed": len(traces),
        "insights": insights,
        "suggestions": suggestions,
        "provider": provider,
    }


@router.get("/agent/self-review/history")
def self_review_history(limit: int = 10):
    try:
        limit = max(1, min(int(limit), 50))
    except Exception:
        limit = 10
    reviews = db_list_self_reviews(limit=limit)
    return {"reviews": reviews, "total": len(reviews)}


# ═══════════════════════════════════════════════════════════════════════════════
#  Test cases
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/agent/test-cases/generate")
async def generate_test_cases_from_production(request: Request):
    body = await _read_json_body(request, "invalid JSON body")
    max_cases = max(1, min(int(body.get("max_cases") or 100), 1000))
    source_limit = max(1, min(int(body.get("source_limit") or 2000), 10000))
    include_reaction_only = bool(body.get("include_reaction_only", True))

    trace_rows = _load_feedback_trace_events(limit=source_limit)
    if not trace_rows and include_reaction_only:
        from ..db import load_feedback_export
        for item in load_feedback_export(limit=source_limit):
            trace_rows.append(
                {
                    "id": f"feedback_{item.get('chat_id')}:{item.get('message_idx')}",
                    "chat_id": item.get("chat_id"),
                    "message_idx": item.get("message_idx"),
                    "prompt": f"Message reaction context for chat {item.get('chat_id')}",
                    "response": str(item.get("reaction") or ""),
                    "provider": item.get("provider"),
                    "model": item.get("model"),
                }
            )

    cases = _build_auto_test_cases(trace_rows, max_cases=max_cases)
    db_save_pref(_AUTO_TEST_CASES_KEY, json.dumps(cases))
    return {
        "generated": len(cases),
        "source_rows": len(trace_rows),
        "stored_key": _AUTO_TEST_CASES_KEY,
        "cases": cases,
    }


@router.get("/agent/test-cases")
def list_generated_test_cases(limit: int = 200):
    raw = db_load_pref(_AUTO_TEST_CASES_KEY, "[]")
    try:
        rows = json.loads(raw) if isinstance(raw, str) else list(raw or [])
    except Exception:
        rows = []
    safe_limit = max(1, min(int(limit or 200), 2000))
    return {"cases": rows[:safe_limit], "total": len(rows)}


@router.post("/agent/test-cases/run")
async def run_generated_test_cases(request: Request):
    body = await _read_json_body(request, "invalid JSON body")
    limit = max(1, min(int(body.get("limit") or 20), 200))

    raw = db_load_pref(_AUTO_TEST_CASES_KEY, "[]")
    try:
        cases = json.loads(raw) if isinstance(raw, str) else list(raw or [])
    except Exception:
        cases = []
    cases = cases[:limit]

    if not cases:
        return {"total": 0, "passed": 0, "failed": 0, "results": []}

    results: list[dict] = []
    for case in cases:
        prompt = str(case.get("prompt") or "").strip()
        expected_keywords = [str(k).lower() for k in (case.get("expected_keywords") or []) if str(k).strip()]
        if not prompt:
            continue
        try:
            run = run_agent_task(prompt, history=[])
            answer = str(run.get("result") or "")
            answer_l = answer.lower()
            hits = [kw for kw in expected_keywords if kw in answer_l]
            pass_ratio = (len(hits) / len(expected_keywords)) if expected_keywords else 0.0
            passed = pass_ratio >= 0.4
            results.append(
                {
                    "id": case.get("id"),
                    "passed": passed,
                    "match_ratio": round(pass_ratio, 3),
                    "hits": hits,
                    "missing": [kw for kw in expected_keywords if kw not in hits],
                }
            )
        except Exception as exc:
            results.append({"id": case.get("id"), "passed": False, "error": str(exc)[:240]})

    passed = sum(1 for r in results if r.get("passed"))
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "pass_pct": round((passed / max(1, len(results))) * 100.0, 2),
        "results": results,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  Reflection & reasoning
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/agent/reflect")
async def agent_reflect(request: Request):
    body = await request.json()
    task        = str(body.get("task", ""))
    result      = str(body.get("result", ""))
    tool_trace  = body.get("tool_trace", [])

    if not task:
        return _api_error("'task' is required", "invalid_request_error", 400)

    from ..thinking import build_reflection_prompt, parse_reflection_response
    prompt = build_reflection_prompt(task, result, tool_trace or [])
    try:
        raw_resp, provider = call_llm_with_fallback([{"role": "user", "content": prompt}], task)
    except Exception as exc:
        return _api_error(f"LLM call failed: {exc}", "model_error", 502)

    raw_text = raw_resp.get("content") or str(raw_resp)
    parsed = parse_reflection_response(raw_text)
    sample_id = db_save_ft_training_sample(
        task=task,
        result=result,
        quality=float(parsed.get("quality_score", 0.7) or 0.7),
        lessons=list(parsed.get("lessons", []) or []),
        source="reflection",
    )
    return {
        "task":         task,
        "reflection":   parsed,
        "provider": provider,
        "fine_tuning_sample_id": sample_id,
        "raw_response": raw_text,
    }


@router.post("/agent/hypothesis")
async def api_hypothesis(request: Request):
    from ..moe_router import build_hypothesis_prompt
    from ..agent import call_llm_with_fallback
    body     = await request.json()
    question = str(body.get("question", ""))
    context  = str(body.get("context", ""))
    prompt   = build_hypothesis_prompt(question, context)
    resp, provider = call_llm_with_fallback(
        [{"role": "user", "content": prompt}], task="hypothesis"
    )
    return {"reasoning": resp.get("content", ""), "provider": provider}


@router.post("/agent/socratic")
async def api_socratic(request: Request):
    from ..moe_router import build_socratic_prompt
    from ..agent import call_llm_with_fallback
    body  = await request.json()
    topic = str(body.get("topic", ""))
    depth = int(body.get("depth", 3))
    prompt = build_socratic_prompt(topic, depth=depth)
    resp, provider = call_llm_with_fallback(
        [{"role": "user", "content": prompt}], task="socratic"
    )
    return {"reasoning": resp.get("content", ""), "provider": provider}


@router.post("/agent/verify")
async def api_formal_proof(request: Request):
    from ..moe_router import build_formal_proof_prompt
    from ..agent import call_llm_with_fallback
    body       = await request.json()
    statement  = str(body.get("statement", ""))
    proof_type = str(body.get("proof_type", "direct"))
    prompt     = build_formal_proof_prompt(statement, proof_type=proof_type)
    resp, provider = call_llm_with_fallback(
        [{"role": "user", "content": prompt}], task="formal_proof"
    )
    return {"proof": resp.get("content", ""), "provider": provider}


# ═══════════════════════════════════════════════════════════════════════════════
#  Code agent
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/agent/code-review")
async def api_code_review(request: Request):
    from ..agent import call_llm_with_fallback
    body     = await request.json()
    code     = str(body.get("code", ""))
    language = str(body.get("language", "python"))
    focus    = str(body.get("focus", "security, bugs, style"))
    if not code:
        return _api_error("code required", status_code=422)
    prompt = (
        f"Review this {language} code for: {focus}.\n\n"
        f"```{language}\n{code}\n```\n\n"
        "Return JSON: {\"issues\": [{\"line\": int|null, \"severity\": \"error|warning|info\", "
        "\"message\": str, \"suggestion\": str}], \"summary\": str, \"score\": 0-10}"
    )
    resp, provider = call_llm_with_fallback(
        [{"role": "user", "content": prompt}], task="code_review"
    )
    import json
    text = resp.get("content", "") if isinstance(resp, dict) else str(resp)
    m    = re.search(r"\{.*\}", text, re.DOTALL)
    result = json.loads(m.group(0)) if m else {"raw": text}
    result["provider"] = provider
    return result


@router.post("/agent/bug-fix")
async def api_bug_fix(request: Request):
    from ..agent import call_llm_with_fallback
    body       = await request.json()
    code       = str(body.get("code", ""))
    error_msg  = str(body.get("error", ""))
    language   = str(body.get("language", "python"))
    test_command = str(body.get("test_command", "")).strip()
    if not code:
        return _api_error("code required", status_code=422)

    checkpoint_id = "bf_" + secrets.token_hex(6)
    checkpoints = _load_bug_fix_checkpoints()
    checkpoint = {
        "checkpoint_id": checkpoint_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "language": language,
        "error": error_msg,
        "original_code": code,
        "test_command": test_command,
        "status": "created",
    }
    checkpoints.append(checkpoint)
    _save_bug_fix_checkpoints(checkpoints)

    prompt = (
        f"Fix this {language} code.\nError: {error_msg}\n\n"
        f"```{language}\n{code}\n```\n\n"
        "Return JSON: {\"fixed_code\": str, \"explanation\": str, \"changes\": [str], "
        "\"confidence\": 0.0-1.0, \"risk\": \"low|medium|high\"}"
    )
    resp, provider = call_llm_with_fallback(
        [{"role": "user", "content": prompt}], task="bug_fix"
    )
    import json
    text   = resp.get("content", "") if isinstance(resp, dict) else str(resp)
    m      = re.search(r"\{.*\}", text, re.DOTALL)
    result = json.loads(m.group(0)) if m else {"raw": text}
    if not isinstance(result, dict):
        result = {"raw": text}

    fixed_code = str(result.get("fixed_code") or "").strip()
    checkpoint["status"] = "fixed" if fixed_code else "review_required"
    checkpoint["provider"] = provider
    checkpoint["updated_at"] = datetime.now(timezone.utc).isoformat()
    checkpoint["fixed_code"] = fixed_code
    checkpoint["confidence"] = result.get("confidence")
    checkpoint["risk"] = result.get("risk")
    _save_bug_fix_checkpoints(checkpoints)

    result["provider"] = provider
    result["checkpoint_id"] = checkpoint_id
    result["rollback_available"] = True
    return result


@router.get("/agent/bug-fix/checkpoints")
async def api_bug_fix_checkpoints(limit: int = 50):
    rows = _load_bug_fix_checkpoints()
    rows = sorted(rows, key=lambda item: str(item.get("created_at", "")), reverse=True)
    capped = rows[: max(1, min(int(limit), 200))]
    return {"checkpoints": capped, "total": len(rows)}


@router.get("/agent/bug-fix/checkpoints/{checkpoint_id}")
async def api_bug_fix_checkpoint_get(checkpoint_id: str):
    rows = _load_bug_fix_checkpoints()
    for row in rows:
        if str(row.get("checkpoint_id") or "") == checkpoint_id:
            return row
    return _api_error("Checkpoint not found", status_code=404)


@router.post("/agent/bug-fix/checkpoints/{checkpoint_id}/rollback")
async def api_bug_fix_checkpoint_rollback(checkpoint_id: str):
    rows = _load_bug_fix_checkpoints()
    for row in rows:
        if str(row.get("checkpoint_id") or "") != checkpoint_id:
            continue
        row["status"] = "rolled_back"
        row["rolled_back_at"] = datetime.now(timezone.utc).isoformat()
        _save_bug_fix_checkpoints(rows)
        return {
            "ok": True,
            "checkpoint_id": checkpoint_id,
            "language": row.get("language", "python"),
            "restored_code": row.get("original_code", ""),
            "error": row.get("error", ""),
        }
    return _api_error("Checkpoint not found", status_code=404)


@router.post("/agent/self-correct")
async def api_agent_self_correct(request: Request):
    from ..agent import call_llm_with_fallback
    from ..thinking import build_critique_prompt, parse_critique_response

    body = await request.json()
    question = str(body.get("question", "") or body.get("task", "")).strip()
    answer = str(body.get("answer", "") or body.get("content", "")).strip()
    try:
        confidence = float(body.get("confidence", 0.0) or 0.0)
    except Exception:
        confidence = 0.0
    threshold = float(body.get("threshold", 0.75) or 0.75)

    if not answer:
        return _api_error("answer is required", status_code=422)
    if confidence >= threshold:
        return {
            "corrected": False,
            "reason": "confidence_above_threshold",
            "threshold": threshold,
            "confidence": confidence,
            "answer": answer,
        }

    critique_prompt = build_critique_prompt(answer, question or "Provide a better version of this answer")
    resp, provider = call_llm_with_fallback(
        [{"role": "user", "content": critique_prompt}],
        task="self_correction",
    )
    raw = resp.get("content", "") if isinstance(resp, dict) else str(resp)
    parsed = parse_critique_response(raw)
    revised = str(parsed.get("revised") or "").strip() or answer
    critique = str(parsed.get("critique") or "").strip()
    revised_confidence = float(parsed.get("confidence", confidence) or confidence)

    db_save_self_review(
        review_id="self_correct_" + secrets.token_hex(6),
        traces_analyzed=0,
        insights=[{"type": "self_correction", "critique": critique}],
        suggestions=[revised],
        provider=provider,
    )

    return {
        "corrected": revised != answer,
        "provider": provider,
        "original_confidence": confidence,
        "threshold": threshold,
        "revised_confidence": revised_confidence,
        "critique": critique,
        "answer": revised,
    }


@router.post("/agent/code-loop")
async def api_agent_code_loop(request: Request):
    from ..agent import run_repo_edit_verify_loop

    body = await request.json()
    task = str(body.get("task") or body.get("prompt") or "").strip()
    if not task:
        return _api_error("task is required", status_code=422)

    sid = str(body.get("sid") or body.get("session_id") or "").strip()
    verify_command = str(body.get("verify_command") or "").strip()
    try:
        max_loops = int(body.get("max_loops", 3) or 3)
    except Exception:
        max_loops = 3

    history = body.get("history") if isinstance(body.get("history"), list) else []
    files = body.get("files") if isinstance(body.get("files"), list) else []
    usage_principal = str(body.get("usage_principal") or "").strip()

    return run_repo_edit_verify_loop(
        task=task,
        history=history,
        files=files,
        sid=sid,
        verify_command=verify_command,
        max_loops=max(1, min(max_loops, 8)),
        usage_principal=usage_principal,
    )


@router.post("/agent/migrate")
async def api_migrate_code(request: Request):
    from ..agent import call_llm_with_fallback
    body       = await request.json()
    code       = str(body.get("code", ""))
    from_lang  = str(body.get("from_language", "python2"))
    to_lang    = str(body.get("to_language", "python3"))
    if not code:
        return _api_error("code required", status_code=422)
    prompt = (
        f"Migrate this code from {from_lang} to {to_lang}.\n\n"
        f"```\n{code}\n```\n\n"
        "Return JSON: {\"migrated_code\": str, \"changes\": [str], \"warnings\": [str]}"
    )
    resp, provider = call_llm_with_fallback(
        [{"role": "user", "content": prompt}], task="code_migration"
    )
    import json
    text   = resp.get("content", "") if isinstance(resp, dict) else str(resp)
    m      = re.search(r"\{.*\}", text, re.DOTALL)
    result = json.loads(m.group(0)) if m else {"raw": text}
    result["provider"] = provider
    return result


@router.post("/agent/diagnose-logs")
async def api_diagnose_logs(request: Request):
    from ..agent import call_llm_with_fallback
    body     = await request.json()
    logs     = str(body.get("logs", ""))
    service  = str(body.get("service", ""))
    if not logs:
        return _api_error("logs required", status_code=422)
    prompt = (
        f"Diagnose these {service} logs and identify root causes.\n\n"
        f"```\n{logs[:8000]}\n```\n\n"
        "Return JSON: {\"issues\": [{\"severity\": str, \"message\": str, \"fix\": str}], "
        "\"root_cause\": str, \"next_steps\": [str]}"
    )
    resp, provider = call_llm_with_fallback(
        [{"role": "user", "content": prompt}], task="log_diagnosis"
    )
    import json
    text   = resp.get("content", "") if isinstance(resp, dict) else str(resp)
    m      = re.search(r"\{.*\}", text, re.DOTALL)
    result = json.loads(m.group(0)) if m else {"raw": text}
    result["provider"] = provider
    return result


# ═══════════════════════════════════════════════════════════════════════════════
#  Specialist agents
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/agents")
def list_specialist_agents():
    from ..agents.registry import list_agents
    return {"agents": list_agents(include_extended=True)}


@router.get("/agents/{agent_id}")
def get_specialist_agent(agent_id: str):
    from ..agents import get_specialist
    agent = get_specialist(agent_id)
    if agent is None:
        return _api_error(f"Agent '{agent_id}' not found", "not_found", 404)
    return {
        "id":                  agent.id,
        "name":                agent.name,
        "icon":                agent.icon,
        "description":         agent.description,
        "keywords":            agent.keywords,
        "preferred_providers": agent.preferred_providers,
        "temperature":         agent.temperature,
        "tier":                agent.tier,
    }


@router.post("/agents/{agent_id}/run")
async def run_specialist_agent(agent_id: str, request: Request):
    from ..agents import get_specialist
    from .. import agent as _agent_mod
    from ..agent import call_llm_with_fallback

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass

    task = (body.get("task") or "").strip()
    if not task:
        return _api_error("task is required", "validation_error", 422)

    agent = get_specialist(agent_id)
    if agent is None:
        return _api_error(f"Agent '{agent_id}' not found", "not_found", 404)

    session_id = str(body.get("session_id") or "")
    try:
        check_user_task(task, policy_profile=get_session_safety_profile(session_id))
    except GuardrailViolation as exc:
        _push_safety_event("block", {
            "scope": "input",
            "tool": f"specialist:{agent_id}",
            "label": task[:120],
            "session": session_id or None,
            "profile": get_session_safety_profile(session_id),
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
        return _api_error(exc.reason, exc.code, 422)

    messages = [
        {"role": "system", "content": agent.system_prompt},
        {"role": "user",   "content": task},
    ]
    try:
        result, pid = call_llm_with_fallback(messages, task)
        content = result.get("content", str(result))
        return {
            "agent_id":  agent_id,
            "agent":     agent.name,
            "provider":  pid,
            "content":   content,
        }
    except _agent_mod.AllProvidersExhausted as exc:
        return JSONResponse(
            {
                "error": str(exc),
                "type": "provider_exhausted",
                "retry_after_seconds": 20,
                "hints": [
                    "Retry shortly after provider cooldown",
                    "Configure at least one additional provider key",
                    "Lower complexity or token budget for this request",
                ],
            },
            status_code=503,
        )
    except Exception as exc:
        return _api_error(str(exc), "agent_error", 500)


@router.post("/agents/classify")
async def classify_task_to_agent(request: Request):
    from ..agents import classify_to_specialist
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass
    task = (body.get("task") or "").strip()
    if not task:
        return _api_error("task is required", "validation_error", 422)
    agent = classify_to_specialist(task)
    return {
        "agent_id":          agent.id,
        "agent_name":        agent.name,
        "icon":              agent.icon,
        "description":       agent.description,
        "match_score":       agent.matches(task),
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  Agent bus
# ═══════════════════════════════════════════════════════════════════════════════

# NOTE: /agents/bus/log and /agents/bus/dlq must be registered BEFORE
# /agents/bus/{agent_id} so FastAPI doesn't capture literal path segments.


@router.get("/agents/bus/log")
def get_bus_log(limit: int = 50, topic: str = ""):
    from ..agent_bus import recent_log, all_agents
    msgs = recent_log(limit=limit, topic=topic if topic else None)
    return {
        "messages":      [m.to_dict() for m in msgs],
        "active_agents": all_agents(),
    }


@router.get("/agents/bus/dlq")
def get_bus_dlq(limit: int = 50):
    from ..agent_bus import get_dlq
    entries = get_dlq(limit=limit)
    return {
        "dlq":   [e.to_dict() for e in entries],
        "count": len(entries),
    }


@router.delete("/agents/bus/dlq")
def clear_bus_dlq():
    from ..agent_bus import clear_dlq
    cleared = clear_dlq()
    return {"cleared": cleared}


@router.get("/agents/bus/consume")
async def consume_agent_inbox_long_poll(
    agent_id: str,
    wait_seconds: float = 20.0,
    limit: int = 20,
    topic: str = "",
):
    from ..agent_bus import read_messages, unread_count

    aid = str(agent_id or "").strip()
    if not aid:
        return _api_error("agent_id is required", "validation_error", 422)

    timeout_s = max(0.0, min(float(wait_seconds), 60.0))
    safe_limit = max(1, min(int(limit), 200))
    start = time.monotonic()

    while True:
        msgs = read_messages(
            aid,
            limit=safe_limit,
            unread_only=True,
            mark_read=True,
            topic=topic if topic else None,
        )
        if msgs:
            return {
                "agent_id": aid,
                "messages": [m.to_dict() for m in msgs],
                "unread_count": unread_count(aid),
                "waited_seconds": round(time.monotonic() - start, 3),
                "timed_out": False,
            }

        if (time.monotonic() - start) >= timeout_s:
            return {
                "agent_id": aid,
                "messages": [],
                "unread_count": unread_count(aid),
                "waited_seconds": round(time.monotonic() - start, 3),
                "timed_out": True,
            }
        await asyncio.sleep(0.25)


@router.websocket("/agents/bus/ws/{agent_id}")
async def consume_agent_inbox_ws(websocket: WebSocket, agent_id: str):
    from ..agent_bus import read_messages, unread_count

    await websocket.accept()
    topic = str(websocket.query_params.get("topic") or "").strip()
    try:
        poll_ms = int(websocket.query_params.get("poll_ms") or 300)
    except Exception:
        poll_ms = 300
    poll_s = max(0.1, min(poll_ms / 1000.0, 2.0))

    heartbeat_every = 10.0
    last_heartbeat = time.monotonic()

    try:
        while True:
            msgs = read_messages(
                agent_id,
                limit=100,
                unread_only=True,
                mark_read=True,
                topic=topic if topic else None,
            )
            for msg in msgs:
                await websocket.send_json({"type": "message", "message": msg.to_dict()})

            now = time.monotonic()
            if now - last_heartbeat >= heartbeat_every:
                await websocket.send_json(
                    {
                        "type": "heartbeat",
                        "agent_id": agent_id,
                        "unread_count": unread_count(agent_id),
                        "ts": time.time(),
                    }
                )
                last_heartbeat = now

            try:
                incoming = await asyncio.wait_for(websocket.receive_text(), timeout=poll_s)
                if incoming.strip().lower() in {"close", "disconnect", "quit"}:
                    await websocket.close()
                    break
            except asyncio.TimeoutError:
                continue
    except WebSocketDisconnect:
        return


@router.get("/agents/bus/{agent_id}")
def read_agent_inbox(
    agent_id: str,
    limit: int = 20,
    unread_only: bool = False,
    topic: str = "",
):
    from ..agent_bus import read_messages, unread_count
    msgs = read_messages(
        agent_id,
        limit=limit,
        unread_only=unread_only,
        mark_read=True,
        topic=topic if topic else None,
    )
    return {
        "agent_id":     agent_id,
        "messages":     [m.to_dict() for m in msgs],
        "unread_count": unread_count(agent_id),
    }


@router.post("/agents/bus", status_code=201)
async def post_agent_message(request: Request):
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        return _api_error("Invalid JSON body", "validation_error", 422)

    from_id = (body.get("from_id") or "").strip()
    to_id   = (body.get("to_id")   or "").strip()
    content = (body.get("content") or "").strip()
    topic   = (body.get("topic")   or "").strip()

    if not from_id:
        return _api_error("from_id is required", "validation_error", 422)
    if not to_id:
        return _api_error("to_id is required", "validation_error", 422)
    if not content:
        return _api_error("content is required", "validation_error", 422)

    from ..agent_bus import post_message
    msg = post_message(from_id, to_id, content, topic=topic)
    return msg.to_dict()


# ═══════════════════════════════════════════════════════════════════════════════
#  Agent lineage
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/agents/lineage/links", status_code=201)
async def create_agent_lineage_link(request: Request):
    body = await _read_json_body(request)
    parent_task_id = str(body.get("parent_task_id") or "").strip()
    child_task_id = str(body.get("child_task_id") or "").strip()
    relation = str(body.get("relation") or "depends_on").strip()
    source = str(body.get("source") or "api").strip()
    metadata = body.get("metadata") if isinstance(body.get("metadata"), dict) else {}

    if not parent_task_id or not child_task_id:
        return _api_error("parent_task_id and child_task_id are required", "validation_error", 422)
    try:
        from ..agent_lineage import record_lineage_edge

        edge = record_lineage_edge(
            parent_task_id=parent_task_id,
            child_task_id=child_task_id,
            relation=relation,
            source=source,
            metadata=metadata,
        )
        return edge
    except ValueError as exc:
        return _api_error(str(exc), "validation_error", 422)


@router.get("/agents/lineage/query")
def query_agent_lineage(task_id: str, direction: str = "both", limit: int = 500):
    from ..agent_lineage import query_lineage

    rows = query_lineage(task_id=task_id, direction=direction, limit=limit)
    return {
        "task_id": task_id,
        "direction": direction,
        "count": len(rows),
        "edges": rows,
    }


@router.get("/agents/lineage/graph/{root_task_id}")
def get_agent_lineage_graph(root_task_id: str, depth: int = 3, limit: int = 2000):
    from ..agent_lineage import get_lineage_graph

    return get_lineage_graph(root_task_id=root_task_id, depth=depth, limit=limit)


# ═══════════════════════════════════════════════════════════════════════════════
#  Marketplace
# ═══════════════════════════════════════════════════════════════════════════════


@router.get("/marketplace/agents")
def list_marketplace_agents(org_id: str = ""):
    from ..agents.registry import SPECIALIST_AGENTS
    from ..db import load_marketplace_agents

    builtin = [
        {
            "id":                  a.id,
            "name":                a.name,
            "icon":                a.icon,
            "description":         a.description,
            "keywords":            a.keywords,
            "preferred_providers": a.preferred_providers,
            "temperature":         a.temperature,
            "tier":                a.tier,
            "source":              "builtin",
        }
        for a in SPECIALIST_AGENTS
    ]
    imported = load_marketplace_agents(source="imported")
    org_agents: list = []
    if org_id:
        org_agents = load_marketplace_agents(org_id=org_id)
        imported_ids = {a["id"] for a in imported}
        org_agents = [a for a in org_agents if a["id"] not in imported_ids]
    all_agents = builtin + imported + org_agents
    return {"agents": all_agents, "total": len(all_agents)}


@router.post("/marketplace/agents", status_code=201)
async def import_marketplace_agent(request: Request):
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        return _api_error("Invalid JSON body", "validation_error", 422)

    agent_id = (body.get("id") or "").strip()
    name     = (body.get("name") or "").strip()
    prompt   = (body.get("system_prompt") or "").strip()

    if not agent_id:
        return _api_error("id is required", "validation_error", 422)
    if not name:
        return _api_error("name is required", "validation_error", 422)
    if not prompt:
        return _api_error("system_prompt is required", "validation_error", 422)

    icon                = (body.get("icon") or "🤖").strip()[:8]
    description         = (body.get("description") or "").strip()[:512]
    keywords            = body.get("keywords") or []
    preferred_providers = body.get("preferred_providers") or []
    temperature         = float(body.get("temperature", 0.7))
    tier                = (body.get("tier") or "standard").strip()

    if not isinstance(keywords, list):
        keywords = [str(keywords)]
    if not isinstance(preferred_providers, list):
        preferred_providers = [str(preferred_providers)]

    from ..db import save_marketplace_agent
    save_marketplace_agent(
        agent_id=agent_id,
        name=name,
        icon=icon,
        description=description,
        system_prompt=prompt,
        keywords=keywords,
        preferred_providers=preferred_providers,
        temperature=temperature,
        tier=tier,
        source="imported",
    )
    return {"id": agent_id, "name": name, "status": "imported"}


@router.post("/marketplace/agents/import-url", status_code=201)
async def import_marketplace_agent_from_url(request: Request):
    import urllib.request
    import urllib.error

    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        return _api_error("Invalid JSON body", "validation_error", 422)

    url    = (body.get("url")    or "").strip()
    org_id = (body.get("org_id") or "").strip()

    if not url:
        return _api_error("url is required", "validation_error", 422)
    if not url.startswith("https://"):
        return _api_error("url must use HTTPS", "validation_error", 422)

    try:
        req = urllib.request.Request(url, headers={"User-Agent": "NexusAI/1.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read(256 * 1024)
        agent_def = json.loads(raw)
    except urllib.error.URLError as exc:
        return _api_error(f"Failed to fetch URL: {exc}", "fetch_error", 400)
    except Exception as exc:
        return _api_error(f"Invalid agent JSON at URL: {exc}", "parse_error", 400)

    agent_id = (agent_def.get("id") or "").strip()
    name     = (agent_def.get("name") or "").strip()
    prompt   = (agent_def.get("system_prompt") or "").strip()

    if not agent_id:
        return _api_error("agent definition missing 'id'", "validation_error", 422)
    if not name:
        return _api_error("agent definition missing 'name'", "validation_error", 422)
    if not prompt:
        return _api_error("agent definition missing 'system_prompt'", "validation_error", 422)

    from ..db import save_marketplace_agent
    save_marketplace_agent(
        agent_id            = agent_id,
        name                = name,
        icon                = (agent_def.get("icon") or "🤖").strip()[:8],
        description         = str(agent_def.get("description") or "")[:512],
        system_prompt       = prompt,
        keywords            = agent_def.get("keywords") or [],
        preferred_providers = agent_def.get("preferred_providers") or [],
        temperature         = float(agent_def.get("temperature", 0.7)),
        tier                = str(agent_def.get("tier") or "standard").strip(),
        source              = "imported_url",
        org_id              = org_id,
    )
    return {"id": agent_id, "name": name, "source_url": url, "status": "imported"}


@router.get("/marketplace/agents/{agent_id}/versions")
def get_marketplace_agent_versions(agent_id: str):
    from ..db import list_marketplace_agent_versions
    versions = list_marketplace_agent_versions(agent_id)
    return {"agent_id": agent_id, "versions": versions}


@router.get("/marketplace/agents/{agent_id}/reviews")
def get_marketplace_agent_reviews(agent_id: str):
    from ..db import list_marketplace_agent_reviews
    reviews = list_marketplace_agent_reviews(agent_id)
    avg = (sum(r["rating"] for r in reviews) / len(reviews)) if reviews else None
    return {
        "agent_id":     agent_id,
        "reviews":      reviews,
        "count":        len(reviews),
        "average_rating": round(avg, 2) if avg is not None else None,
    }


@router.post("/marketplace/agents/{agent_id}/reviews", status_code=201)
async def submit_marketplace_agent_review(agent_id: str, request: Request):
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        return _api_error("Invalid JSON body", "validation_error", 422)

    username = (body.get("username") or "").strip()
    comment  = str(body.get("comment") or "").strip()
    try:
        rating = int(body.get("rating", 0))
    except (TypeError, ValueError):
        rating = 0

    if not username:
        return _api_error("username is required", "validation_error", 422)
    if not 1 <= rating <= 5:
        return _api_error("rating must be an integer 1–5", "validation_error", 422)

    from ..db import save_marketplace_agent_review
    review = save_marketplace_agent_review(
        agent_id=agent_id,
        username=username,
        rating=rating,
        comment=comment,
    )
    return {"agent_id": agent_id, "review": review, "status": "saved"}


@router.delete("/marketplace/agents/{agent_id}", status_code=200)
def delete_marketplace_agent(agent_id: str):
    from ..db import delete_marketplace_agent as db_delete_agent
    deleted = db_delete_agent(agent_id)
    if not deleted:
        return _api_error(
            f"Agent '{agent_id}' not found or is a built-in agent",
            "not_found",
            404,
        )
    return {"id": agent_id, "status": "deleted"}


# ═══════════════════════════════════════════════════════════════════════════════
#  Multi-agent reasoning
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/reason/debate")
async def reason_debate(request: Request):
    """Multi-agent red/blue team debate.

    POST body:
      {
        "claim":  "The earth is the best planet",
        "rounds": 2,
        "model_a": "",   // optional, leave blank for auto-routing
        "model_b": ""
      }

    Returns the full debate transcript + impartial judge verdict.
    """
    from ..thinking import (
        build_debate_position_prompt,
        build_debate_verdict_prompt,
        parse_debate_turn,
        parse_debate_verdict,
    )

    body = {}
    try:
        body = await request.json()
    except Exception:
        pass

    claim = (body.get("claim") or "").strip()
    if not claim:
        return _api_error("claim is required", "validation_error", 422)

    try:
        safe_claim = check_user_task(claim, policy_profile=_config.get("safety_profile", "standard"))
    except GuardrailViolation as exc:
        _push_safety_event("block", {
            "scope": "input", "tool": "reason_debate",
            "label": claim[:120],
            "profile": _config.get("safety_profile", "standard"),
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
        return _api_error(exc.reason, exc.code, 422)

    num_rounds = max(1, min(int(body.get("rounds", 2)), 5))
    rounds_transcript: List[Dict[str, Any]] = []
    providers_used: List[Dict[str, str]] = []

    prop_argument = ""
    crit_argument = ""

    for round_num in range(1, num_rounds + 1):
        prop_prompt = build_debate_position_prompt(safe_claim, "proponent", prior_round=crit_argument)
        prop_resp, prop_provider = call_llm_with_fallback(
            [{"role": "user", "content": prop_prompt}], safe_claim
        )
        prop_data = parse_debate_turn(prop_resp.get("content") or str(prop_resp))
        prop_argument = prop_data["argument"]

        crit_prompt = build_debate_position_prompt(safe_claim, "critic", prior_round=prop_argument)
        crit_resp, crit_provider = call_llm_with_fallback(
            [{"role": "user", "content": crit_prompt}], safe_claim
        )
        crit_data = parse_debate_turn(crit_resp.get("content") or str(crit_resp))
        crit_argument = crit_data["argument"]

        rounds_transcript.append({
            "round": round_num,
            "proponent": prop_argument,
            "proponent_key_points": prop_data["key_points"],
            "proponent_confidence": prop_data["confidence"],
            "critic": crit_argument,
            "critic_key_points": crit_data["key_points"],
            "critic_confidence": crit_data["confidence"],
        })
        providers_used.append({"round": str(round_num), "proponent": prop_provider, "critic": crit_provider})

    verdict_prompt = build_debate_verdict_prompt(safe_claim, rounds_transcript)
    verdict_resp, verdict_provider = call_llm_with_fallback(
        [{"role": "user", "content": verdict_prompt}], safe_claim
    )
    verdict_data = parse_debate_verdict(verdict_resp.get("content") or str(verdict_resp))

    return {
        "claim":                      safe_claim,
        "rounds_completed":           num_rounds,
        "transcript":                 rounds_transcript,
        "verdict":                    verdict_data.get("verdict", "inconclusive"),
        "synthesis":                  verdict_data.get("synthesis", ""),
        "strongest_proponent_point":  verdict_data.get("strongest_proponent_point", ""),
        "strongest_critic_point":     verdict_data.get("strongest_critic_point", ""),
        "confidence":                 verdict_data.get("confidence", 0.5),
        "providers":                  providers_used,
        "verdict_provider":           verdict_provider,
    }


# ═══════════════════════════════════════════════════════════════════════════════
#  Orchestration
# ═══════════════════════════════════════════════════════════════════════════════


def _orchestrator_llm(prompt: str, task: str = "") -> str:
    result, _pid = call_llm_with_fallback([{"role":"user","content":prompt}], task)
    if isinstance(result, dict):
        return result.get("content", str(result))
    return str(result)


def _save_autonomy_checkpoint(trace_id: str, step_idx: int, goal: str, events: list[dict]) -> None:
    try:
        _save_checkpoint(trace_id, step_idx, {"task": goal, "trace_id": trace_id, "events": list(events)})
    except Exception:
        pass


@router.post("/orchestrate/hierarchical")
async def hierarchical_orchestrate(request: Request):
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        pass

    goal = (body.get("goal") or "").strip()
    if not goal:
        return _api_error("goal is required", "validation_error", 422)

    try:
        goal = check_user_task(goal)
    except GuardrailViolation as exc:
        _push_safety_event("block", {
            "scope": "input",
            "tool": "orchestrate_hierarchical",
            "label": goal[:120],
            "profile": _config.get("safety_profile", "standard"),
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
        return _api_error(exc.reason, exc.code, 422)

    max_subtasks = int(body.get("max_subtasks", 6))
    skip_review  = bool(body.get("skip_review", False))
    skip_verify  = bool(body.get("skip_verify", False))

    try:
        from ..autonomy import HierarchicalOrchestrator
        orch = HierarchicalOrchestrator(
            _orchestrator_llm,
            max_parallel=2,
            skip_review=skip_review,
            skip_verify=skip_verify,
        )
        hr = orch.run(goal, max_subtasks=max_subtasks)
        trace_id = secrets.token_hex(8)
        result = {
            "trace_id":         trace_id,
            "goal":             hr.goal,
            "plan":             hr.plan,
            "execution":        hr.execution,
            "review":           hr.review,
            "verification":     hr.verification,
            "final_output":     hr.final_output,
            "execution_time":   round(hr.execution_time, 3),
            "stages_completed": hr.stages_completed,
        }
        autonomy_traces[trace_id] = {"type": "hierarchical", "status": "done", **result}
        db_save_autonomy_trace(trace_id, autonomy_traces[trace_id])
        return result
    except Exception as exc:
        return _api_error(str(exc), "orchestration_error", 500)


@router.get("/orchestrate/hierarchical/{trace_id}")
def get_hierarchical_trace(trace_id: str):
    trace = autonomy_traces.get(trace_id) or db_load_autonomy_trace(trace_id)
    if trace is None:
        return JSONResponse({"error": "trace not found"}, status_code=404)
    return trace


# ═══════════════════════════════════════════════════════════════════════════════
#  Agent state
# ═══════════════════════════════════════════════════════════════════════════════


@router.post("/agents/state")
async def save_agent_state(request: Request):
    body: dict = {}
    try:
        body = await request.json()
    except Exception:
        return _api_error("Invalid JSON body", "validation_error", 422)
    agent_id = (body.get("agent_id") or "").strip()
    state = body.get("state")
    ttl = int(body.get("ttl") or 86400)
    if not agent_id:
        return _api_error("agent_id is required", "validation_error", 422)
    if state is None:
        return _api_error("state is required", "validation_error", 422)
    from ..db import save_pref as _save_pref
    _save_pref(f"agent_state:{agent_id}", json.dumps({"state": state, "updated_at": time.time()}))
    return {"agent_id": agent_id, "saved": True, "ttl": ttl}


@router.get("/agents/state/{agent_id}")
def get_agent_state(agent_id: str):
    from ..db import load_pref as _load_pref
    raw = _load_pref(f"agent_state:{agent_id}", "")
    if not raw:
        return _api_error(f"State for agent '{agent_id}' not found", "not_found", 404)
    try:
        data = json.loads(raw) if isinstance(raw, str) else raw
    except Exception:
        data = {"state": raw}
    return {"agent_id": agent_id, "state": data.get("state"), "updated_at": data.get("updated_at")}


@router.get("/agents/active")
def list_active_agents():
    from ..agents.registry import SPECIALIST_AGENTS
    return {
        "agents": [
            {
                "id": a.id,
                "name": a.name,
                "icon": a.icon,
                "description": a.description,
                "keywords": a.keywords,
                "preferred_providers": a.preferred_providers,
                "temperature": a.temperature,
                "tier": a.tier,
            }
            for a in SPECIALIST_AGENTS
        ],
        "total": len(SPECIALIST_AGENTS),
    }


# ── nostack skill routes ───────────────────────────────────────────────────


def _import_nostack():
    """Import nostack registry, handling the path resolution."""
    import sys, os
    from pathlib import Path
    root = Path(__file__).resolve().parents[2]
    nostack_path = root / "nostack"
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    if str(nostack_path.parent) not in sys.path:
        sys.path.insert(0, str(nostack_path.parent))
    from nostack.registry import list_skill_names, get_skill_agent, get_skill_prompt, run_skill
    return list_skill_names, get_skill_agent, get_skill_prompt, run_skill


@router.get("/nostack/skills")
def list_nostack_skills():
    """List all available nostack virtual team skills."""
    try:
        list_skill_names, get_skill_agent, _, _ = _import_nostack()
        skills = []
        for name in list_skill_names():
            agent = get_skill_agent(name)
            skills.append({
                "id": f"nostack-{name}",
                "command": f"/{name}",
                "name": agent.name if agent else name,
                "description": agent.description if agent else "",
                "tier": agent.tier if agent else "standard",
            })
        return {"skills": skills, "total": len(skills)}
    except ImportError:
        return {"skills": [], "total": 0, "error": "nostack not installed"}


@router.post("/nostack/skills/{skill_name}/run")
async def run_nostack_skill(skill_name: str, request: Request):
    """Run a nostack skill against the agent pipeline."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}

    task = body.get("task", "")
    history = body.get("history")
    provider = body.get("provider", "")
    model = body.get("model", "")

    try:
        _, _, _, run_skill = _import_nostack()
        result = run_skill(skill_name, task=task, history=history,
                          provider=provider, model=model)
        return result
    except ImportError:
        return {"error": "nostack not installed", "skill_name": skill_name}


@router.get("/nostack/skills/{skill_name}")
def get_nostack_skill_prompt(skill_name: str):
    """Get the full system prompt for a nostack skill."""
    try:
        _, get_skill_agent, get_skill_prompt, _ = _import_nostack()
        prompt = get_skill_prompt(skill_name)
        agent = get_skill_agent(skill_name)
        if prompt is None:
            return {"error": f"Skill not found: {skill_name}"}
        return {
            "skill": skill_name,
            "name": agent.name if agent else skill_name,
            "description": agent.description if agent else "",
            "system_prompt": prompt,
        }
    except ImportError:
        return {"error": "nostack not installed"}


@router.post("/nostack/sprint")
async def run_nostack_sprint(request: Request):
    """Run a nosprint — a chain of nostack skills in sequence."""
    body = {}
    try:
        body = await request.json()
    except Exception:
        body = {}

    task = body.get("task", "")
    skills = body.get("skills", [])
    provider = body.get("provider", "")

    if not task or not skills:
        return {"error": "task and skills list are required"}

    try:
        _, _, _, run_skill = _import_nostack()
    except ImportError:
        return {"error": "nostack not installed"}

    sprint_id = f"sprint-{uuid.uuid4().hex[:8]}"
    results = []
    context = task

    for skill_name in skills:
        enriched_task = (
            f"Previous sprint context:\n{context[:2000]}\n\n"
            f"Now run /{skill_name} on this task: {task}"
        )
        result = run_skill(skill_name, task=enriched_task, provider=provider)
        results.append({
            "skill": skill_name,
            "result": result.get("result", "")[:2000],
        })
        if result.get("result"):
            context = result["result"][:2000]
        # Persist intermediate results
        from src.db import save_pref
        save_pref(f"nostack.sprint.{sprint_id}.{skill_name}",
                  json.dumps({"result": result.get("result", "")[:4000]}))

    return {
        "sprint_id": sprint_id,
        "task": task,
        "skills_run": len(results),
        "results": results,
        "status": "completed",
    }
