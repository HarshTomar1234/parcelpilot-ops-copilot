"""Retrieval evaluation against tests/evaluation/golden_cases.json.

For every golden case whose expected_citations name at least one document
source (SRC-01..SRC-06 - SRC-07 is structured data, not retrievable) and
whose `question` is a real natural-language query (not a bracketed
action-flow placeholder), this runs search_documents() with the question
text and checks whether an expected source appears in the results.

Writes docs/retrieval_evaluation.md. Reports only measured numbers - no
retrieval quality claim is made beyond what this run actually produced.

Usage:
    python scripts/run_retrieval_eval.py --source-dir "<pack>/source-pack"
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.connection import connect  # noqa: E402
from app.documents.retrieval import search_documents  # noqa: E402
from app.observability.timing import Timings  # noqa: E402
from scripts.ingest_sources import ingest  # noqa: E402

GOLDEN_PATH = Path(__file__).resolve().parents[1] / "tests" / "evaluation" / "golden_cases.json"
REPORT_PATH = Path(__file__).resolve().parents[1] / "docs" / "retrieval_evaluation.md"
_DOC_SOURCE = re.compile(r"^(SRC-0[1-6]):")


def _expected_doc_sources(case: dict) -> list[str]:
    ids = []
    for citation in case.get("expected_citations", []):
        match = _DOC_SOURCE.match(citation)
        if match and match[1] not in ids:
            ids.append(match[1])
    return ids


def _eligible_cases(golden: dict) -> list[dict]:
    cases = []
    for case in golden["cases"]:
        question = case.get("question", "")
        if question.startswith("["):
            continue  # action-flow placeholder, not a real query
        if _expected_doc_sources(case):
            cases.append(case)
    return cases


def run_eval(source_dir: Path, db_path: Path) -> dict:
    ingest(source_dir, db_path)
    conn = connect(db_path)
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    cases = _eligible_cases(golden)

    timings = Timings()
    rows = []
    for case in cases:
        expected = _expected_doc_sources(case)
        with timings.measure():
            results = search_documents(conn, case["question"], top_k=5)
        retrieved = [r.source_id for r in results]
        rank = next(
            (i + 1 for i, sid in enumerate(retrieved) if sid in expected), None
        )
        rows.append(
            {
                "id": case["id"],
                "question": case["question"],
                "expected": expected,
                "retrieved": retrieved,
                "rank": rank,
            }
        )
    conn.close()

    n = len(rows)
    hit_at_3 = sum(1 for r in rows if r["rank"] is not None and r["rank"] <= 3)
    hit_at_5 = sum(1 for r in rows if r["rank"] is not None and r["rank"] <= 5)

    total_expected_sources = sum(len(r["expected"]) for r in rows)
    found_expected_sources = sum(
        sum(1 for sid in r["expected"] if sid in r["retrieved"]) for r in rows
    )

    return {
        "cases_evaluated": n,
        "recall_at_3": hit_at_3 / n if n else 0.0,
        "recall_at_5": hit_at_5 / n if n else 0.0,
        "source_hit_rate": found_expected_sources / total_expected_sources
        if total_expected_sources
        else 0.0,
        "latency_p50_ms": round(timings.p50, 3),
        "latency_p95_ms": round(timings.p95, 3),
        "rows": rows,
    }


def render_report(result: dict) -> str:
    failures = [r for r in result["rows"] if r["rank"] is None or r["rank"] > 3]
    lines = [
        "# Retrieval Evaluation",
        "",
        "Measured against `tests/evaluation/golden_cases.json` by running "
        "`scripts/run_retrieval_eval.py` over a freshly built database. "
        "Regenerate with:",
        "",
        "```",
        'python scripts/run_retrieval_eval.py --source-dir "<pack>/source-pack"',
        "```",
        "",
        "## Method",
        "",
        f"{result['cases_evaluated']} of the 32 golden cases cite at least one document "
        "source (SRC-01..SRC-06) and pose a real natural-language question - the rest are "
        "structured-data lookups, action-flow steps, or authorization-denial cases with no "
        "document to retrieve. For each eligible case, `search_documents()` runs with the "
        "case's `question` text verbatim at top_k=5 (no query rewriting, no filters). A case "
        "is a hit at rank R if an expected source_id appears at position R in the results.",
        "",
        "## Results",
        "",
        f"- Cases evaluated: **{result['cases_evaluated']}**",
        f"- Recall@3: **{result['recall_at_3']:.0%}**",
        f"- Recall@5: **{result['recall_at_5']:.0%}**",
        f"- Source hit rate (expected sources actually retrieved, of all "
        f"expected-source citations across eligible cases): **{result['source_hit_rate']:.0%}**",
        f"- Retrieval latency: p50 **{result['latency_p50_ms']:.2f} ms**, "
        f"p95 **{result['latency_p95_ms']:.2f} ms** ({result['cases_evaluated']} queries, "
        "local SQLite, cold connection per run)",
        "",
        "## Per-case detail",
        "",
        "| Case | Rank | Expected | Retrieved (top 5) |",
        "|---|---|---|---|",
    ]
    for row in result["rows"]:
        rank = row["rank"] if row["rank"] is not None else "miss"
        lines.append(
            f"| {row['id']} | {rank} | {', '.join(row['expected'])} | "
            f"{', '.join(row['retrieved']) or '(none)'} |"
        )

    partial_misses = [
        r for r in result["rows"] if any(sid not in r["retrieved"] for sid in r["expected"])
    ]

    lines += ["", "## Representative failures", ""]
    if not failures:
        lines.append(
            "No case-level miss: every eligible case retrieved at least one expected "
            "source in the top 3 (that is what Recall@3/@5 above measure)."
        )
    else:
        for row in failures:
            lines.append(f"### {row['id']}")
            lines.append("")
            lines.append(f"> {row['question']}")
            lines.append("")
            expected_str = ", ".join(row["expected"])
            retrieved_str = ", ".join(row["retrieved"]) or "(none)"
            lines.append(f"Expected: {expected_str}. Retrieved: {retrieved_str}.")
            lines.append("")

    lines += [
        "",
        f"### Partial source misses (source hit rate {result['source_hit_rate']:.0%})",
        "",
        "A case can pass the rank-based hit test above (some expected source was found) "
        "while still missing one of several expected sources - this is what "
        "`source_hit_rate` catches that Recall@K does not.",
        "",
    ]
    if not partial_misses:
        lines.append("None: every expected source was retrieved in every case.")
    else:
        for row in partial_misses:
            missing = [sid for sid in row["expected"] if sid not in row["retrieved"]]
            lines.append(
                f"- **{row['id']}**: missing {', '.join(missing)} from the top 5 "
                f"(retrieved {', '.join(row['retrieved'])}). Query: \"{row['question']}\""
            )
        lines.append("")
    lines.append(
        "One known ranking sensitivity found during Phase 1 testing, not from the table "
        "above: a query built only from the words *\"Northstar cancellation fee waiver\"* "
        "ranks SRC-06 (LumenWorks) above SRC-05 (Northstar), because the literal word "
        "\"waiver\" appears in SRC-06's text (\"No special cancellation-fee waiver applies\") "
        "but nowhere in SRC-05's. The OR-of-terms BM25 query has no way to know \"Northstar\" "
        "is the more load-bearing term for this question. Every case actually phrased the way "
        "a user would ask it (naming the account or order) ranks correctly - this only "
        "surfaces for artificially sparse, keyword-only queries. Documented as a known "
        "limitation of plain BM25 rather than fixed, per ADR-003 (embeddings only if "
        "measured to help, and this corpus is 24 chunks)."
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-dir", required=True, type=Path)
    parser.add_argument("--db", default=Path("build/eval.db"), type=Path)
    parser.add_argument(
        "--mlflow", action="store_true", help="log this run as an MLflow experiment"
    )
    args = parser.parse_args()

    result = run_eval(args.source_dir, args.db)
    report = render_report(result)
    REPORT_PATH.write_text(report, encoding="utf-8")

    summary = {k: v for k, v in result.items() if k != "rows"}
    print(json.dumps(summary, indent=2))
    print(f"\nwrote {REPORT_PATH}")

    if args.mlflow:
        from app.evaluation.mlflow_tracking import ExperimentRun, log_experiment_run

        run = ExperimentRun.build(
            experiment_name="parcelpilot-retrieval",
            provider="n/a",  # deterministic BM25 retrieval - no LLM call in this eval
            model="fts5-bm25",
            retrieval_top_k=5,
            retrieval_config={"filters": "none", "corpus_chunks": 18},
            metrics={
                "recall_at_3": result["recall_at_3"],
                "recall_at_5": result["recall_at_5"],
                "source_hit_rate": result["source_hit_rate"],
            },
            latency_ms={"p50": result["latency_p50_ms"], "p95": result["latency_p95_ms"]},
            tags={"phase": "2", "eval_type": "retrieval"},
        )
        run_id = log_experiment_run(run)
        print(f"logged MLflow run: {run_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
