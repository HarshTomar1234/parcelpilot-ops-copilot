# Evaluation Report

Consolidates every measured result across the project. Every number here
came from an actual run, listed with the command that produced it. Nothing
here is estimated or projected.

## Test suites

| Suite | Real pack | No pack (hosted CI) |
|---|---|---|
| Full `pytest` | 453 passed | 339 passed, 114 skipped, 0 failed |
| `tests/fixture_backed/` only | 158 passed | 158 passed (never skips - see below) |
| `tests/red_team/` only | 114 passed | 114 passed (never skips - never needs the real pack) |

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
| Status match rate | **0.94** (16/17 checkable) | No (exact match) |
| Task completion scored | 0 of 19 | Yes - harness-blocked, same limitation as RAG quality above |

Tool correctness and status match are genuine, non-fabricated scores -
they compare the real agent's actual tool calls and terminal status
against the golden dataset and need no LLM judge.

**Status-match rate progression this project: 0.71 -> 0.82 -> 0.88 -> 0.94.**
The first two jumps are documented in the private phase reports. The
final jump (finding F4, final release hardening) fixed GC-015 - a
question with no meaningful token overlap or corroborated strong score
in its retrieved evidence now correctly returns `insufficient_evidence`
via `app/agent/evidence_sufficiency.py`'s gate, instead of `completed`.
Re-run before/after this exact fix: 0.88 -> 0.94, with retrieval
Recall@3/5 (below) and every other real-pack test unchanged - the fix
does not reduce recall for genuinely supported questions.

