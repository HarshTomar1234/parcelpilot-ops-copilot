"""OpenTelemetry-compatible tracing for the future request path.

No SDK or exporter is configured here - with only opentelemetry-api
installed, spans are no-ops by default (this is a deliberate, standard
OTel behavior, not a stub we wrote). That gives every code path a real
tracing interface (span() below) that a later phase can make observable
by configuring a TracerProvider + exporter in one place, without touching
any call site. This is the "make every future request traceable"
foundation the phase asks for, not a monitoring platform.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass

from opentelemetry import trace
from opentelemetry.trace import Span

_tracer = trace.get_tracer("parcelpilot.ops_copilot")


@dataclass(frozen=True)
class RequestContext:
    """Threaded through every tool call and future LLM call so a single
    user request is traceable end to end across domain evaluation,
    retrieval, and (later) model calls."""

    request_id: str
    trace_id: str

    @classmethod
    def new(cls) -> RequestContext:
        return cls(request_id=str(uuid.uuid4()), trace_id=str(uuid.uuid4()))

    def child(self) -> RequestContext:
        """A new request_id under the same trace_id - for a sub-step of
        the same end-to-end request (e.g. one tool call within an agent turn)."""
        return RequestContext(request_id=str(uuid.uuid4()), trace_id=self.trace_id)


@contextmanager
def span(name: str, context: RequestContext, **attributes: object) -> Iterator[Span]:
    with _tracer.start_as_current_span(name) as otel_span:
        otel_span.set_attribute("request_id", context.request_id)
        otel_span.set_attribute("trace_id", context.trace_id)
        for key, value in attributes.items():
            otel_span.set_attribute(key, str(value))
        start = time.perf_counter()
        try:
            yield otel_span
        finally:
            otel_span.set_attribute("duration_ms", (time.perf_counter() - start) * 1000)
