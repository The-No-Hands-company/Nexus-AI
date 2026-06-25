import os
import uuid
import json
import asyncio
import threading
import time
import base64
from fastapi import Request, HTTPException, APIRouter
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import ValidationError

router = APIRouter()

from ..agent import (
    run_agent_task, stream_agent_task, get_providers_list, call_llm_with_fallback, _push_safety_event, _config, PROVIDERS,
    PROVIDER_CAPABILITIES, _PROVIDER_BENCHMARKS,
)
from ..safety import GuardrailViolation, check_user_task
from ._helpers import (
    _v1_error, _v1_quota_error_response, _normalize_response_format, _validate_json_output,
    _evaluate_rate_limit, _principal_from_request, _provider_capability_flags,
    _provider_capabilities_list, _read_json_body,
)
from ..api.state import get_rag_system
from ..api.schemas import (
    V1EmbeddingsRequest, V1ChatCompletionsRequest, CompletionRequest,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _v1_models_catalog() -> list[dict]:
    providers = get_providers_list()
    provider_models = []
    for provider in providers:
        if isinstance(provider, dict):
            provider_id = str(provider.get("id", "")).strip()
        else:
            provider_id = str(provider).strip()
        if not provider_id:
            continue
        provider_models.append(
            {
                "id": f"nexus-ai/{provider_id}",
                "object": "model",
                "created": 0,
                "owned_by": "nexus-systems",
            }
        )
    return [
        {"id": "nexus-ai", "object": "model", "created": 0, "owned_by": "nexus-systems"},
        {"id": "nexus-ai/auto", "object": "model", "created": 0, "owned_by": "nexus-systems"},
    ] + provider_models


def _normalize_embeddings_input(raw_input):
    if isinstance(raw_input, str):
        text = raw_input
        return [text], max(1, len(text.split()))
    if not isinstance(raw_input, list) or not raw_input:
        raise ValueError("input is required")
    if all(isinstance(item, str) for item in raw_input):
        texts = raw_input
        token_count = sum(max(1, len(item.split())) for item in texts)
        return texts, token_count
    if all(isinstance(item, int) for item in raw_input):
        token_ids = raw_input
        return [" ".join(str(token) for token in token_ids)], max(1, len(token_ids))
    if all(isinstance(item, list) and all(isinstance(token, int) for token in item) for item in raw_input):
        token_batches = raw_input
        texts = [" ".join(str(token) for token in token_batch) for token_batch in token_batches]
        token_count = sum(max(1, len(token_batch)) for token_batch in token_batches)
        return texts, token_count
    raise ValueError("input must be a string, list of strings, token array, or list of token arrays")


def _estimate_text_tokens(text: str) -> int:
    normalized = str(text or "").strip()
    if not normalized:
        return 0
    return len(normalized.split())


def _resolve_provider_order_from_model(model: str) -> list[str] | None:
    raw = str(model or "").strip()
    if not raw:
        return None
    normalized = raw
    if normalized.startswith("nexus-ai/"):
        normalized = normalized.split("/", 1)[1].strip()
    elif normalized == "nexus-ai":
        normalized = "auto"
    if normalized in {"", "auto"}:
        return None
    available = {str(p.get("id") or "").strip() for p in get_providers_list() if isinstance(p, dict)}
    if normalized in available:
        return [normalized]
    return None


_FILES_DIR = os.path.join(os.getenv("DATA_DIR", "/data"), "files")


def _ensure_files_dir():
    os.makedirs(_FILES_DIR, exist_ok=True)


def _file_meta_path(file_id: str) -> str:
    return os.path.join(_FILES_DIR, f"{file_id}.meta.json")


def _load_file_meta(file_id: str) -> dict | None:
    p = _file_meta_path(file_id)
    if not os.path.exists(p):
        return None
    with open(p) as f:
        return json.load(f)


def _list_file_metas() -> list:
    _ensure_files_dir()
    metas = []
    for name in os.listdir(_FILES_DIR):
        if name.endswith(".meta.json"):
            try:
                with open(os.path.join(_FILES_DIR, name)) as f:
                    metas.append(json.load(f))
            except Exception:
                pass
    return sorted(metas, key=lambda m: m.get("created_at", 0), reverse=True)


# ── Models ──────────────────────────────────────────────────────────────────

@router.get("/v1/models")
def v1_models():
    return {
        "object": "list",
        "data": _v1_models_catalog(),
    }


@router.get("/v1/models/capabilities")
def v1_models_capabilities():
    """Return capability matrix for all providers (vision, json_mode, tools, reasoning, streaming)."""
    data = []
    for provider in get_providers_list():
        pid = str(provider.get("id") or "")
        caps = dict(PROVIDER_CAPABILITIES.get(pid, {}))
        item = {
            "id": str(provider.get("model") or pid),
            "provider": pid,
            "label": provider.get("label", pid),
            "capabilities": caps,
            "tools": bool(caps.get("tools", False)),
            "json_mode": bool(caps.get("json_mode", False)),
            "reasoning": bool(caps.get("reasoning", False)),
            "vision": bool(caps.get("vision", False)),
            "embeddings": bool(caps.get("embeddings", provider.get("openai_compat", False))),
            "streaming": bool(caps.get("streaming", False)),
        }
        data.append(item)
    return {"object": "list", "data": data}


@router.get("/v1/models/{model_id}")
def v1_get_model(model_id: str):
    """Get detailed info for a specific model."""
    for pid, cfg in PROVIDERS.items():
        if cfg["default_model"] == model_id or pid == model_id:
            benchmarks = _PROVIDER_BENCHMARKS.get(pid, {})
            return {
                "id": model_id,
                "provider": pid,
                "label": cfg["label"],
                "default_model": cfg["default_model"],
                "openai_compat": cfg.get("openai_compat", False),
                "capabilities": PROVIDER_CAPABILITIES.get(pid, {}),
                "benchmarks": {
                    "estimated_latency_ms": benchmarks.get("latency_ms", 0),
                    "quality_score": benchmarks.get("quality", 0),
                    "tier": benchmarks.get("tier", "unknown"),
                    "cost_tier": benchmarks.get("cost_tier", "unknown"),
                },
            }
    return _v1_error(
        f"Model not found: {model_id}",
        err_type="not_found_error",
        status_code=404,
        code="model_not_found",
    )


@router.get("/v1/models/capabilities")
def v1_model_capabilities():
    providers = get_providers_list()
    return {
        "object": "list",
        "data": [
            {
                "id": f"nexus-ai/{provider['id']}",
                "object": "model",
                "label": provider["label"],
                "provider": provider["id"],
                "model": provider["model"],
                "openai_compat": provider.get("openai_compat", False),
                "keyless": provider.get("keyless", False),
                "available": provider.get("available", False),
                "rate_limited": provider.get("rate_limited", False),
                **_provider_capability_flags(provider),
                "capabilities": _provider_capabilities_list(_provider_capability_flags(provider)),
            }
            for provider in providers
        ],
    }


@router.get("/v1/models/{model_id:path}")
def v1_model_retrieve(model_id: str):
    requested_id = model_id
    if not requested_id.startswith("nexus-ai"):
        requested_id = f"nexus-ai/{requested_id}"
    for model in _v1_models_catalog():
        if model["id"] == requested_id:
            return model
    return _v1_error(
        f"Model '{requested_id}' not found",
        "not_found_error",
        404,
        "model_not_found",
    )


@router.get("/v1/capabilities")
def v1_capabilities():
    """Return platform-level capability metadata for OpenAI-compatible clients."""
    providers = get_providers_list()
    flags = [_provider_capability_flags(provider) for provider in providers]
    return {
        "object": "capabilities",
        "provider_count": len(providers),
        "tools": any(flag["tools"] for flag in flags),
        "vision": any(flag["vision"] for flag in flags),
        "embeddings": any(flag["embeddings"] for flag in flags),
        "json_mode": any(flag["json_mode"] for flag in flags),
        "reasoning": any(flag["reasoning"] for flag in flags),
    }


# ── Images ──────────────────────────────────────────────────────────────────

@router.post("/v1/images/generations")
async def v1_images_generations(request: Request):
    """OpenAI-compatible local image generation endpoint."""
    try:
        body = await _read_json_body(request)
    except HTTPException as exc:
        return _v1_error(str(exc.detail), "invalid_request_error", exc.status_code)
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return _v1_error("prompt is required", "invalid_request_error", 422)
    size = str(body.get("size") or "1024x1024").strip().lower()
    width, height = 1024, 1024
    if "x" in size:
        try:
            width, height = [int(x) for x in size.split("x", 1)]
        except Exception:
            return _v1_error("size must be in WxH format", "invalid_request_error", 422)
    try:
        from ..generation import generate_image_local
        image_bytes = generate_image_local(
            prompt=prompt,
            negative_prompt=str(body.get("negative_prompt") or ""),
            width=width,
            height=height,
            steps=int(body.get("steps") or 20),
            backend=str(body.get("backend") or "ollama_flux"),
            model=str(body.get("model") or "auto"),
        )
    except ValueError as exc:
        return _v1_error(str(exc), "invalid_request_error", 422)
    except Exception as exc:
        return _v1_error(str(exc), "server_error", 500)
    return {
        "created": int(time.time()),
        "data": [
            {
                "b64_json": base64.b64encode(image_bytes).decode("ascii"),
                "revised_prompt": prompt,
            }
        ],
    }


# ── Embeddings ──────────────────────────────────────────────────────────────

@router.post("/v1/embeddings")
async def v1_embeddings(request: Request):
    try:
        payload = V1EmbeddingsRequest(**(await request.json()))
    except ValidationError:
        return _v1_error("Invalid embeddings request", "validation_error", 422, "validation_error")
    try:
        inputs, prompt_tokens = _normalize_embeddings_input(payload.input)
    except ValueError as exc:
        return _v1_error(str(exc), "validation_error", 422, "validation_error")
    try:
        embeddings = get_rag_system().embedding_model.embed_batch(inputs)
        if hasattr(embeddings, "tolist"):
            embeddings = embeddings.tolist()
    except Exception as exc:
        return _v1_error(f"Failed to generate embeddings: {exc}", "model_error", 500, "model_error")
    return {
        "object": "list",
        "data": [
            {"object": "embedding", "embedding": list(vec), "index": idx}
            for idx, vec in enumerate(embeddings)
        ],
        "model": payload.model,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "total_tokens": prompt_tokens,
        },
    }


