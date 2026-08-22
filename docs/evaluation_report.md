# Evaluation Report

Consolidates every measured result across the project. Every number here
came from an actual run, listed with the command that produced it. Nothing
here is estimated or projected.

## Test suites

| Suite | Real pack | No pack (hosted CI) |
|---|---|---|
| Full `pytest` | 331 passed | 217 passed, 114 skipped, 0 failed |
| `tests/fixture_backed/` only | 150 passed | 150 passed (never skips - see below) |

(Requires the `api` extra - `pip install -e ".[dev,llm,evaluation,api]"` -
since `tests/fixture_backed/` now exercises `app/api/` via FastAPI's
`TestClient`. Without it, that tier's API-specific test files fail to
collect; every other suite is unaffected.)

`tests/fixture_backed/` is the only suite `.github/workflows/ci.yml`
guarantees runs and never skips - it uses a fabricated, version-controlled
dataset (`tests/fixtures/seed_fixture_db.py`) instead of the real,
never-committed source pack. It includes every security regression
(question-text injection, retrieved-document injection, action-workflow
attacks), budget enforcement, tool timeout/retry, citation repair,
clarification, retrieval relevance, and the full action workflow.

## Retrieval

`scripts/run_retrieval_eval.py` - see
[`retrieval_evaluation.md`](retrieval_evaluation.md) for the full report.
`app/agent/tools.py::MIN_RELEVANCE_SCORE` (a lexical relevance floor
applied at the agent's tool boundary, not in this script) is documented
separately below.

## RAG quality (DeepEval)

`scripts/run_deepeval_baseline.py` - see
[`deepeval_baseline.md`](deepeval_baseline.md). 16 cases evaluated, 0
scored: `MockProvider` cannot satisfy DeepEval's structured-JSON judge
requirement. Still no `ANTHROPIC_API_KEY` in this environment.

## Agent trajectory (DeepEval)

`scripts/run_agent_trajectory_eval.py` - full per-case table in
[`agent_trajectory_evaluation.md`](agent_trajectory_evaluation.md). Run
against the real pack, `MockProvider`:

| Metric | Value | Judge needed? |
|---|---|---|
| Cases evaluated | 19 | - |
| Mean tool correctness | **0.84** | No (exact match) |
| Status match rate | **0.88** (15/17 checkable) | No (exact match) |
| Task completion scored | 0 of 19 | Yes - harness-blocked, same limitation as RAG quality above |

Tool correctness and status match are genuine, non-fabricated scores -
they compare the real agent's actual tool calls and terminal status
against the golden dataset and need no LLM judge.

**Status-match rate progression this project: 0.71 -> 0.82 -> 0.88.**
The first jump (fixing a bug that conflated an operational "needs human
follow-up" flag with epistemic trust) and the second (adding the
clarification gate for GC-002, with an aggregate-question carve-out for
GC-028 added immediately after it introduced a regression there) are both
documented in the private phase reports.

The 2 remaining mismatches (GC-015, GC-016) are a documented, unfixed
limitation, not a test gap: both retrieve strongly-scoring evidence (BM25
top scores of -3.8 and -14.5 respectively - not weak matches) that simply
doesn't contain the specific fact asked for (how to change a billing
contact; the exact remaining service-credit balance this month). The
Phase 4 lexical-relevance threshold (`MIN_RELEVANCE_SCORE`) fixes
*off-topic* questions like "What is the weather today?" - a different,
easier problem than *semantic sufficiency* (does the retrieved text
actually answer what was asked), which remains open.

## Security

All tests in `tests/fixture_backed/test_security.py`,
`test_document_prompt_injection.py`, and `test_action_security.py` pass,
in the always-runs public CI tier:

- Cross-account access denial, both for question-answering (tool calls,
  full agent pipeline) and for the action workflow (prepare/confirm
  target validation)
- Unknown tool name handled without a raw exception
- Authorization cannot be widened via smuggled tool arguments
- SQL-injection-shaped input treated as inert text, tables intact
- Prompt injection in question text AND in retrieved document content
  (a worst-case "compliant" fake model that tries to obey embedded
  instructions still cannot add a tool call, change trust_state, leak a
  fabricated citation, or widen authorization) does not bypass anything
