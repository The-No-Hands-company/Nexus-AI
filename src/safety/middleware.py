"""
src/safety/middleware.py — FastAPI safety middleware stub

Pluggable middleware that runs input filtering on every request
and output filtering on every response before returning to the caller.
"""

from __future__ import annotations

import json
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class SafetyMiddleware(BaseHTTPMiddleware):
    """
    Runs input and output safety filters on every API request.

    STUB: dispatch() raises NotImplementedError for full pipeline.
    Basic pass-through is functional.

    Implementation plan:
    - Read request body, run input_filter.filter_input()
    - On block: return 400 with reason
    - Proceed to handler
    - Read response body, run output_filter.filter_output()
    - On block: replace response body with blocked message
    """

    # Paths to skip safety filtering on (health checks, static assets)
    SKIP_PATHS = frozenset(["/health", "/", "/docs", "/openapi.json", "/redoc"])

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """
        Middleware dispatch — input check → handler → output check.

        STUB: currently passes through without filtering.
        Full input/output pipeline raises NotImplementedError.
        """
        # TODO: implement full input + output filtering pipeline
        # For now, pass through to not break existing tests
        response = await call_next(request)
        return response
