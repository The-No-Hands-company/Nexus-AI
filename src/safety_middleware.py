from __future__ import annotations

import json

from .safety_pipeline import screen_input, screen_output


class SafetyPipelineMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        body_chunks = []

        async def wrapped_receive():
            message = await receive()
            if message.get("type") == "http.request":
                body_chunks.append(message.get("body", b""))
            return message

        request_body = b""
        sent_request = False

        async def buffering_receive():
            nonlocal request_body, sent_request
            if sent_request:
                return {"type": "http.request", "body": b"", "more_body": False}
            message = await wrapped_receive()
            request_body += message.get("body", b"")
            sent_request = not message.get("more_body", False)
            return message

        if path in {"/scheduler/jobs", "/v1/scheduler/jobs", "/agent/stream", "/v1/agent/stream"}:
            chunks = []
            more = True
            while more:
                msg = await wrapped_receive()
                chunks.append(msg.get("body", b""))
                more = msg.get("more_body", False)
            request_body = b"".join(chunks)
            sent_request = True
            try:
                payload = json.loads(request_body.decode("utf-8") or "{}")
            except Exception:
                payload = {}
            task = str(payload.get("task") or payload.get("cmd") or "")
            decision = screen_input(task)
            if not decision.allowed:
                data = json.dumps({"error": "blocked by safety policy", "type": decision.issues[0].code if decision.issues else "blocked", "safety": decision.to_dict()}).encode("utf-8")
                await send({"type": "http.response.start", "status": 422, "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": data, "more_body": False})
                return

            replayed = False

            async def replay_receive():
                nonlocal replayed
                if replayed:
                    return {"type": "http.request", "body": b"", "more_body": False}
                replayed = True
                return {"type": "http.request", "body": request_body, "more_body": False}

            receive_fn = replay_receive
        else:
            receive_fn = buffering_receive

        async def wrapped_send(message):
            if message.get("type") == "http.response.body" and message.get("body"):
                body = message.get("body", b"")
                decision = screen_output(body.decode("utf-8", errors="ignore"))
                if decision.masked_text is not None:
                    message = dict(message)
                    message["body"] = decision.masked_text.encode("utf-8")
            await send(message)

        await self.app(scope, receive_fn, wrapped_send)