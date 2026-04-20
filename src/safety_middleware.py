import json
from typing import Any, Dict, Iterable, List, Tuple

from fastapi.responses import JSONResponse
from starlette.datastructures import MutableHeaders

from .safety_pipeline import describe_block, screen_input, screen_output
from .safety_types import SafetyAction, SafetySignal, SafetyVerdict, ThreatLevel


_REQUEST_METHODS_WITH_BODY = {"POST", "PUT", "PATCH"}
_TEXTUAL_RESPONSE_TYPES = (
    "application/json",
    "text/plain",
    "text/event-stream",
    "text/markdown",
)
_REQUEST_EXEMPT_PATHS = {"/safety/check", "/safety/pii-scan", "/safety/prompt-injection"}
_RESPONSE_EXEMPT_PREFIXES = ("/static/",)


def _max_threat(a: ThreatLevel, b: ThreatLevel) -> ThreatLevel:
    order = {
        ThreatLevel.NONE: 0,
        ThreatLevel.LOW: 1,
        ThreatLevel.MEDIUM: 2,
        ThreatLevel.HIGH: 3,
        ThreatLevel.CRITICAL: 4,
    }
    return a if order[a] >= order[b] else b


def _max_action(a: SafetyAction, b: SafetyAction) -> SafetyAction:
    order = {
        SafetyAction.ALLOW: 0,
        SafetyAction.WARN: 1,
        SafetyAction.REDACT: 2,
        SafetyAction.BLOCK: 3,
    }
    return a if order[a] >= order[b] else b


def _merge_verdicts(stage: str, verdicts: Iterable[SafetyVerdict], masked_changed: bool) -> SafetyVerdict:
    issues: List[SafetySignal] = []
    action = SafetyAction.ALLOW
    threat = ThreatLevel.NONE
    allowed = True
    for verdict in verdicts:
        issues.extend(verdict.issues)
        action = _max_action(action, verdict.action)
        threat = _max_threat(threat, verdict.threat)
        allowed = allowed and verdict.allowed
    if masked_changed and action == SafetyAction.ALLOW:
        action = SafetyAction.REDACT
    return SafetyVerdict(
        stage=stage,
        allowed=allowed,
        action=action,
        threat=threat,
        issues=issues,
        masked_text=None,
        pii_matches=[],
    )


def _sanitize_json_value(value: Any, *, request_mode: bool, allow_destructive: bool = False,
                         policy_profile: str | None = None) -> Tuple[Any, SafetyVerdict]:
    if isinstance(value, str):
        verdict = screen_input(value, allow_destructive=allow_destructive, policy_profile=policy_profile) if request_mode else screen_output(value)
        return (verdict.masked_text if verdict.masked_text is not None else value), verdict
    if isinstance(value, list):
        verdicts: List[SafetyVerdict] = []
        sanitized_items: List[Any] = []
        changed = False
        for item in value:
            sanitized, verdict = _sanitize_json_value(item, request_mode=request_mode, allow_destructive=allow_destructive, policy_profile=policy_profile)
            sanitized_items.append(sanitized)
            verdicts.append(verdict)
            changed = changed or sanitized != item
        return sanitized_items, _merge_verdicts("input" if request_mode else "output", verdicts, changed)
    if isinstance(value, dict):
        verdicts: List[SafetyVerdict] = []
        sanitized_dict: Dict[str, Any] = {}
        changed = False
        for key, item in value.items():
            sanitized, verdict = _sanitize_json_value(item, request_mode=request_mode, allow_destructive=allow_destructive, policy_profile=policy_profile)
            sanitized_dict[key] = sanitized
            verdicts.append(verdict)
            changed = changed or sanitized != item
        return sanitized_dict, _merge_verdicts("input" if request_mode else "output", verdicts, changed)
    return value, SafetyVerdict(stage="input" if request_mode else "output", allowed=True)


def _headers_to_dict(scope: Dict[str, Any]) -> Dict[str, str]:
    return {k.decode("latin1").lower(): v.decode("latin1") for k, v in scope.get("headers", [])}


def _set_scope_content_length(scope: Dict[str, Any], content_length: int) -> None:
    headers = [(k, v) for k, v in scope.get("headers", []) if k.lower() != b"content-length"]
    headers.append((b"content-length", str(content_length).encode("latin1")))
    scope["headers"] = headers


class SafetyPipelineMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        request_headers = _headers_to_dict(scope)
        content_type = request_headers.get("content-type", "")
        method = scope.get("method", "GET").upper()
        request_verdict = SafetyVerdict(stage="input", allowed=True)
        receive_to_use = receive

        if method in _REQUEST_METHODS_WITH_BODY and path not in _REQUEST_EXEMPT_PATHS:
            body = b""
            more_body = True
            while more_body:
                message = await receive()
                if message["type"] != "http.request":
                    continue
                body += message.get("body", b"")
                more_body = message.get("more_body", False)

            if body and "application/json" in content_type:
                try:
                    payload = json.loads(body.decode("utf-8"))
                except Exception:
                    payload = None
                if payload is not None:
                    from .agent import get_config

                    runtime_profile = str(get_config().get("safety_profile", "standard") or "standard")
                    allow_destructive = bool(payload.get("allow_destructive", False)) if isinstance(payload, dict) else False
                    policy_profile = payload.get("policy_profile", runtime_profile) if isinstance(payload, dict) else runtime_profile
                    sanitized_payload, request_verdict = _sanitize_json_value(
                        payload,
                        request_mode=True,
                        allow_destructive=allow_destructive,
                        policy_profile=policy_profile,
                    )
                    if request_verdict.action == SafetyAction.BLOCK:
                        issue = request_verdict.primary_issue()
                        error_code = issue.code if issue else "guardrail_violation"
                        message = describe_block(request_verdict)
                        payload = {
                            "error": message,
                            "type": error_code,
                            "safety": request_verdict.to_dict(),
                        }
                        if path.startswith("/v1/"):
                            payload = {
                                "error": {
                                    "message": message,
                                    "type": error_code,
                                    "code": error_code,
                                    "status": 422,
                                },
                                "message": message,
                                "type": error_code,
                                "code": error_code,
                                "safety": request_verdict.to_dict(),
                            }
                        response = JSONResponse(payload, status_code=422)
                        await response(scope, receive, send)
                        return
                    body = json.dumps(sanitized_payload).encode("utf-8")
                    _set_scope_content_length(scope, len(body))

            replayed_once = False

            async def replay_receive():
                nonlocal body, replayed_once
                if not replayed_once:
                    replayed_once = True
                    current = body
                    body = b""
                    return {"type": "http.request", "body": current, "more_body": False}
                return {"type": "http.disconnect"}

            receive_to_use = replay_receive

        scope["nexus_safety_request"] = request_verdict.to_dict()

        response_start = None
        response_body_chunks: List[bytes] = []
        response_content_type = ""
        sent_start = False

        async def send_wrapper(message):
            nonlocal response_start, response_content_type, sent_start
            if message["type"] == "http.response.start":
                response_start = dict(message)
                headers = MutableHeaders(raw=response_start["headers"])
                response_content_type = headers.get("content-type", "")
                headers["x-nexus-safety-action"] = request_verdict.action.value
                return

            if message["type"] != "http.response.body":
                await send(message)
                return

            if response_start is None:
                await send(message)
                return

            if path.startswith(_RESPONSE_EXEMPT_PREFIXES):
                if not sent_start:
                    sent_start = True
                    await send(response_start)
                await send(message)
                return

            if "text/event-stream" in response_content_type:
                if not sent_start:
                    sent_start = True
                    headers = MutableHeaders(raw=response_start["headers"])
                    if "content-length" in headers:
                        del headers["content-length"]
                    await send(response_start)
                chunk = message.get("body", b"")
                if chunk:
                    text = chunk.decode("utf-8", errors="replace")
                    verdict = screen_output(text)
                    if verdict.masked_text is not None:
                        message = dict(message)
                        message["body"] = verdict.masked_text.encode("utf-8")
                await send(message)
                return

            if not any(t in response_content_type for t in _TEXTUAL_RESPONSE_TYPES):
                if not sent_start:
                    sent_start = True
                    await send(response_start)
                await send(message)
                return

            response_body_chunks.append(message.get("body", b""))
            if message.get("more_body", False):
                return

            raw_body = b"".join(response_body_chunks)
            text = raw_body.decode("utf-8", errors="replace")
            redacted_text = text
            response_verdict = SafetyVerdict(stage="output", allowed=True)

            if "application/json" in response_content_type:
                try:
                    payload = json.loads(text)
                except Exception:
                    payload = None
                if payload is not None:
                    sanitized_payload, response_verdict = _sanitize_json_value(payload, request_mode=False)
                    redacted_text = json.dumps(sanitized_payload)
                else:
                    response_verdict = screen_output(text)
                    redacted_text = response_verdict.masked_text or text
            else:
                response_verdict = screen_output(text)
                redacted_text = response_verdict.masked_text or text

            headers = MutableHeaders(raw=response_start["headers"])
            headers["x-nexus-safety-action"] = _max_action(request_verdict.action, response_verdict.action).value
            encoded = redacted_text.encode("utf-8")
            headers["content-length"] = str(len(encoded))

            if not sent_start:
                sent_start = True
                await send(response_start)
            await send({"type": "http.response.body", "body": encoded, "more_body": False})

        await self.app(scope, receive_to_use, send_wrapper)