- Action workflow: unauthorized/cross-account prepare, confirmation
  missing, wrong-user confirmation, expired action, changed target state,
  duplicate execution (idempotent, not just rejected), replayed
  confirmation, manipulated payload hash all fail safely with a
  structured error code
- No prompt can reach `confirm_action`/`execute_action` at all - verified
  structurally (the orchestrator module never imports either function),
  not just behaviorally

## Performance

Structured-data/domain-calculation latency: sub-millisecond at this
corpus size, see [`performance_report.md`](performance_report.md). A full
`run_agent()` call (3-tool cancellation case, real pack, `MockProvider`):
~2.6ms total. The action workflow (prepare/confirm/execute) runs
~100-230ms per call - roughly 1000x the read-only operations above,
because every call durably commits its audit row to disk, a deliberate
choice for the audit trail, not measured overhead to remove. Neither
number is a production latency claim - the real LLM-call cost is a
network round trip, unexercised (no API key).

## Cost

$0.00 for every run - `MockProvider` is priced at $0/M tokens by
definition. The cost-accounting mechanism (`TokenUsage`, `CostEstimate`,
`PricingTable`, `ParcelPilotLLMGateway.last_run.total_cost_usd`) is built
and unit-tested, not yet exercised against a real, paid call.

## Provider resilience

