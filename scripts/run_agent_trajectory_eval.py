"""Agent trajectory evaluation over the golden case set (Phase 3 s23).

For every golden case with a real question and a non-empty expected_tools
list, runs the actual agent (app/agent/orchestrator.py::run_agent) against
the real database and scores two things:

  - Tool correctness (DeepEval's ToolCorrectnessMetric): exact-match
    comparison of tools actually called vs. expected_tools. This needs no
    LLM judge, so it is a genuine, non-fabricated score even with
    MockProvider.
  - Terminal-status match: whether the agent's AgentStatus matches the
    case's expected_status (mapped via expected_agent_status - see
    app/evaluation/adapters/agent_trajectory_adapter.py for why
    action_pending/action_completed/rejected cases are excluded: Phase 3
    does not execute actions).

Also attempts DeepEval's TaskCompletionMetric (an LLM-judged metric) and
records the exact harness-blocked failure when using MockProvider as the
judge, following the same honest pattern as scripts/run_deepeval_baseline.py
- it is not skipped or faked, the limitation is measured and reported.

Usage:
    python scripts/run_agent_trajectory_eval.py --source-dir "<pack>/source-pack"
    python scripts/run_agent_trajectory_eval.py --source-dir "<pack>/source-pack" \
        --provider anthropic --model claude-sonnet-5
"""

from __future__ import annotations

import os

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.connection import connect  # noqa: E402
from app.evaluation.adapters.agent_trajectory_adapter import (  # noqa: E402
    build_test_case,
    expected_agent_status,
    run_case,
)
from app.evaluation.cases import EvaluationCase, load_golden_cases  # noqa: E402
from app.llm.base import LLMProvider  # noqa: E402
from app.llm.deepeval_bridge import GatewayDeepEvalModel  # noqa: E402
from app.llm.mock_provider import MockProvider  # noqa: E402
from scripts.ingest_sources import ingest  # noqa: E402

REPORT_PATH = (
    Path(__file__).resolve().parents[1] / "docs" / "agent_trajectory_evaluation.md"
)


def _eligible_cases(cases: list[EvaluationCase]) -> list[EvaluationCase]:
    return [c for c in cases if c.is_real_query() and c.expected_tools]


def _build_provider(name: str, model: str) -> LLMProvider:
    if name == "mock":
        return MockProvider()
    if name == "anthropic":
        from app.llm.anthropic_provider import AnthropicProvider

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise SystemExit("--provider anthropic requires ANTHROPIC_API_KEY to be set")
        return AnthropicProvider(api_key=api_key)
    raise SystemExit(f"unknown provider {name!r}")


def run_trajectory_eval(source_dir: Path, db_path: Path, provider_name: str, model: str) -> dict:
    from deepeval.metrics import TaskCompletionMetric, ToolCorrectnessMetric

    ingest(source_dir, db_path)
    conn = connect(db_path)
    row = conn.execute("SELECT value FROM meta WHERE key = 'snapshot_time'").fetchone()
    from datetime import datetime

    snapshot = datetime.fromisoformat(row["value"])

    provider = _build_provider(provider_name, model)
    judge = GatewayDeepEvalModel(provider, model)
    tool_metric = ToolCorrectnessMetric(model=judge, async_mode=False)
    task_metric = TaskCompletionMetric(model=judge, async_mode=False, include_reason=False)

    cases = _eligible_cases(load_golden_cases())
    rows = []
    task_completion_error: str | None = None
    for case in cases:
        result = run_case(conn, case, provider, model, snapshot)
        test_case = build_test_case(case, result)

        tool_metric.measure(test_case)

        expected_status = expected_agent_status(case)
        status_match = (
            None if expected_status is None else result.status == expected_status
        )

        row = {
            "id": case.case_id,
            "question": case.question,
            "expected_tools": case.expected_tools,
            "actual_tools": result.planned_tools,
            "tool_correctness": tool_metric.score,
            "expected_status": expected_status,
            "actual_status": result.status,
            "status_match": status_match,
        }
        try:
            task_metric.measure(test_case)
            row["task_completion"] = task_metric.score
        except ValueError as exc:
            task_completion_error = str(exc)
            row["task_completion"] = None
        rows.append(row)
    conn.close()

    tool_scores = [r["tool_correctness"] for r in rows]
    status_checks = [r["status_match"] for r in rows if r["status_match"] is not None]
    task_scores = [r["task_completion"] for r in rows if r["task_completion"] is not None]

    return {
        "provider": provider_name,
        "model": model,
        "judge_model": judge.get_model_name(),
        "cases_evaluated": len(rows),
        "mean_tool_correctness": sum(tool_scores) / len(tool_scores) if tool_scores else None,
        "status_match_rate": (
            sum(status_checks) / len(status_checks) if status_checks else None
        ),
        "status_checkable_cases": len(status_checks),
        "task_completion_scored": len(task_scores),
        "task_completion_error": task_completion_error,
        "rows": rows,
    }