# ── Chat Completions ────────────────────────────────────────────────────────

@router.post("/v1/chat/completions")
async def v1_chat_completions(request: Request):
    try:
        payload = V1ChatCompletionsRequest(**(await request.json()))
    except ValidationError:
        return _v1_error("Invalid chat completions request", "validation_error", 422, "validation_error")
    messages = payload.messages
    stream = payload.stream
    model = payload.model
    model_provider_order = _resolve_provider_order_from_model(model)
    if str(model or "").strip() and model_provider_order is None and str(model).strip() not in {"nexus-ai", "nexus-ai/auto", "auto"}:
        return _v1_error(
            f"Model '{model}' not found",
            "not_found_error",
            404,
            "model_not_found",
        )
    response_format = payload.response_format
    payload_user = payload.user or ""
    principal = _principal_from_request(request, payload_user=payload_user)
    rate_result = _evaluate_rate_limit(principal)
    if not rate_result.get("allowed", True):
        return _v1_quota_error_response(rate_result)
    if not messages:
        return _v1_error("messages is required", "validation_error", 422, "validation_error")
    system_parts = [m.content for m in messages if m.role == "system"]
    turns = [m for m in messages if m.role != "system"]
    if not turns or turns[-1].role != "user":
        return _v1_error("Last message must be role=user", "validation_error", 422, "validation_error")
    raw_task = turns[-1].content
    _has_vision = isinstance(raw_task, list) and any(
        p.get("type") == "image_url" for p in raw_task if isinstance(p, dict)
    )
    if isinstance(raw_task, list):
        task = " ".join(
            part.get("text", "") for part in raw_task if part.get("type") == "text"
        )
    else:
        task = str(raw_task)
    if system_parts:
        task = "[System instructions: " + " ".join(system_parts) + "]\n\n" + task
    try:
        task = check_user_task(task)
    except GuardrailViolation as exc:
        _push_safety_event("block", {
            "scope": "input",
            "tool": "v1_chat_completions",
            "label": task[:120],
            "profile": _config.get("safety_profile", "standard"),
            "verdict": {"allowed": False, "reason": exc.reason, "code": exc.code, "detail": exc.detail},
        })
        return _v1_error(exc.reason, exc.code, 422, exc.code)
    try:
        response_format_cfg = _normalize_response_format(response_format)
    except ValueError as exc:
        return _v1_error(str(exc), "validation_error", 422, "validation_error")
    response_format_mode = response_format_cfg.get("mode")
    response_schema = response_format_cfg.get("schema")
    task = _apply_response_format_hint(task, response_format_mode or "", response_schema)
    history = [{"role": m.role, "content": m.content if isinstance(m.content, str)
                else " ".join(p.get("text", "") for p in m.content if p.get("type") == "text")}
               for m in turns[:-1]]
    cid = f"chatcmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    if stream:
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()
        stop_evt = threading.Event()
        if _has_vision:
            _raw_msgs_s = []
            for _m in turns:
                if isinstance(_m.content, list):
                    _raw_msgs_s.append({"role": _m.role, "content": _m.content})
                else:
                    _raw_msgs_s.append({"role": _m.role, "content": str(_m.content)})
            if system_parts:
                _raw_msgs_s.insert(0, {"role": "system", "content": " ".join(system_parts)})

            async def _vision_stream():
                try:
                    _vr, _vp = await asyncio.get_event_loop().run_in_executor(
                        None, lambda: call_llm_with_fallback(_raw_msgs_s, task="vision", provider_order=model_provider_order)
                    )
                    _vc = _vr.get("content", str(_vr))
                except Exception as _exc:
                    _vc = f"Vision error: {_exc}"
                _chunk = {
                    "id": cid, "object": "chat.completion.chunk",
                    "created": created, "model": model,
                    "choices": [{"index": 0, "delta": {"content": _vc}, "finish_reason": "stop"}],
                }
                yield f"data: {json.dumps(_chunk)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(_vision_stream(), media_type="text/event-stream",
                                      headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        if model_provider_order:
            _raw_msgs_s = []
            for _m in turns:
                if isinstance(_m.content, list):
                    _raw_msgs_s.append({"role": _m.role, "content": _m.content})
                else:
                    _raw_msgs_s.append({"role": _m.role, "content": str(_m.content)})
            if system_parts:
                _raw_msgs_s.insert(0, {"role": "system", "content": " ".join(system_parts)})

            async def _provider_stream():
                try:
                    _resp, _pid = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: call_llm_with_fallback(_raw_msgs_s, task=task, provider_order=model_provider_order),
                    )
                    _content = _resp.get("content", str(_resp))
                except Exception as _exc:
                    _pid = model_provider_order[0]
                    _content = f"Provider error: {_exc}"
                _chunk = {
                    "id": cid,
                    "object": "chat.completion.chunk",
                    "created": created,
                    "model": model,
                    "choices": [{"index": 0, "delta": {"content": _content}, "finish_reason": "stop"}],
                    "_nexus": {"provider": _pid},
                }
                yield f"data: {json.dumps(_chunk)}\n\n"
                yield "data: [DONE]\n\n"

            return StreamingResponse(_provider_stream(), media_type="text/event-stream",
                                      headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

        def _run():
            try:
                for evt in stream_agent_task(task, history, [], stop_evt):
                    loop.call_soon_threadsafe(queue.put_nowait, evt)
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": str(e)})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=_run, daemon=True).start()

        async def _generate():
            full_content = ""
            try:
                while True:
                    evt = await queue.get()
                    if evt is None:
                        break
                    etype = evt.get("type", "")
                    delta_text = None
                    finish = None
                    if etype == "done":
                        content = evt.get("content", "")
                        if response_format_mode == "json":
                            try:
                                validated = _validate_json_output(content, response_schema)
                                delta_text = json.dumps(validated)
                            except ValueError as exc:
                                delta_text = json.dumps({
                                    "error": {
                                        "message": f"response_format=json required valid JSON but model output failed to parse: {exc}",
                                        "type": "invalid_response_format",
                                        "code": "invalid_response_format",
                                        "status": 422,
                                    }
                                })
                            finish = "stop"
                        else:
                            delta_text = content
                            finish = "stop"
                    elif etype == "think":
                        delta_text = f"<think>{evt.get('thought', '')}</think>"
                    elif etype == "tool":
                        delta_text = f"\n[{evt.get('icon', '🔧')} {evt.get('action', 'tool')}]\n"
                    elif etype == "error":
                        delta_text = f"\nError: {evt.get('message', '')}"
                        finish = "stop"
                    if delta_text is not None:
                        chunk = {
                            "id": cid, "object": "chat.completion.chunk",
                            "created": created, "model": model,
                            "choices": [{"index": 0, "delta": {"content": delta_text}, "finish_reason": finish}],
                        }
                        yield f"data: {json.dumps(chunk)}\n\n"
            except asyncio.CancelledError:
                stop_evt.set()
            yield "data: [DONE]\n\n"

        return StreamingResponse(_generate(), media_type="text/event-stream",
                                  headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    sid = f"v1-{uuid.uuid4().hex[:8]}"
    _result_provider = ""
    _result_model = ""
    if _has_vision:
        _raw_msgs = []
        for m in turns:
            if isinstance(m.content, list):
                _raw_msgs.append({"role": m.role, "content": m.content})
            else:
                _raw_msgs.append({"role": m.role, "content": str(m.content)})
        if system_parts:
            _raw_msgs.insert(0, {"role": "system", "content": " ".join(system_parts)})
        try:
            _vision_resp, _vision_pid = call_llm_with_fallback(_raw_msgs, task="vision", provider_order=model_provider_order)
            output = _vision_resp.get("content", str(_vision_resp))
            _result_provider = _vision_pid
        except Exception as exc:
            return _v1_error(str(exc), "vision_error", 500, "vision_error")
    elif model_provider_order:
        _raw_msgs = []
        for m in turns:
            if isinstance(m.content, list):
                _raw_msgs.append({"role": m.role, "content": m.content})
            else:
                _raw_msgs.append({"role": m.role, "content": str(m.content)})
        if system_parts:
            _raw_msgs.insert(0, {"role": "system", "content": " ".join(system_parts)})
        try:
            _direct_resp, _direct_pid = call_llm_with_fallback(_raw_msgs, task=task, provider_order=model_provider_order)
            output = _direct_resp.get("content", str(_direct_resp))
            _result_provider = _direct_pid
        except Exception as exc:
            return _v1_error(str(exc), "provider_error", 500, "provider_error")
    else:
        result = run_agent_task(task, history, [], sid=sid)
        output = result.get("result", "")
        _result_provider = result.get("provider", "")
        _result_model = result.get("model", "")
    if response_format_mode == "json":
        try:
            validated = _validate_json_output(output, response_schema)
            output = json.dumps(validated)
        except ValueError:
            return _v1_error(
                "response_format=json required valid JSON but model output failed to parse",
                "invalid_response_format",
                422,
                "invalid_response_format",
            )
    prompt_tokens = _estimate_text_tokens(task)
    completion_tokens = _estimate_text_tokens(output)
    total_tokens = prompt_tokens + completion_tokens
    return {
        "id": cid,
        "object": "chat.completion",
        "created": created,
        "model": model,
        "choices": [{
            "index": 0,
            "message": {"role": "assistant", "content": output},
            "finish_reason": "stop",
        }],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": total_tokens,
        },
        "_nexus": {"provider": _result_provider, "model": _result_model},
    }


# ── Legacy Completions ──────────────────────────────────────────────────────

@router.get("/v1/")
def v1_root():
    """Version root metadata for lifecycle-aware clients."""
    return {
        "version": "v1",
        "status": "active",
        "deprecated_paths": [
            {
                "path": "/v1/completions",
                "sunset": "2026-12-31T00:00:00+00:00",
                "replacement": "/v1/chat/completions",
            }
        ],
    }


@router.post("/v1/completions")
async def v1_completions(request: Request):
    """Legacy OpenAI-compatible text completions (non-chat) endpoint."""
    try:
        body = await request.json()
    except Exception:
        return _v1_error("invalid JSON body", "invalid_request_error", 400)
    try:
        payload = CompletionRequest(**body)
    except Exception as exc:
        return _v1_error(str(exc), "validation_error", 422)
    principal = _principal_from_request(request, payload_user=payload.user or "")
    rate_result = _evaluate_rate_limit(principal)
    if not rate_result.get("allowed", True):
        return _v1_quota_error_response(rate_result)
    prompt = payload.prompt_text()
    if not prompt:
        return _v1_error("prompt is required", "invalid_request_error", 422)
    cid = f"cmpl-{uuid.uuid4().hex[:12]}"
    created = int(time.time())
    if payload.stream:
        stop_evt = threading.Event()
        loop = asyncio.get_event_loop()
        queue: asyncio.Queue = asyncio.Queue()

        def _run():
            try:
                for evt in stream_agent_task(prompt, [], [], stop_evt):
                    loop.call_soon_threadsafe(queue.put_nowait, evt)
            except Exception as e:
                loop.call_soon_threadsafe(queue.put_nowait, {"type": "error", "message": str(e)})
            finally:
                loop.call_soon_threadsafe(queue.put_nowait, None)

        threading.Thread(target=_run, daemon=True).start()

        async def _gen():
            while True:
                evt = await queue.get()
                if evt is None:
                    break
                etype = evt.get("type", "")
                text = None
                finish = None
                if etype == "done":
                    text = evt.get("content", "")
                    finish = "stop"
                elif etype == "think":
                    text = ""
                elif etype == "error":
                    text = evt.get("message", "")
                    finish = "stop"
                if text is not None:
                    chunk = {
                        "id": cid, "object": "text_completion",
                        "created": created, "model": payload.model,
                        "choices": [{"text": text, "index": 0, "finish_reason": finish, "logprobs": None}],
                    }
                    yield f"data: {json.dumps(chunk)}\n\n"
            yield "data: [DONE]\n\n"

        return StreamingResponse(_gen(), media_type="text/event-stream",
                                  headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    result = run_agent_task(prompt, [], [], sid=f"cmpl-{uuid.uuid4().hex[:8]}")
    output = result.get("result", "")
    prompt_tokens = _estimate_text_tokens(prompt)
    completion_tokens = _estimate_text_tokens(output)
    return {
        "id": cid,
        "object": "text_completion",
        "created": created,
        "model": payload.model,
        "choices": [{"text": output, "index": 0, "finish_reason": "stop", "logprobs": None}],
        "usage": {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        },
    }


# ── Audio ───────────────────────────────────────────────────────────────────

@router.post("/v1/audio/transcriptions")
async def v1_audio_transcriptions(request: Request):
    """Whisper-compatible STT using shared local/provider backend helpers."""
    form = await request.form()
    file_field = form.get("file")
    language = str(form.get("language", "")) or None
    response_format = str(form.get("response_format", "json"))
    include_diarization = str(form.get("include_diarization", "false")).lower() == "true"
    include_speaker_labels = str(form.get("include_speaker_labels", "false")).lower() == "true"
    include_analysis = str(form.get("include_analysis", "false")).lower() == "true"
    voice_profile_field = form.get("voice_profile")
    voice_profile_b64 = form.get("voice_profile_base64")
    if file_field is None:
        return _v1_error("file is required", "invalid_request_error", 422)
    audio_bytes = await file_field.read()
    mime_type = getattr(file_field, "content_type", None) or "audio/wav"
    try:
        from ..audio import AudioProviderError, analyse_audio, diarize_audio, identify_speaker, transcribe_audio
        result = transcribe_audio(audio_bytes, mime_type=mime_type, language=language, backend="auto")
    except AudioProviderError as exc:
        return _v1_error(str(exc), "model_error", 503)
    except ValueError as exc:
        return _v1_error(str(exc), "invalid_request_error", 422)
    except Exception as exc:
        return _v1_error(str(exc), "server_error", 500)
    if response_format == "text":
        return result.get("text", "")
    profile_bytes = None
    try:
        if voice_profile_field is not None and hasattr(voice_profile_field, "read"):
            profile_bytes = await voice_profile_field.read()
        elif voice_profile_b64:
            profile_bytes = base64.b64decode(str(voice_profile_b64))
    except Exception:
        return _v1_error("invalid voice profile", "invalid_request_error", 422)
    payload = {
        "text": result.get("text", ""),
        "language": result.get("language", language or "en"),
        "duration": result.get("duration_seconds", 0.0),
        "segments": result.get("segments", []),
        "backend": result.get("backend", "unknown"),
    }
    if include_diarization or include_speaker_labels:
        diarization = diarize_audio(audio_bytes)
        payload["diarization"] = diarization
        if diarization.get("ok"):
            payload["transcript_with_speakers"] = "\n".join(
                f"{segment.get('speaker', 'SPEAKER_01')}: {str(segment.get('text', '') or '').strip()}"
                for segment in diarization.get("segments", [])
                if str(segment.get("text", "") or "").strip()
            )
    if profile_bytes is not None or include_speaker_labels:
        payload["speaker_identification"] = identify_speaker(audio_bytes, voice_profile_bytes=profile_bytes)
    if include_analysis:
        payload["analysis"] = analyse_audio(audio_bytes, voice_profile_bytes=profile_bytes)
    return payload


@router.post("/v1/audio/speech")
async def v1_audio_speech(request: Request):
    """OpenAI-compatible TTS using shared local/provider backend helpers."""
    try:
        body = await request.json()
    except Exception:
        return _v1_error("invalid JSON body", "invalid_request_error", 400)
    text = str(body.get("input", "")).strip()
    voice = str(body.get("voice", "alloy"))
    fmt = str(body.get("response_format", "mp3")).lower()
    speed = float(body.get("speed", 1.0))
    if not text:
        return _v1_error("input is required", "invalid_request_error", 422)
    try:
        from ..audio import AudioProviderError, synthesize_speech
        audio_bytes = synthesize_speech(text, voice=voice, speed=speed, format=fmt, backend="auto")
    except AudioProviderError as exc:
        return _v1_error(str(exc), "model_error", 503)
    except ValueError as exc:
        return _v1_error(str(exc), "invalid_request_error", 422)
    except Exception as exc:
        return _v1_error(str(exc), "server_error", 500)
    media_map = {"mp3": "audio/mpeg", "opus": "audio/opus", "aac": "audio/aac",
                 "flac": "audio/flac", "wav": "audio/wav", "pcm": "audio/pcm"}
    filename_ext = fmt if fmt in media_map else "wav"
    return StreamingResponse(
        iter([audio_bytes]),
        media_type=media_map.get(fmt, "audio/wav"),
        headers={"Content-Disposition": f'attachment; filename="speech.{filename_ext}"'},
    )


# ── Files API ───────────────────────────────────────────────────────────────

@router.get("/v1/files")
def v1_list_files(request: Request, purpose: str = ""):
    _ensure_files_dir()
    metas = _list_file_metas()
    if purpose:
        metas = [m for m in metas if m.get("purpose") == purpose]
    return {"object": "list", "data": metas}


@router.post("/v1/files")
async def v1_upload_file(request: Request):
    _ensure_files_dir()
    form = await request.form()
    file_field = form.get("file")
    purpose = str(form.get("purpose", "assistants"))
    if file_field is None:
        return _v1_error("file is required", "invalid_request_error", 422)
    raw = await file_field.read()
    filename = getattr(file_field, "filename", "upload.bin")
    file_id = f"file-{uuid.uuid4().hex[:16]}"
    created_at = int(time.time())
    data_path = os.path.join(_FILES_DIR, file_id)
    with open(data_path, "wb") as fh:
        fh.write(raw)
    meta = {
        "id": file_id,
        "object": "file",
        "bytes": len(raw),
        "created_at": created_at,
        "filename": filename,
        "purpose": purpose,
        "status": "processed",
    }
    with open(_file_meta_path(file_id), "w") as fh:
        json.dump(meta, fh)
    return meta


@router.get("/v1/files/{file_id}")
def v1_get_file(file_id: str):
    meta = _load_file_meta(file_id)
    if meta is None:
        return _v1_error("file not found", "not_found_error", 404)
    return meta


@router.delete("/v1/files/{file_id}")
def v1_delete_file(file_id: str):
    meta = _load_file_meta(file_id)
    if meta is None:
        return _v1_error("file not found", "not_found_error", 404)
    for path in (_file_meta_path(file_id), os.path.join(_FILES_DIR, file_id)):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
    return {"id": file_id, "object": "file", "deleted": True}


@router.get("/v1/files/{file_id}/content")
def v1_get_file_content(file_id: str):
    meta = _load_file_meta(file_id)
    if meta is None:
        return _v1_error("file not found", "not_found_error", 404)
    data_path = os.path.join(_FILES_DIR, file_id)
    if not os.path.exists(data_path):
        return _v1_error("file content not found", "not_found_error", 404)
    return FileResponse(data_path, filename=meta.get("filename", file_id))


# ── Shared helper used by routes.py ─────────────────────────────────────────
# (_v1_models_catalog is re-exported for use in the webhook GET / endpoint)

def _apply_response_format_hint(task: str, response_format_mode: str = "", schema: dict | None = None) -> str:
    if not response_format_mode:
        return task
    if response_format_mode == "json" and not schema:
        return task + (
            "\n\nRespond with strict JSON only. "
            "The response must be valid JSON and contain no extra prose or markdown."
        )
    if response_format_mode == "json" and schema:
        compact_schema = json.dumps(schema, separators=(",", ":"))
        return task + (
            "\n\nRespond with strict JSON only and match this JSON Schema exactly: "
            f"{compact_schema}"
        )
    return task