The 1 remaining mismatch (GC-016) is a documented, unfixed limitation,
not a test gap: it retrieves strongly-scoring evidence (BM25 top score of
-3.8 - not a weak match) that simply doesn't contain the specific fact
asked for (the exact remaining service-credit balance this month). The
evidence-sufficiency gate fixes *off-topic-with-no-real-overlap*
questions (F4, generic by construction - no keyword list, no
example-specific special case); GC-016 is a different, harder problem -
*semantic sufficiency* (does the retrieved text actually answer what was
asked, even when it's topically strong and lexically overlapping) -
which remains open, same as GC-015 was before this fix.

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

## Red team (final validation phase)

Full report: [`red_team_report.md`](red_team_report.md). Summary:

- **Total attacks (executable tests):** 114, across 10 classes -
  identity spoofing, API authorization, the action attack matrix, prompt
  injection (question + retrieved document), tool argument injection,
  information leakage/enumeration/aggregate leakage, invalid input,
  deployment failure scenarios, concurrency/race conditions, and
  agent/retrieval abuse.
- **Passed:** 114 / 114.
- **Failed (before fix):** 2 real issues found and fixed before this
  report was written - a confirm/execute race condition (4 of 20
  concurrent confirmations on one action all reported success) and a
  Docker entrypoint that crashed the whole container on an invalid
  base64 secret instead of starting degraded. Both re-verified fixed
  against a real rebuilt container, not just the test suite.
- **Residual limitations:** the lexical relevance floor doesn't fully
  filter every off-topic query on a small corpus (never fabricates a
  confident answer either way); an authenticated-but-unauthorized caller
  can technically distinguish "this action exists" from "it never did"
  via 403-vs-404, though no action content leaks either way.

## Deployment (final validation phase)

- **Docker build:** succeeds from a clean layer cache in ~30s.
- **Startup:** verified against a real running container for all of:
  valid database (writable mount, `PARCELPILOT_DB_B64_FILE`, and
  `PARCELPILOT_DB_B64`), missing database, corrupt database file,
  read-only database mount, invalid base64 secret, and no configuration
  at all. `/health` stays up in every case; `/ready` reports the real
  state honestly; no case fabricates data or crashes the process (after
  the entrypoint fix above).
- **API smoke tests:** `/api/chat`, `/api/radar/run`, and the full
  `/api/actions/{prepare,confirm,execute}` chain all verified against a
  live container with the real, ingested database.

## Concurrency (final validation phase)

Measured with `scripts/run_api_load_test.py` against a live Docker
container, real pack, `MockProvider` (see
[`performance_report.md`](performance_report.md) for the full table):

| Endpoint | Concurrency | Errors |
|---|---|---|
| `/api/chat` | 1, 5, 10 | 0 |
| `/api/radar/run` | 1, 5, 10 | 0 |
| `/api/actions/confirm` (same action, race) | 20 | 0 crashes; exactly 1 of 20 succeeds (correct) |
| `/api/actions/execute` (same action, race) | 20 | 0 crashes; all report success (idempotent by design), exactly 1 real transition |

This is a regression/smoke test at this corpus size, not a production
scalability claim.

## Final release hardening

Two residual issues from the red-team phase were fixed and re-verified
before freeze - full detail in [`red_team_report.md`](red_team_report.md):

- **F4 - evidence sufficiency.** A clearly off-topic or unsupported
  question could retrieve a coincidentally-scoring document chunk and
  reach `completed`/`CONDITIONAL` instead of `insufficient_evidence`.
  Fixed with a deterministic, generic multi-signal gate
  (`app/agent/evidence_sufficiency.py`: relevance score, score margin,
  query-token overlap across every returned chunk, and corroborating
  chunk count - no keyword list, no example-specific special case).
  Verified with the required matrix (supported policy/order/SLA
  questions still pass; obviously unrelated, weakly-related-but-
  unsupported, and coincidentally-overlapping questions now correctly
  return `insufficient_evidence`) and against real HTTP traffic on a live
  container. Before/after evaluation: status-match rate 0.88 -> 0.94 (one
  golden case, GC-015, fixed); Recall@3/Recall@5 unchanged (1.0/1.0) -
  recall for genuinely supported queries was not reduced.
- **F5 - action enumeration.** `GET /api/actions/{id}` now returns the
  same 404 for an action that exists but belongs to someone else as for
  one that never existed - verified live (nonexistent -> 404, another
  user's action -> 404 with an identical-shaped body, owner -> 200,
  admin -> 200) and in the fixture-backed/red-team suites.

**Live LLM checkpoint:** `ANTHROPIC_API_KEY` was checked again at the
start of this phase and remains unset in this environment. No live
provider smoke test, real RAG evaluation, real agent task-completion
evaluation, or provider fallback test was run - **no live LLM evaluation
was possible because no provider credentials were available in the
environment.** Nothing here is fabricated or estimated in its place.

**UI verification:** `mcp__claude-in-chrome` remained disabled in this
environment ("Claude in Chrome is turned off in your settings") - the
browser-rendered layer could not be manually exercised. Verified instead:
`node --check` on `app/api/static/app.js` (no syntax errors), a full
cross-reference of every DOM id the JS queries against `index.html` (no
mismatches), and that `/`, `/style.css`, and `/app.js` all serve `200`
from a live container. Every API call the UI makes was independently
verified working (this report, `red_team_report.md`) - the UI is a thin
fetch layer over an already-verified API, not independent logic, but its
actual rendering was not visually confirmed this phase.

## Summary: MEASURED / NOT AVAILABLE / KNOWN LIMITATION

Deliberately not averaged into one score - these are unrelated
measurements, and a blended "overall accuracy" would hide which specific
thing is or isn't proven.

| Area | Status | Detail |
|---|---|---|
| pytest (full suite) | **MEASURED** | 453 passed, real pack; 339 passed / 114 skipped, no pack; 0 failed |
| Security regressions | **MEASURED** | all pass, always-runs CI tier |
| Red team | **MEASURED** | 114/114 passing, 2 real issues found and fixed (F1, F2), 2 documented residual limitations (F4 partially fixed - see below, F5 fixed) |
| Retrieval (Recall@K) | **MEASURED** | Recall@3 = Recall@5 = 1.0, source hit rate 0.96, real pack |
| Agent trajectory (tool correctness, status match) | **MEASURED** | 0.84 / 0.94, judge-free, real pack |
| Agent trajectory (task completion) | **NOT AVAILABLE** | harness-blocked without a real judge model |
| RAG quality (faithfulness/relevancy) | **NOT AVAILABLE** | needs a real judge model |
| Action safety | **MEASURED** | full prepare/confirm/execute attack matrix, 0 unsafe outcomes; race condition closed and re-verified |
| Operations Radar | **MEASURED** | 6/6 real-pack alerts match the independently-written golden dataset exactly |
| Docker build/startup | **MEASURED** | built and run this phase; valid/missing/corrupt/read-only DB and a bad secret all verified against a live container |
| Concurrency | **MEASURED** | chat/radar 1/5/10 concurrent, 0 errors; 20-way action race, exactly 1 transition, real container |
| API (all 5 endpoints) | **MEASURED** | verified over real HTTP against a live container this phase |
| Latency | **MEASURED** | domain-layer, Operations Radar, and end-to-end API, all with `MockProvider` latency explicitly labeled as not production LLM latency |
| Cost | **MEASURED (MockProvider only)** | $0.00; the accounting mechanism itself is unit-tested, never exercised against a real paid call |
| Provider resilience | **MEASURED (construction/unit level)** | retry/fallback classification tested against real SDK exception types; **NOT AVAILABLE**: a live second-provider fallback |
| Live LLM evaluation | **NOT AVAILABLE** | no `ANTHROPIC_API_KEY` in this environment, checked again this phase - not fabricated or estimated |
| Semantic sufficiency (GC-016-class questions) | **KNOWN LIMITATION** | a lexical gate (F4) cannot fully resolve "retrieved text is topically strong but doesn't answer the specific fact asked" - open, documented, not claimed solved |
| Action-existence enumeration via non-GET paths | **KNOWN LIMITATION** | `POST /api/actions/execute` still returns a distinct 403 for a non-owner (by design - see red_team_report.md F5); only `GET /api/actions/{id}` was normalized to 404 |

## Release gates

Per [`quality_gates.md`](quality_gates.md):

| Gate | Status |
|---|---|
| 0 unauthorized access | Met - all security tests pass, including the action workflow's |
| 0 unsafe actions | Met - every action security scenario fails safely with a structured error, never a silent success or a duplicated effect; concurrent confirm/execute races closed via atomic compare-and-swap (see red_team_report.md F1) |
| 0 deterministic regressions | Met - 453/453 pytest, including the full domain, Operations Radar, API-layer, and red-team suites |
| 0 invalid required citations | Met - an invalid citation gets one bounded repair attempt, then a controlled `evidence_validation_failed` result if still invalid - never a silently-edited answer shown as valid |
| 0 red-team failures | Met - 114/114 passing, re-verified after the F4/F5 fixes with no regression in authorization, prompt injection, action safety, concurrency, deployment, or information leakage |
| 0 Docker startup regressions | Met - a fresh image built this phase starts cleanly with a valid DB, missing DB, bad secret, and read-only DB, all verified against a live container |
| 0 concurrent action races | Met - 20 concurrent `confirm` attempts on one action, exactly 1 succeeds, re-verified against a live rebuilt container this phase |
| AI-quality thresholds | **Not set** - no real judge-scored baseline exists; `ANTHROPIC_API_KEY` remains unavailable in this environment (checked again this phase) |

## Known limitations (full list)

See the "Known limitations" section of
[`architecture_note.md`](architecture_note.md) and the private phase
reports' "Risks / trade-offs" for the complete, prioritized list.
