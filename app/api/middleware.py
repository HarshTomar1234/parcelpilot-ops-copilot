"""One request_id/trace_id per HTTP request (Phase 6 s3, s21), attached to
request.state for every dependency/route to share, echoed back as response
headers, and logged as a single structured access-log line. No new
tracing framework - reuses app.observability.tracing.RequestContext and
app.observability.logging_config's existing JSON formatter.
"""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.observability.tracing import RequestContext

logger = logging.getLogger("api.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        context = RequestContext.new()
        request.state.request_context = context
        start = time.perf_counter()
        response = await call_next(request)
        latency_ms = (time.perf_counter() - start) * 1000

        response.headers["X-Request-Id"] = context.request_id
        response.headers["X-Trace-Id"] = context.trace_id
        logger.info(
            "http_request",
            extra={
                "request_id": context.request_id,
                "trace_id": context.trace_id,
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "latency_ms": round(latency_ms, 3),
                "demo_user": request.headers.get("X-Demo-User", "ops_admin"),
            },
        )
        return response