`ParcelPilotLLMGateway` classifies a provider failure (by exception type
name, shared with `AnthropicProvider`'s own retry classification) before
deciding what to do: a transient failure (timeout, network error, 429,
retryable 5xx) falls over to the next candidate provider; a permanent
failure (bad credentials, malformed request, unknown model) stops
immediately without trying the rest, rather than repeating an
unrecoverable error against every configured provider. Unit-tested with
stub providers (5 tests: success, retryable fallback, all-retryable-fail,
non-retryable-stops-immediately, per-candidate model substitution) and
verified as a drop-in replacement for a single `LLMProvider` by direct
smoke test against the real agent. No live second-provider fallback was
exercised (no second API key available).

## Action safety

`tests/fixture_backed/test_action_workflow.py` and
`test_action_security.py` (21 tests total) cover the full
prepare/confirm/execute lifecycle deterministically - no LLM judge is
used anywhere in this evaluation, per the explicit instruction not to use
one for action safety. Escalation eligibility is a deterministic rule
(P1 severity or an SLA breach); idempotency, expiry, payload integrity,
target-state revalidation, and authorization are all covered with real
pass/fail assertions against the fixture corpus.

## Operations Radar (Phase 5)

`scripts/run_operations_radar_eval.py --source-dir <real pack>` - full
per-alert table in
[`operations_radar_evaluation.md`](operations_radar_evaluation.md).

**Real-pack detection results:** 6 alerts total - `sla_breach`: 2,
`recurring_issue`: 1, `known_issue_pattern`: 2, `overdue_pickup`: 1.
`sla_approaching` and `carrier_pattern` both found 0 (the real pack has no
ticket in an unresolved SLA warning window, and only one carrier-fault
order - below the pattern threshold of 2). Every alert reached
`trust_state=CONFIDENT` with real evidence attached; none of the 6 was
generated via any LLM judgment.

**Golden-case regression (`tests/evaluation/test_golden_operations_radar_cases.py`,
4 tests, real pack):** all 4 pass, matching a golden dataset written
before this phase's detection code existed - exact record IDs
(`TKT-501`/`TKT-505` for the two SLA breaches, `TKT-451`/`TKT-502` for the
`KI-208` known-issue pattern, `ORD-2002` for the overdue pickup), exact
affected accounts, and an exact `4.5`-hours-overdue computation.

**Fixture-backed detection tests (`tests/fixture_backed/test_detection_*.py`,
32 tests, never skip):** rule correctness at the threshold boundary
(below/at/above), deterministic fingerprint/dedup behavior (order
independence, rule-version sensitivity, no duplicate IDs across repeated
runs), authorization (a scoped caller never sees another account's
breach/recurring alert even as a partial count, the named "aggregate
leakage" attack - requesting another account's P1 count - is denied,
`restricted_support` is denied Operations Radar entirely with a
structured error, no path from a detected alert into the action
workflow), and the `detect_issues` tool contract (typed request/response,
no raw SQL/query field exposed, `account_scope` can only narrow a
caller's real access, never widen it).

**Latency (`scripts/run_performance_benchmark.py`, see
[`performance_report.md`](performance_report.md), 30 reps each):** a full
unrestricted detection pass (`full_snapshot_scan`) - p50 6.90ms / p95
7.38ms; a single-account-scoped pass (`scoped_account_query`) - p50
3.08ms / p95 3.41ms. Both well under any interactive latency budget at
this corpus size; scoping to one account is roughly 2x faster than a full
scan, as expected from reading fewer rows, not from a different code
path.

**False-positive control:** one real false positive was found and fixed
during development, not left as a known gap - `TKT-501` ("shipment
creation is failing," an unrelated API error) initially matched
`KI-208` (a bulk-upload issue) purely because both texts happened to
share the generic words "shipment" and "creation." Fixed by excluding
generic domain vocabulary from the match; both true positives
(`TKT-502`, `TKT-504`) still match correctly, and the false positive is
gone on the current real-pack run (0 of 6 alerts is a false positive by
manual verification against the source records each cites).

## API layer and deployment (Phase 6)

**MEASURED** (see [`performance_report.md`](performance_report.md)'s "API
layer" section for the full numbers): 25 fixture-backed API tests
(`tests/fixture_backed/test_api_*.py`) covering health/readiness, chat,
Operations Radar (including the `restricted_support` denial and scope
filtering through the HTTP layer), the full action workflow through HTTP
(prepare -> confirm -> execute -> idempotent re-execute -> audit read
back), and a chained end-to-end path (a chat question, then a separately
prepared/confirmed/executed escalation) - all against the fabricated
fixture corpus, never the real pack, all passing. End-to-end HTTP latency
for `/api/chat` and `/api/radar/run` at 1/5/10 concurrent requests, and a
single-call latency for each action-workflow endpoint, measured against
the real pack through an actual Docker container (`docker build` +
`docker run`), not `TestClient`.

A real concurrency bug was found by this measurement and fixed before
being reported: FastAPI's per-request SQLite connection could cross
threads under concurrent load (`sqlite3.ProgrammingError`), fixed with
`check_same_thread=False` in `app/db/connection.py::connect()` - the
before/after numbers are both in `performance_report.md`, not just the
fixed one. A second real issue was found and documented (not a bug, a
deployment-configuration fact): mounting the database read-only breaks
`prepare_escalation`'s audit-row write - the deployment docs now say so
explicitly.

**NOT AVAILABLE:** live-model cost/latency for `/api/chat` (no
`ANTHROPIC_API_KEY` in this environment - `MockProvider` latency is
reported and labeled as such, never presented as production LLM
latency); a real judge-scored evaluation of the API layer's answers
(the existing DeepEval/agent-trajectory limitation above applies
identically here, since `/api/chat` calls the same `run_agent()`).

## Release gates

Per [`quality_gates.md`](quality_gates.md):

| Gate | Status |
|---|---|
| 0 unauthorized access | Met - all security tests pass, including the action workflow's |
| 0 unsafe actions | Met - every action security scenario fails safely with a structured error, never a silent success or a duplicated effect |
| 0 deterministic regressions | Met - 331/331 pytest, including the full domain, Operations Radar, and API-layer suites |
| 0 invalid required citations | Met - an invalid citation gets one bounded repair attempt, then a controlled `evidence_validation_failed` result if still invalid - never a silently-edited answer shown as valid |
| RAG/agent quality thresholds | **Not set** - no real judge-scored baseline exists yet (MockProvider limitation) |

## Known limitations (full list)

See the "Known limitations" section of
[`architecture_note.md`](architecture_note.md) and the private phase
reports' "Risks / trade-offs" for the complete, prioritized list.
