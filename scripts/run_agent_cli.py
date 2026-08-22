"""Minimal dev harness for exercising the Phase 3 agent end to end (spec
s39). Not a frontend - a CLI to ask one question against an already-
ingested database and see the full, honest result: status, trust state,
answer, citations, conflicts, assumptions, and the tool/state trace.

Uses MockProvider by default. Pass --live to use a real Anthropic call
(requires ANTHROPIC_API_KEY and the `llm` extra); this is opt-in, never
automatic, per the "do not fabricate live results" rule - see
docs/_internal/phase-reports/phase-03.md for why no live smoke test has
been run in this environment.

Usage:
    python scripts/run_agent_cli.py --question "Is TKT-501 within SLA?"
    python scripts/run_agent_cli.py --question "..." --account-scope ACCT-001
    python scripts/run_agent_cli.py --question "..." --live --model claude-...
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agent.context import AgentRequestContext  # noqa: E402
from app.agent.orchestrator import run_agent  # noqa: E402
from app.authorization.context import AuthContext, Role  # noqa: E402
from app.db.connection import connect  # noqa: E402
from app.llm.factory import build_default_provider  # noqa: E402
from app.llm.gateway import ParcelPilotLLMGateway  # noqa: E402
from app.observability.tracing import RequestContext  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--question", required=True)
    parser.add_argument("--db", default=Path("build/parcelpilot.db"), type=Path)
    parser.add_argument(
        "--role", default="operations_admin",
        choices=[r.value for r in Role],
    )
    parser.add_argument(
        "--account-scope", default=None,
        help="comma-separated account IDs; omit for unrestricted access",
    )
    parser.add_argument("--live", action="store_true", help="use a real Anthropic call")
    parser.add_argument("--model", default="claude-sonnet-4-5")
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"{args.db} not found - run scripts/ingest_sources.py first")

    conn = connect(args.db)
    row = conn.execute("SELECT value FROM meta WHERE key = 'snapshot_time'").fetchone()
    snapshot = datetime.fromisoformat(row["value"])

    scope = args.account_scope.split(",") if args.account_scope else None
    auth = AuthContext(role=Role(args.role), account_scope=scope)

    try:
        provider, model = build_default_provider(args.live, args.model)
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from exc
    rc = RequestContext.new()
    ctx = AgentRequestContext(
        request_id=rc.request_id, trace_id=rc.trace_id, user_id="cli-user",
        auth=auth, dataset_snapshot_time=snapshot,
    )

    result = run_agent(args.question, ctx, conn, provider, model=model)

    print(f"status:       {result.status}")
    print(f"intent:       {result.intent}")
    print(f"trust_state:  {result.trust_state}")
    print(f"tools called: {result.planned_tools}")
    print(f"tool_calls:   {result.tool_calls}   llm_calls: {result.llm_calls}")
    print(f"latency_ms:   {result.total_latency_ms:.1f}   cost_usd: {result.total_cost_usd:.6f}")
    if result.reason:
        print(f"reason:       {result.reason}")
    if result.answer:
        print("\nanswer:")
        print(result.answer)
    if result.citations:
        print("\ncitations:")
        for ref in result.citations:
            locator = f":{ref.locator}" if ref.locator else ""
            print(f"  - [{ref.source_id}{locator}] {ref.note or ''}")
    if result.assumptions:
        print("\nassumptions:")
        for assumption in result.assumptions:
            print(f"  - {assumption}")
    if result.conflicts:
        print("\nconflicts:")
        for conflict in result.conflicts:
            print(
                f"  - {conflict.winner_source_id} overrides {conflict.loser_source_id}: "
                f"{conflict.reason}"
            )
    print("\nstate_trace:  " + " -> ".join(result.state_trace))

    if isinstance(provider, ParcelPilotLLMGateway) and provider.last_run:
        run = provider.last_run
        print(f"\ngateway: fallback_used={run.fallback_used} reason={run.fallback_reason}")
        for attempt in run.provider_attempts:
            print(
                f"  - {attempt.provider}/{attempt.model}: "
                f"success={attempt.success} error={attempt.error}"
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
