"""Operations Radar evaluation against the real pack (Phase 5 s14/s16).

Runs the full deterministic detection engine, reports exactly what it
found (alert type, severity, observed_count/threshold, affected
accounts, evidence count) - never an invented number - and, for each
alert, generates an optional LLM summary (MockProvider by default),
logging model/prompt_version/alert_type/token_usage/latency/cost to
MLflow per alert. Deterministic detection itself is not logged as an ML
experiment (Phase 5 s16 - "normal test/evaluation reports are
sufficient" for that part); this script's MLflow runs cover only the
LLM-summary layer.

Usage:
    python scripts/run_operations_radar_eval.py --source-dir "<pack>/source-pack"
    python scripts/run_operations_radar_eval.py --source-dir "<pack>/source-pack" --mlflow
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.authorization.context import INTERNAL_SYSTEM_CONTEXT  # noqa: E402
from app.db.connection import connect  # noqa: E402
from app.detection.service import run_operations_radar  # noqa: E402
from app.detection.summary import compose_alert_summary  # noqa: E402
from app.llm.mock_provider import MockProvider  # noqa: E402
from app.observability.tracing import RequestContext  # noqa: E402
from app.time.clock import FixedSnapshotClock  # noqa: E402
from scripts.ingest_sources import ingest  # noqa: E402

REPORT_PATH = Path(__file__).resolve().parents[1] / "docs" / "operations_radar_evaluation.md"


def run_eval(source_dir: Path, db_path: Path, model: str) -> dict:
    summary_info = ingest(source_dir, db_path)
    conn = connect(db_path)
    clock = FixedSnapshotClock(datetime.fromisoformat(summary_info["snapshot"]))
    provider = MockProvider()

    alerts = run_operations_radar(conn, INTERNAL_SYSTEM_CONTEXT, clock)

    rows = []
    for alert in alerts:
        summary_text, response = compose_alert_summary(
            alert, provider, model, RequestContext.new()
        )
        rows.append(
            {
                "alert_id": alert.alert_id,
                "alert_type": alert.alert_type.value,
                "severity": alert.severity.value,
                "title": alert.title,
                "observed_count": alert.observed_count,
                "threshold": alert.threshold,
                "affected_accounts": alert.affected_accounts,
                "evidence_count": len(alert.evidence),
                "trust_state": alert.trust_state.value,
                "summary": summary_text,
                "summary_tokens": response.usage.total_tokens,
                "summary_latency_ms": round(response.latency_ms, 4),
                "summary_cost_usd": response.cost.total_cost_usd,
                "prompt_version": response.prompt_version,
            }
        )
    conn.close()

    by_type: dict[str, int] = {}
    for alert in alerts:
        by_type[alert.alert_type.value] = by_type.get(alert.alert_type.value, 0) + 1

    return {
        "model": model,
        "provider": provider.name,
        "total_alerts": len(alerts),
        "by_type": by_type,
        "rows": rows,
    }


def render_report(result: dict) -> str:
    lines = [
        "# Operations Radar Evaluation",
        "",
        f"Real-pack detection run. Provider: `{result['provider']}` / model "
        f"`{result['model']}`. Every alert below came from a deterministic rule in "
        "app/detection/rules.py - the LLM summary column is explanatory prose only, "
        "generated after detection and never able to change count/threshold/severity/"
        "affected_accounts/evidence.",
        "",
        f"**Total alerts: {result['total_alerts']}**",
        "",
        "| Alert type | Count |",
        "|---|---|",
    ]
    for alert_type, count in sorted(result["by_type"].items()):
        lines.append(f"| {alert_type} | {count} |")

    lines += [
        "",
        "## Per-alert results",
        "",
        "| Alert ID | Type | Severity | Observed/Threshold | Accounts | Evidence | Trust |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in result["rows"]:
        accounts = ", ".join(row["affected_accounts"])
        lines.append(
            f"| {row['alert_id']} | {row['alert_type']} | {row['severity']} | "
            f"{row['observed_count']}/{row['threshold']} | {accounts} | "
            f"{row['evidence_count']} | {row['trust_state']} |"
        )

    lines += [
        "",
        "## LLM summary cost/latency (per alert)",
        "",
        "| Alert ID | Tokens | Latency (ms) | Cost (USD) |",
        "|---|---|---|---|",
    ]
    for row in result["rows"]:
        lines.append(
            f"| {row['alert_id']} | {row['summary_tokens']} | {row['summary_latency_ms']} | "
            f"{row['summary_cost_usd']:.6f} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--db", default=Path("build/operations_radar_eval.db"), type=Path)
    parser.add_argument("--model", default="mock-model")
    parser.add_argument(
        "--mlflow", action="store_true", help="log each alert's summary as an MLflow run"
    )
    args = parser.parse_args()

    result = run_eval(args.source_dir, args.db, args.model)
    REPORT_PATH.write_text(render_report(result), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    print(f"\nwrote {REPORT_PATH}")

    if args.mlflow:
        from app.evaluation.mlflow_tracking import ExperimentRun, log_experiment_run

        for row in result["rows"]:
            run = ExperimentRun.build(
                experiment_name="parcelpilot-operations-radar-summary",
                provider=result["provider"],
                model=result["model"],
                prompt_version=row["prompt_version"],
                metrics={
                    "observed_count": float(row["observed_count"]),
                    "threshold": float(row["threshold"]),
                },
                latency_ms={"summary": row["summary_latency_ms"]},
                token_usage={"summary_total": row["summary_tokens"]},
                estimated_cost_usd=row["summary_cost_usd"],
                tags={
                    "phase": "5", "alert_type": row["alert_type"],
                    "alert_id": row["alert_id"], "severity": row["severity"],
                },
            )
            log_experiment_run(run)
        print(f"logged {len(result['rows'])} MLflow runs")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
