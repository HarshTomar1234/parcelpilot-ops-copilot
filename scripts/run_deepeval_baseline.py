"""DeepEval baseline over the golden evaluation set.

Measures ContextualRelevancyMetric (how relevant is what was retrieved to
the question) and FaithfulnessMetric (does the generated answer stay
grounded in that retrieval) for every golden case with a real question and
at least one expected document source - the same 16-case eligibility used
by scripts/run_retrieval_eval.py.

Uses MockProvider (deterministic, free, no network) as both the answering
model and the judge by default - this proves the harness runs end to end,
not that answers are good. Pass --provider anthropic --model <name> with
ANTHROPIC_API_KEY set to get a real quality signal instead; the report
states plainly which one produced the numbers in it.

Usage:
    python scripts/run_deepeval_baseline.py --source-dir "<pack>/source-pack"
    python scripts/run_deepeval_baseline.py --source-dir "<pack>/source-pack" \
        --provider anthropic --model claude-sonnet-5
"""

from __future__ import annotations

import os

os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")

import argparse  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.authorization.context import INTERNAL_SYSTEM_CONTEXT  # noqa: E402
from app.db.connection import connect  # noqa: E402
from app.evaluation.adapters.deepeval_adapter import build_test_case  # noqa: E402
from app.evaluation.cases import EvaluationCase, load_golden_cases  # noqa: E402
from app.llm.base import LLMProvider  # noqa: E402
from app.llm.deepeval_bridge import GatewayDeepEvalModel  # noqa: E402
from app.llm.mock_provider import MockProvider  # noqa: E402
from scripts.ingest_sources import ingest  # noqa: E402

REPORT_PATH = Path(__file__).resolve().parents[1] / "docs" / "deepeval_baseline.md"
_DOC_SOURCE = re.compile(r"^(SRC-0[1-6]):")


def _eligible_cases(cases: list[EvaluationCase]) -> list[EvaluationCase]:
    return [c for c in cases if c.is_real_query() and c.expected_document_sources()]


def _build_provider(name: str, model: str) -> LLMProvider:
    if name == "mock":
        return MockProvider()
    if name == "anthropic":
        import os

        from app.llm.anthropic_provider import AnthropicProvider

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            raise SystemExit("--provider anthropic requires ANTHROPIC_API_KEY to be set")
        return AnthropicProvider(api_key=api_key)
    raise SystemExit(f"unknown provider {name!r}")


def run_baseline(source_dir: Path, db_path: Path, provider_name: str, model: str) -> dict:
    from deepeval.metrics import ContextualRelevancyMetric, FaithfulnessMetric

    ingest(source_dir, db_path)
    conn = connect(db_path)

    provider = _build_provider(provider_name, model)
    judge = GatewayDeepEvalModel(provider, model)
    relevancy = ContextualRelevancyMetric(model=judge, async_mode=False, include_reason=True)
    faithfulness = FaithfulnessMetric(model=judge, async_mode=False, include_reason=True)

    cases = _eligible_cases(load_golden_cases())
    rows = []
    harness_error: str | None = None
    for case in cases:
        test_case = build_test_case(conn, case, INTERNAL_SYSTEM_CONTEXT, provider, model)
        try:
            relevancy.measure(test_case)
            faithfulness.measure(test_case)
        except ValueError as exc:
            # The judge did not return the structured JSON DeepEval's metrics
            # require to extract a verdict. MockProvider cannot produce this -
            # it is not a bug to route around, it is the honest signal that a
            # real quality score needs a real LLM_API_KEY. Recorded, not hidden.
            harness_error = str(exc)
            rows.append({"id": case.case_id, "question": case.question, "error": harness_error})
            continue
        rows.append(
            {
                "id": case.case_id,
                "question": case.question,
                "contextual_relevancy": relevancy.score,
                "contextual_relevancy_reason": relevancy.reason,
                "faithfulness": faithfulness.score,
                "faithfulness_reason": faithfulness.reason,
            }
        )
    conn.close()

    def _mean(key: str) -> float | None:
        values = [r[key] for r in rows if key in r and r[key] is not None]
        return sum(values) / len(values) if values else None

    return {
        "provider": provider_name,
        "model": model,
        "judge_model": judge.get_model_name(),
        "cases_evaluated": len(rows),
        "cases_scored": sum(1 for r in rows if "error" not in r),
        "harness_error": harness_error,
        "mean_contextual_relevancy": _mean("contextual_relevancy"),
        "mean_faithfulness": _mean("faithfulness"),
        "rows": rows,
    }


