"""FastAPI application factory (Phase 6 s2-3). Thin surface only: this
module wires routers, middleware, error handlers, and the static UI over
the existing agent/detection/action engines - it contains no business
logic of its own.

Run with: uvicorn app.api.main:app --reload
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api.error_handlers import register_error_handlers
from app.api.middleware import RequestContextMiddleware
from app.api.routes import actions, chat, health, radar
from app.observability.logging_config import configure_logging

_STATIC_DIR = Path(__file__).parent / "static"


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(
        title="ParcelPilot Ops Copilot",
        description="Support Copilot, Operations Radar, and the escalation action workflow.",
        version="0.6.0",
    )
    app.add_middleware(RequestContextMiddleware)
    register_error_handlers(app)

    app.include_router(health.router)
    app.include_router(chat.router)
    app.include_router(radar.router)
    app.include_router(actions.router)

    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="static")
    return app


app = create_app()
