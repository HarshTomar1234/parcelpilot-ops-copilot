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

from app.actions.workflow import confirm_action, execute_action, prepare_escalation  # noqa: E402
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

    action_results = _bench_action_workflow(conn, ticket_ids, auth, clock)

    conn.close()
    return {
        "repetitions_per_operation": REPETITIONS,
        "operations": {
            name: {"p50_ms": round(t.p50, 4), "p95_ms": round(t.p95, 4), "count": t.count}
            for name, t in results.items()
        },
        "action_workflow": {
            name: {"p50_ms": round(t.p50, 4), "p95_ms": round(t.p95, 4), "count": t.count}
            for name, t in action_results.items()
        },
    }


def _bench_action_workflow(conn, ticket_ids: list[str], auth, clock) -> dict[str, Timings]:
    """Phase 4 s13: prepare/confirm/execute latency, measured separately
    from the table above and captioned as mock-executor latency only - no
    real external action system exists to call, so this can never be read
    as a production external-action latency claim."""
    eligible_ticket_id = None
    for tid in ticket_ids:
        outcome = calculate_sla(conn, tid, auth, clock)
        if outcome.result and (outcome.result.severity.value == "P1" or outcome.result.breached):
            eligible_ticket_id = tid
            break
    results = {
        "prepare_escalation": Timings(), "confirm_action": Timings(), "execute_action": Timings(),
    }
    if eligible_ticket_id is None:
        return results  # no P1/breached ticket in this pack - nothing eligible to benchmark

    for i in range(REPETITIONS):
        with results["prepare_escalation"].measure():
            outcome = prepare_escalation(
                conn, eligible_ticket_id, "perf benchmark", auth, clock,
                f"bench-user-{i}", f"bench-req-{i}",
            )
        assert outcome.record is not None
        action_id, payload_hash = outcome.record.action_id, outcome.record.payload_hash

        with results["confirm_action"].measure():
            confirmed = confirm_action(
                conn, action_id, payload_hash, auth, clock, f"bench-user-{i}"
            )
        assert confirmed.record is not None

        with results["execute_action"].measure():
            execute_action(conn, action_id, clock)

    return results


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

    lines += [
        "",
        "## Action workflow (Phase 4)",
        "",
        "**Mock-executor latency only.** No real external action system exists to call - "
        "execute_action only updates the local actions audit row. This is not a production "
        "external-action latency claim. Unlike the read-only table above, every action "
        "workflow call durably commits its audit row to disk (sqlite3.Connection.commit()) "
        "before returning, which is why these numbers run roughly 1000x higher - that is a "
        "deliberate durability choice for the audit trail, not something to optimize away.",
        "",
        "| Operation | p50 (ms) | p95 (ms) | n |",
        "|---|---|---|---|",
    ]
    for name, stats in result["action_workflow"].items():
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
