# ParcelPilot Ops Copilot

An internal support/operations assistant for ParcelPilot staff. It answers
questions by retrieving from the supplied policy/agreement corpus, looking up
scoped operational data, computing outcomes deterministically, citing
evidence, surfacing source conflicts, and requiring confirmation before any
state change.

**Status: Phase 3 complete (bounded agent orchestration).** A CLI dev
harness exists (`scripts/run_agent_cli.py`); no chat interface, no action
execution, no Operations Radar, no full UI yet - see [Roadmap](#roadmap).

## Overview

The system is built around one rule: an LLM (once one is wired in) may
explain a result, never compute or alter one. Everything that determines
money, deadlines, or entitlements - cancellation fees, service credits, SLA
deadlines, ticket severity - is deterministic Python, cross-checked against
an independently-verified table of facts derived from the actual source
pack. Source authority (a signed agreement vs. the default policy vs. a
deprecated document) is resolved by an explicit, citable precedence rule,
never by "whichever result came back first."

## Capabilities

- A bounded agent (`app/agent/`) that resolves entities and intent
  deterministically, plans and executes only approved tools, builds a
  verified evidence pack, applies a hard trust gate, and composes a
  grounded, cited answer - the LLM renders, it never decides a fact. See
  [`docs/architecture_note.md`](docs/architecture_note.md).
- A provider-resilient LLM gateway (`app/llm/gateway.py`) with ordered
  fallback across providers, recording every attempt and whether a
  fallback was used.
- Deterministic cancellation, service-credit, SLA, and severity calculations,
  each returning a typed result with its trust state, evidence, assumptions,
  and any source conflict it resolved.
- Clause-level source-authority resolution: an agreement overrides only the
  specific clauses it addresses, never blanket - including cases where the
  agreement's *silence* on a topic is the fact.
- Deterministic full-text document retrieval (SQLite FTS5 + BM25) with
  authorization-aware metadata filtering applied before ranking.
- Typed, authorization-scoped structured-data lookups for accounts, orders,
  and tickets.
- Three typed tool contracts (`search_documents`, `lookup_structured_data`,
  `calculate_support_outcome`) - the only interface a future agent will use;
  never raw SQL, never an unvalidated dict.
- A provider-agnostic LLM gateway with full token/cost accounting, a
  deterministic mock provider for tests and CI, and a real Anthropic-backed
  provider behind the same interface.
- Request tracing (`request_id`/`trace_id`) via an OpenTelemetry-compatible
  interface, and structured JSON logging throughout.
- A DeepEval-based RAG evaluation harness and MLflow experiment tracking,
  both wired to the same LLM gateway.

## Architecture

```
source pack (PDFs + xlsx, external, never committed)
        |
        v
scripts/ingest_sources.py  ->  build/parcelpilot.db (SQLite, rebuilt each run)
        |
        +--> app/documents/retrieval.py          search_documents()
        +--> app/structured_data/repository.py   get_*/search_* (AuthContext-scoped)
        |
        v
app/policy/applicability.py   which source's clause governs (topic, account)?
        |
        v
app/domain/{cancellation,service_credit,sla,severity}.py
   deterministic calculation -> DecisionResult[T]
   (trust_state, evidence, assumptions, conflicts, needs_human_review)
        |
        v
app/agent/tools.py   typed tool contracts (Pydantic request/response,
                      traced via app/observability/tracing.RequestContext)
        |
        v
app/llm/   LLMProvider gateway (MockProvider / AnthropicProvider),
           ParcelPilotLLMGateway (ordered fallback across providers)
   -> app/llm/deepeval_bridge.py -> DeepEval RAG + agent trajectory metrics
   -> app/evaluation/mlflow_tracking.py -> MLflow experiment log
        |
        v
app/agent/   run_agent(): entities -> intent -> plan -> tools -> evidence
             pack -> trust gate -> LLM response -> citation validation
        |
        v
scripts/run_agent_cli.py   minimal dev harness (no frontend)
```

Full rationale for every decision is in
[`docs/architecture_decision_record.md`](docs/architecture_decision_record.md)
(ADR-001 through ADR-020).

## Data and evidence

Every domain result carries `evidence`: typed `EvidenceRef`s pointing at a
document (source + real page number + section, looked up from the ingested
chunks - never hand-typed), a structured record (table + record ID), or a
calculation. Conflicts between sources are returned as structured `Conflict`
objects (winner, loser, scope, reason), not resolved silently. Where the
source pack cannot support an answer - a business calendar it never defines,
an SLA compliance question the workbook has no column for - the result's
`trust_state` is `CONDITIONAL` or `UNCERTAIN`, with the gap stated in
`reason`, not filled with a guess.

## Evaluation

Three layers, each answering a different question:

- **pytest** (`tests/`) - deterministic correctness: parsing, authorization,
  domain calculations, state transitions. Includes a suite that runs
  `tests/evaluation/golden_cases.json`'s own facts through the real
  deterministic engine (`tests/evaluation/test_golden_domain_cases.py`), not
  hand-picked assertions.
- **Retrieval evaluation** (`scripts/run_retrieval_eval.py`) - Recall@K,
  source hit rate, and p50/p95 latency against the golden set. Report:
  [`docs/retrieval_evaluation.md`](docs/retrieval_evaluation.md).
- **DeepEval RAG baseline** (`scripts/run_deepeval_baseline.py`) - RAG
  faithfulness and contextual relevancy, LLM-judged. Report:
  [`docs/deepeval_baseline.md`](docs/deepeval_baseline.md). **Produces zero
  scored cases with `MockProvider`** - DeepEval's structured-output judge
  requirement needs a real model. The report states plainly what *was*
  verified (retrieval -> generation -> judge-call pipeline runs without
  error) versus what needs a real key.
- **Agent trajectory evaluation** (`scripts/run_agent_trajectory_eval.py`)
  - runs the real agent against every eligible golden case and scores tool
  correctness and terminal-status match (both exact-match, no judge
  needed - genuine numbers even with `MockProvider`), plus attempts a
  judge-based task-completion score (harness-blocked, same limitation as
  above). Report:
  [`docs/agent_trajectory_evaluation.md`](docs/agent_trajectory_evaluation.md).
  Consolidated view of every evaluation result:
  [`docs/evaluation_report.md`](docs/evaluation_report.md).
- **Security regressions** (`tests/fixture_backed/test_security.py`) -
  cross-account access, tool-argument injection, SQL-injection-shaped
  input, prompt injection - in the public, always-runs CI tier.

Evaluation scripts accept `--mlflow` to log a reproducible experiment run
(git SHA, config, metrics, latency, cost) to a local MLflow store - see
[Configuration](#configuration).

Gates distinguishing what's enforced today from what's pending a real
baseline: [`docs/quality_gates.md`](docs/quality_gates.md). Measured
structured-data/domain-calculation latency:
[`docs/performance_report.md`](docs/performance_report.md).

## Configuration

See `.env.example`.

| Variable | Purpose |
|---|---|
| `PARCELPILOT_SOURCE_DIR` | Path to the source pack (never committed) |
| `PARCELPILOT_DB_PATH` | SQLite database path (default `build/parcelpilot.db`) |
| `ANTHROPIC_API_KEY` | Optional. Everything defaults to `MockProvider` when unset |
| `DEEPEVAL_TELEMETRY_OPT_OUT` | Set to `YES` to stop DeepEval's background analytics calls (set automatically in tests) |
| `BUSINESS_*` | Placeholders for a future phase's business-calendar assumption ([ADR-007](docs/architecture_decision_record.md)) - unused by anything today |

MLflow tracking is local-only: `sqlite:///build/mlflow.db`, gitignored, no
server (see [ADR-020](docs/architecture_decision_record.md)).

## Quickstart

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -e ".[dev,llm,evaluation]"

.venv\Scripts\python.exe scripts\ingest_sources.py --source-dir "<pack>\source-pack" --db build\parcelpilot.db
.venv\Scripts\python.exe -m pytest -q
```

The `llm` and `evaluation` extras are optional (`anthropic`; `deepeval`,
`mlflow`) - omit them for a minimal `[dev]`-only install if you only need
ingestion, retrieval, and the domain layer.

## Development

```powershell
.venv\Scripts\python.exe -m ruff check app scripts tests
.venv\Scripts\python.exe -m pyright app scripts\ingest_sources.py scripts\run_retrieval_eval.py scripts\run_deepeval_baseline.py scripts\run_performance_benchmark.py scripts\run_agent_cli.py scripts\run_agent_trajectory_eval.py tests
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts\run_retrieval_eval.py --source-dir "<pack>\source-pack"
.venv\Scripts\python.exe scripts\run_deepeval_baseline.py --source-dir "<pack>\source-pack"
.venv\Scripts\python.exe scripts\run_agent_trajectory_eval.py --source-dir "<pack>\source-pack"
.venv\Scripts\python.exe scripts\run_performance_benchmark.py --source-dir "<pack>\source-pack"
.venv\Scripts\python.exe scripts\run_agent_cli.py --question "Is TKT-501 within its first-response SLA?"
```

See [`docs/demo_script.md`](docs/demo_script.md) for a full walkthrough of
`run_agent_cli.py`.

A `Makefile` wraps the same commands (`make lint`, `make typecheck`, `make
test`, `make eval`, `make deepeval`, `make perf`, `make check`) for
contributors who have `make`.

## Testing

```powershell
.venv\Scripts\python.exe -m pytest -q
```

Tests that need the source pack look for it via `PARCELPILOT_SOURCE_DIR`,
falling back to `../parcelpilot-assessment/source-pack`, and skip (not fail)
if neither is found - a clean checkout, and hosted CI, both collect cleanly
without the pack (`.github/workflows/ci.yml`).

- `tests/unit/` - parsing, normalization, and gateway/fallback logic in
  isolation.
- `tests/integration/` - full ingest into a temp database, domain
  calculations, policy applicability, tool contracts, and the full agent
  orchestrator against it.
- `tests/regression/` - guards against regressing specific documented traps.
- `tests/evaluation/` - the golden-case regression suite, the DeepEval RAG
  harness test, and the agent trajectory harness test.
- `tests/fixture_backed/` - the public, always-runs CI tier: domain rules,
  authorization, retrieval, SLA/severity, security regressions, and agent
  ID-generality tests, all against a fabricated dataset. Never needs the
  real pack, never skips.

## Deployment

Not built yet - no HTTP surface exists. See the Roadmap.

## Limitations

- No action execution, no chat interface, no full UI, no Operations Radar
  yet - a CLI dev harness (`scripts/run_agent_cli.py`) is the only way to
  exercise the agent today.
- Retrieval cannot yet distinguish "weak match" from "no relevant evidence"
  - an off-topic question currently still returns a low-confidence answer
  instead of a clean refusal (see
  [`docs/architecture_note.md`](docs/architecture_note.md)).
- No clarification prompt for an ambiguous multi-account question that
  names no specific order/account.
- No bulk/aggregate queries across many records - the agent is
  single-entity per request.
- Authorization is account-scope filtering only; role-based field
  allowlists and action permissions are not implemented.
- Business-hour SLA targets are parsed but not evaluated - the pack never
  defines a business calendar.
- No real DeepEval quality score exists yet for RAG or agent task
  completion (see Evaluation above) - both harnesses are verified to run,
  not verified to produce good numbers; agent tool-correctness and
  status-match scores are real, since they don't need a judge.
- `AnthropicProvider` and `ParcelPilotLLMGateway`'s fallback routing are
  construction/unit-tested only; no live API call has been exercised (no
  key was available while building this).
- No prompt-injection test covers retrieved document content, only
  question text.
- The SQLite database is single-writer and rebuilt from scratch each run;
  fine at this corpus size, not a concurrency design.
- No Airflow/scheduler - nothing yet needs one
  ([`docs/airflow_decision.md`](docs/airflow_decision.md)).

## Design notes

[`docs/architecture_decision_record.md`](docs/architecture_decision_record.md)
covers retrieval strategy, source-authority precedence, the policy/domain
split (who-wins vs. what-they-say), the LLM gateway design, pricing-as-data,
and the tracing-now/monitoring-platform-later choice.
[`docs/architecture_note.md`](docs/architecture_note.md) covers the Phase 3
agent layer specifically. [`docs/product_note.md`](docs/product_note.md)
describes the product from a user's perspective - what it can and can't do
today.

## AI-assisted development

Built with Claude (Anthropic) via Claude Code: implementation, test writing,
and running every verification command referenced in this README and in
[`docs/_internal/phase-reports/`](docs/_internal/phase-reports/) (private,
gitignored). Every claim of "done" here corresponds to a command that was
actually run, including the ones that surfaced a real limitation (MockProvider
cannot judge DeepEval metrics; MLflow's filesystem backend is deprecated)
rather than a clean success. Full account for this phase:
[`docs/AI_USAGE.md`](docs/AI_USAGE.md).

## Roadmap

Phase 1 data & retrieval (done) -> Phase 2 deterministic domain layer &
LLMOps foundation (done) -> Phase 3 bounded agent orchestration (done) ->
Phase 4 role/field-level authorization -> Phase 5 action confirmation &
audit -> Phase 6 Operations Radar -> Phase 7 full evaluation, cost,
observability -> Phase 8 UI -> Phase 9 deployment -> Phase 10 docs & demo.
