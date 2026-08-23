"""Safe error UX (Phase 6 s13). No route in app/api/routes/ lets a raw
exception or stack trace reach a client - expected business outcomes
already come back as typed, success=False results (ActionOutcome,
AgentRunResult.status) from the engines themselves; this module only
catches what's left: an authorization/lookup error raised instead of
returned, and any genuinely unexpected exception (a real bug), which
becomes a generic 500 with no internal detail.
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.errors import NotAuthorizedError, ParcelPilotError, UnknownEntityError

logger = logging.getLogger("api.errors")


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(NotAuthorizedError)
    async def _not_authorized(request: Request, exc: NotAuthorizedError) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(exc)})

    @app.exception_handler(UnknownEntityError)
    async def _unknown_entity(request: Request, exc: UnknownEntityError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(exc)})

    @app.exception_handler(ParcelPilotError)
    async def _domain_error(request: Request, exc: ParcelPilotError) -> JSONResponse:
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "unhandled_api_exception", extra={"path": request.url.path, "method": request.method}
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "an internal error occurred; it has been logged"},
        )
