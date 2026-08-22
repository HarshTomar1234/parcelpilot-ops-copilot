"""Measures structured-data and domain-calculation latency (Phase 2 s21).
Retrieval latency is already measured by run_retrieval_eval.py; this script
covers the two Phase 2 additions that script doesn't touch.

Do not read p50/p95 here as "this system is fast" - the corpus is 4
accounts, 6 orders, 7 tickets. It measures that these operations are not
accidentally quadratic or I/O-bound, nothing more. The real latency budget
arrives with the LLM/agent phase (Phase 2 s21's own framing).

Usage:
    python scripts/run_performance_benchmark.py --source-dir "<pack>/source-pack"
"""

from __future__ import annotations

import argparse
import datetime
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.authorization.context import INTERNAL_SYSTEM_CONTEXT  # noqa: E402
from app.db.connection import connect  # noqa: E402
from app.domain.cancellation import evaluate_cancellation  # noqa: E402
from app.domain.service_credit import evaluate_service_credit  # noqa: E402
from app.domain.severity import classify_severity  # noqa: E402
from app.domain.sla import calculate_sla  # noqa: E402
from app.observability.timing import Timings  # noqa: E402
from app.structured_data.repository import (  # noqa: E402
    get_account,
    get_order,
    get_ticket,
    search_orders,
    search_tickets,
)
from app.time.clock import FixedSnapshotClock, tz_of  # noqa: E402
from scripts.ingest_sources import ingest  # noqa: E402

REPORT_PATH = Path(__file__).resolve().parents[1] / "docs" / "performance_report.md"
REPETITIONS = 30


def _bench(timings: Timings, fn) -> None:
    for _ in range(REPETITIONS):
        with timings.measure():
            fn()


def run_benchmark(source_dir: Path, db_path: Path) -> dict:
    summary = ingest(source_dir, db_path)
    conn = connect(db_path)
    clock = FixedSnapshotClock(datetime.datetime.fromisoformat(summary["snapshot"]))
    tz = tz_of(clock)
    auth = INTERNAL_SYSTEM_CONTEXT

    order_ids = [r["order_id"] for r in conn.execute("SELECT order_id FROM orders")]
    ticket_ids = [r["ticket_id"] for r in conn.execute("SELECT ticket_id FROM tickets")]
    account_ids = [r["account_id"] for r in conn.execute("SELECT account_id FROM accounts")]

    results: dict[str, Timings] = {
        "get_account": Timings(),
        "get_order": Timings(),
        "get_ticket": Timings(),
        "search_orders": Timings(),
        "search_tickets": Timings(),
        "evaluate_cancellation": Timings(),
        "evaluate_service_credit": Timings(),
        "calculate_sla": Timings(),
        "classify_severity": Timings(),
    }

    _bench(results["get_account"], lambda: get_account(conn, account_ids[0], auth))
    _bench(results["get_order"], lambda: get_order(conn, order_ids[0], auth, tz))
    _bench(results["get_ticket"], lambda: get_ticket(conn, ticket_ids[0], auth, tz))
    _bench(results["search_orders"], lambda: search_orders(conn, auth, tz))
    _bench(results["search_tickets"], lambda: search_tickets(conn, auth, tz))

    for order_id in order_ids:
        _bench(
            results["evaluate_cancellation"],
            lambda oid=order_id: evaluate_cancellation(conn, oid, auth, clock),
        )
        _bench(
            results["evaluate_service_credit"],
            lambda oid=order_id: evaluate_service_credit(conn, oid, auth, clock),
        )
    for ticket_id in ticket_ids:
        _bench(
            results["calculate_sla"], lambda tid=ticket_id: calculate_sla(conn, tid, auth, clock)
        )
        ticket = get_ticket(conn, ticket_id, auth, tz)
        _bench(results["classify_severity"], lambda t=ticket: classify_severity(t, conn))

    conn.close()
    return {
        "repetitions_per_operation": REPETITIONS,
        "operations": {
            name: {"p50_ms": round(t.p50, 4), "p95_ms": round(t.p95, 4), "count": t.count}
            for name, t in results.items()
        },
    }


def render_report(result: dict) -> str:
    lines = [
        "# Performance Report",
        "",
        "Structured-data and domain-calculation latency, measured locally against the "
        f"full workbook ({result['repetitions_per_operation']} repetitions per operation). "
        "Retrieval latency is in docs/retrieval_evaluation.md. This is not a claim of "
        "production latency under load - it establishes that nothing here is accidentally "
        "quadratic or I/O-bound at this corpus size.",
        "",
        "| Operation | p50 (ms) | p95 (ms) | n |",
        "|---|---|---|---|",
    ]
    for name, stats in result["operations"].items():
        lines.append(f"| {name} | {stats['p50_ms']} | {stats['p95_ms']} | {stats['count']} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--db", default=Path("build/perf.db"), type=Path)
    args = parser.parse_args()

    result = run_benchmark(args.source_dir, args.db)
    REPORT_PATH.write_text(render_report(result), encoding="utf-8")
    print(json.dumps(result, indent=2))
    print(f"\nwrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