def render_report(result: dict) -> str:
    is_mock = result["provider"] == "mock"
    scored = result["cases_scored"]
    total = result["cases_evaluated"]

    if is_mock and scored == 0:
        caveat = (
            "**No quality scores were produced.** DeepEval's LLM-judged metrics require "
            "the judge to return structured JSON verdicts; MockProvider returns a fixed "
            "placeholder string, which is not that. This is not a bug being routed around - "
            "it is the honest signal that a real score needs a real judge model. What this "
            "run *did* verify: retrieval via the real `search_documents` tool, "
            "`LLMTestCase` construction, and the `GatewayDeepEvalModel` bridge all execute "
            "correctly up to the point DeepEval calls the judge - the wiring works, the "
            "score does not exist yet. Re-run with `--provider anthropic --model <name>` "
            "and a real `ANTHROPIC_API_KEY` for genuine scores."
            f"\n\nDeepEval's error, for the first case it failed on: `{result['harness_error']}`"
        )
    elif is_mock:
        caveat = (
            "**This run used the mock provider as both answerer and judge.** Scores below "
            "prove the DeepEval harness runs end to end, not that any answer is actually "
            "good - MockProvider's canned response is not a real support answer. Re-run "
            "with `--provider anthropic --model <name>` and a real ANTHROPIC_API_KEY for a "
            "genuine quality signal."
        )
    else:
        caveat = (
            f"This run used `{result['judge_model']}` as both answerer and judge - these "
            "are real LLM-judged quality scores."
        )

    lines = [
        "# DeepEval Baseline",
        "",
        caveat,
        "",
        "## Method",
        "",
        f"{total} golden cases with a real question and at least one expected document "
        "source (the same eligibility as docs/retrieval_evaluation.md). For each: retrieve "
        "via the real search_documents tool, generate an answer from the retrieved evidence "
        "via the configured LLMProvider, then score with DeepEval's ContextualRelevancyMetric "
        "(is the retrieved context relevant to the question) and FaithfulnessMetric (does the "
        "answer stay grounded in that context).",
        "",
        "## Results",
        "",
        f"- Provider: `{result['provider']}` / model `{result['model']}`",
        f"- Judge: `{result['judge_model']}`",
        f"- Cases evaluated: **{total}** (scored: {scored}, harness-blocked: {total - scored})",
    ]
    if result["mean_contextual_relevancy"] is not None:
        lines.append(f"- Mean contextual relevancy: **{result['mean_contextual_relevancy']:.2f}**")
    if result["mean_faithfulness"] is not None:
        lines.append(f"- Mean faithfulness: **{result['mean_faithfulness']:.2f}**")

    lines += [
        "",
        "## Per-case results",
        "",
        "| Case | Contextual relevancy | Faithfulness |",
        "|---|---|---|",
    ]
    for row in result["rows"]:
        if "error" in row:
            lines.append(f"| {row['id']} | harness-blocked | harness-blocked |")
        else:
            lines.append(
                f"| {row['id']} | {row['contextual_relevancy']:.2f} | {row['faithfulness']:.2f} |"
            )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--db", default=Path("build/deepeval.db"), type=Path)
    parser.add_argument("--provider", default="mock", choices=["mock", "anthropic"])
    parser.add_argument("--model", default="mock-model")
    args = parser.parse_args()

    result = run_baseline(args.source_dir, args.db, args.provider, args.model)
    REPORT_PATH.write_text(render_report(result), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
    print(f"\nwrote {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
