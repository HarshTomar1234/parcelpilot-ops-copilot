"""API latency and basic concurrency smoke test (Phase 6 s22-23). Hits a
*running* server (start one first, e.g. `uvicorn app.api.main:app` or the
Docker image) over real HTTP - this measures end-to-end API latency
including the ASGI/HTTP stack, not just the in-process function call time
scripts/run_performance_benchmark.py already measures for the domain
layer. A smoke test, not a load-testing platform: three concurrency
levels, a bounded request count, no ramping, no distributed load
generation.

Usage:
    python scripts/run_api_load_test.py --base-url http://localhost:8000
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402

ENDPOINTS = {
    "chat": ("POST", "/api/chat", {"question": "What severity is TKT-501?"}),
    "radar": ("POST", "/api/radar/run", {}),
}


def _one_request(base_url: str, method: str, path: str, body: dict) -> tuple[float, int]:
    start = time.perf_counter()
    try:
        resp = httpx.request(method, f"{base_url}{path}", json=body, timeout=30.0)
        status = resp.status_code
    except httpx.HTTPError:
        status = -1
    latency_ms = (time.perf_counter() - start) * 1000
    return latency_ms, status


def run_level(base_url: str, method: str, path: str, body: dict, concurrency: int) -> dict:
    start = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        results = list(
            pool.map(lambda _: _one_request(base_url, method, path, body), range(concurrency))
        )
    wall_seconds = time.perf_counter() - start

    latencies = sorted(lat for lat, _ in results)
    errors = sum(1 for _, status in results if status < 200 or status >= 400)
    return {
        "concurrency": concurrency,
        "requests": len(results),
        "errors": errors,
        "requests_per_sec": round(len(results) / wall_seconds, 2) if wall_seconds > 0 else 0.0,
        "p50_ms": round(statistics.median(latencies), 2),
        "p95_ms": round(latencies[int(len(latencies) * 0.95) - 1], 2),
        "max_ms": round(latencies[-1], 2),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--levels", default="1,5,10")
    args = parser.parse_args()

    levels = [int(x) for x in args.levels.split(",")]

    try:
        health = httpx.get(f"{args.base_url}/health", timeout=5.0)
        health.raise_for_status()
    except httpx.HTTPError as exc:
        raise SystemExit(f"server at {args.base_url} is not reachable: {exc}") from exc

    print(f"{'endpoint':<8} {'concurrency':>11} {'req/s':>8} {'p50 ms':>8} "
          f"{'p95 ms':>8} {'max ms':>8} {'errors':>7}")
    for name, (method, path, body) in ENDPOINTS.items():
        for concurrency in levels:
            row = run_level(args.base_url, method, path, body, concurrency)
            print(
                f"{name:<8} {row['concurrency']:>11} {row['requests_per_sec']:>8} "
                f"{row['p50_ms']:>8} {row['p95_ms']:>8} {row['max_ms']:>8} {row['errors']:>7}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