def render_report(result: dict) -> str:
    is_mock = result["provider"] == "mock"
    lines = [
        "# Agent Trajectory Evaluation",
        "",
    ]
    if is_mock:
        lines.append(
            "**This run used MockProvider.** Tool correctness and status-match below are "
            "genuine, non-fabricated scores - they compare the real agent's actual tool "
            "calls and terminal status against the golden dataset, and need no LLM judge. "
            "Task completion (an LLM-judged metric) could not be scored with MockProvider "
            "as the judge - see the harness-blocked note below; this mirrors "
            "docs/deepeval_baseline.md's documented limitation, not a new one."
        )
    else:
        lines.append(
            f"This run used `{result['judge_model']}` as both agent LLM and judge - task "
            "completion below is a real LLM-judged score."
        )
    lines += [
        "",
        "## Method",
        "",
        f"{result['cases_evaluated']} golden cases with a real question and a non-empty "
        "expected_tools list. For each: run the actual agent "
        "(app/agent/orchestrator.py::run_agent) against the real database with the case's "
        "own role/account_scope, then score tool correctness (DeepEval's "
        "ToolCorrectnessMetric, exact match, no judge needed) and terminal-status match "
        "against the case's expected_status.",
        "",
        "## Results",
        "",
        f"- Provider: `{result['provider']}` / model `{result['model']}`",
        f"- Judge: `{result['judge_model']}`",
        f"- Cases evaluated: **{result['cases_evaluated']}**",
    ]
    if result["mean_tool_correctness"] is not None:
        lines.append(f"- Mean tool correctness: **{result['mean_tool_correctness']:.2f}**")
    if result["status_match_rate"] is not None:
        lines.append(
            f"- Status match rate: **{result['status_match_rate']:.2f}** "
            f"({result['status_checkable_cases']} status-checkable cases; the rest expect "
            "an action_pending/action_completed/rejected status, out of scope for Phase 3)"
        )
    lines.append(
        f"- Task completion: scored for {result['task_completion_scored']} of "
        f"{result['cases_evaluated']} cases"
        + (
            f" (harness-blocked for the rest: `{result['task_completion_error']}`)"
            if result["task_completion_error"]
            else ""
        )
    )

    lines += [
        "",
        "## Per-case results",
        "",
        "| Case | Tools expected | Tools called | Tool correctness | Status expected | "
        "Status actual | Match |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in result["rows"]:
        match = "-" if row["status_match"] is None else ("yes" if row["status_match"] else "NO")
        lines.append(
            f"| {row['id']} | {', '.join(row['expected_tools'])} | "
            f"{', '.join(row['actual_tools'])} | {row['tool_correctness']:.2f} | "
            f"{row['expected_status']} | {row['actual_status']} | {match} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--db", default=Path("build/agent_trajectory_eval.db"), type=Path)
    parser.add_argument("--provider", default="mock", choices=["mock", "anthropic"])
    parser.add_argument("--model", default="mock-model")
    parser.add_argument(
        "--mlflow", action="store_true", help="log this run as an MLflow experiment"
    )
    args = parser.parse_args()

    result = run_trajectory_eval(args.source_dir, args.db, args.provider, args.model)
    REPORT_PATH.write_text(render_report(result), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    print(f"\nwrote {REPORT_PATH}")

    if args.mlflow:
        from app.evaluation.mlflow_tracking import ExperimentRun, log_experiment_run

        metrics = {"cases_evaluated": float(result["cases_evaluated"])}
        if result["mean_tool_correctness"] is not None:
            metrics["mean_tool_correctness"] = result["mean_tool_correctness"]
        if result["status_match_rate"] is not None:
            metrics["status_match_rate"] = result["status_match_rate"]
        metrics["task_completion_scored"] = float(result["task_completion_scored"])
        run = ExperimentRun.build(
            experiment_name="parcelpilot-agent-trajectory",
            provider=result["provider"],
            model=result["model"],
            metrics=metrics,
            tags={"phase": "3", "eval_type": "agent_trajectory", "judge": result["judge_model"]},
        )
        run_id = log_experiment_run(run)
        print(f"logged MLflow run: {run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
