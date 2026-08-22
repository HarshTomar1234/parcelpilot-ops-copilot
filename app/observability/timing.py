"""Minimal latency measurement. AGENTS.md rule 13: measure latency, do not
claim it. No OpenTelemetry dependency yet - Phase 1 has no distributed
request path to trace, just local calls to time.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field


@dataclass
class Timings:
    samples_ms: list[float] = field(default_factory=list)

    @contextmanager
    def measure(self) -> Iterator[None]:
        start = time.perf_counter()
        try:
            yield
        finally:
            self.samples_ms.append((time.perf_counter() - start) * 1000)

    def percentile(self, p: float) -> float:
        if not self.samples_ms:
            return 0.0
        data = sorted(self.samples_ms)
        idx = min(int(round(p / 100 * (len(data) - 1))), len(data) - 1)
        return data[idx]

    @property
    def p50(self) -> float:
        return self.percentile(50)

    @property
    def p95(self) -> float:
        return self.percentile(95)

    @property
    def count(self) -> int:
        return len(self.samples_ms)
