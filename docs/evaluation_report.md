# Evaluation Report

Consolidates every measured result across the project. Every number here
came from an actual run, listed with the command that produced it. Nothing
here is estimated or projected.

## Test suites

| Suite | Real pack | No pack (hosted CI) |
|---|---|---|
| Full `pytest` | 265 passed | 155 passed, 110 skipped, 0 failed |
| `tests/fixture_backed/` only | 88 passed | 88 passed (never skips - see below) |

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

## Release gates

Per [`quality_gates.md`](quality_gates.md):

| Gate | Status |
|---|---|
| 0 unauthorized access | Met - all security tests pass, including the action workflow's |
| 0 unsafe actions | Met - every action security scenario fails safely with a structured error, never a silent success or a duplicated effect |
| 0 deterministic regressions | Met - 265/265 pytest, including the full domain suite |
| 0 invalid required citations | Met - an invalid citation gets one bounded repair attempt, then a controlled `evidence_validation_failed` result if still invalid - never a silently-edited answer shown as valid |
| RAG/agent quality thresholds | **Not set** - no real judge-scored baseline exists yet (MockProvider limitation) |

## Known limitations (full list)

See the "Known limitations" section of
[`architecture_note.md`](architecture_note.md) and the private phase
reports' "Risks / trade-offs" for the complete, prioritized list.
