from __future__ import annotations

import json
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from .input_filter import filter_input
from .output_filter import filter_output


class SafetyMiddleware(BaseHTTPMiddleware):

    SKIP_PATHS = frozenset(["/health", "/", "/docs", "/openapi.json", "/redoc"])

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        if path in self.SKIP_PATHS or path.startswith("/static/"):
            return await call_next(request)

        request_body = None
        if request.method in ("POST", "PUT", "PATCH"):
            body_bytes = await request.body()
            if body_bytes:
                request_body = body_bytes.decode("utf-8", errors="replace")
                filter_result = filter_input(request_body, redact_pii=True)
                if not filter_result.passed:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": "input_filter_rejected",
                            "reason": filter_result.rejection_reason,
                            "warnings": filter_result.warnings,
                        },
                    )

                async def receive_body():
                    return {"type": "http.request", "body": filter_result.prompt_clean.encode("utf-8")}

                request._body = filter_result.prompt_clean.encode("utf-8")

        response = await call_next(request)

        if response.status_code == 200 and response.headers.get("content-type", "").startswith("application/json"):
            try:
                body_bytes = b""
                async for chunk in response.body_iterator:
                    body_bytes += chunk

                response_body = body_bytes.decode("utf-8", errors="replace")
                output_result = filter_output(response_body, redact_pii=True)

                if not output_result.passed:
                    return JSONResponse(
                        status_code=400,
                        content={
                            "error": "output_filter_rejected",
                            "reason": output_result.reason,
                        },
                    )

                if output_result.response_clean != response_body:
                    return JSONResponse(
                        status_code=response.status_code,
                        content=json.loads(output_result.response_clean),
                    )
            except (json.JSONDecodeError, UnicodeDecodeError):
                pass

        return response
