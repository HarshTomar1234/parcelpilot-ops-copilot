# Architecture Note: The Agent Layer

This note covers `app/agent/` (the bounded question-answering state
machine) and `app/actions/` (the state-changing action workflow) on top
of the deterministic domain layer and tool contracts. For the
domain/retrieval/policy architecture underneath it, see
[`architecture_decision_record.md`](architecture_decision_record.md).

## The one rule

The LLM is a reasoning and rendering component. It understands the
question, and it writes the final explanation. It never decides a fee,
a deadline, a severity, a trust level, or which source wins a conflict -
all of that is Python, computed before the LLM is ever called, and handed
to it as facts it is told not to alter.

## The pipeline

```
question
  |
  v
resolve_entities()      deterministic ID-shape + name matching,
                         authorization-scoped, never hardcoded to a
                         literal ID prefix
  |
  v
resolve_intent()         deterministic (no LLM call) - see "why no second
                          model call" below
  |
  v
build_plan()              one tool-call list per intent; a severity
                           question never touches calculate_support_outcome
                           with calculation_type=cancellation
  |
  v
execute_tool() x N        controlled registry (3 tools only); every
                           exception - including an unknown tool name -
                           normalizes into ToolResult, never a raw
                           exception reaching this loop
  |
  v
build_evidence_pack()     assembled only from real ToolResult outputs
  |
  v
enforce_trust_gate()      the one place TrustState is decided; takes the
                           worst of every domain result involved
  |
  v
compose_response()        one LLM call, renders over the verified pack
  |
  v
validate_citations()      invalid -> one bounded repair call -> validate
                           again -> still invalid means a controlled
                           evidence_validation_failed result, never a
                           silently-edited answer presented as valid
  |
  v
AgentRunResult
```

Implemented as a single linear function (`run_agent()` in
`app/agent/orchestrator.py`) rather than a generic state-machine
framework - the state graph has one path with early-exit terminal
branches (`needs_clarification`, `insufficient_evidence`, `failed`,
`escalated`, `completed`), and a framework class would add indirection
without adding safety. Every transition is recorded in a `state_trace`
list on the result, so a failure is diagnosable after the fact without
re-running anything.

## Why no second LLM call for intent

A regex-and-entity-driven classifier answers "which tools does this
question need" as reliably as a model call would, for a fixed, small set
of supported intents, at zero latency and zero cost. A second model call
buys nothing here and the spec asks explicitly to avoid one when a
deterministic pass suffices.

## The trust gate is structural, not conventional

`TrustState` for a request is computed once, in
`app/agent/trust_gate.py`, in code the LLM's output never touches. The
response-composition prompt is told the trust state as an already-decided
fact ("do not restate a higher confidence") - there is no code path by
which the model's text could upgrade UNCERTAIN or CONDITIONAL to
CONFIDENT, because trust_state is never derived from the model's output in
the first place.

One nuance worth naming: the domain layer's `needs_human_review` flag is
*not* the same signal as trust state. Sometimes it means epistemic
uncertainty (a tied severity classification - already routed into
`TrustState.ESCALATE`); sometimes it means "this confidently-established
fact should trigger an operational escalation workflow" (a P1 SLA breach
is still a `CONFIDENT` answer, but the business rule says route it to a
human anyway). Only the epistemic case changes the agent's own response
status; the operational case is surfaced as content in the answer instead.
Conflating the two was a real bug this phase - see the phase report for
how it was found and fixed.

## Tool boundary

Three tools, typed request/response contracts, each Pydantic-validated
before dispatch: `search_documents`, `lookup_structured_data`,
`calculate_support_outcome`. No repository, domain module, or raw SQL is
ever exposed to the planner directly - `app/agent/registry.py::execute_tool`
is the only dispatch point, and authorization is enforced inside the real
tool functions (never re-derived from the tool's own arguments - auth is
always the trusted, backend-supplied second parameter).

Entity resolution runs *before* planning and drops anything the caller
isn't authorized to see - a cross-account ID reference in the question
text never reaches a tool call at all; it simply fails to resolve, and the
request ends in `insufficient_evidence` rather than an authorization error
that would confirm the record exists. `execute_tool()` still checks for
`NOT_AUTHORIZED` inside the tool-execution loop as defense in depth, even
though this should not be reachable if entity resolution did its job.

## Provider resilience

`app/llm/gateway.py::ParcelPilotLLMGateway` wraps an ordered list of
`(provider, model)` candidates and tries each in turn, recording every
attempt (`provider_attempts`, `fallback_used`, `fallback_reason`,
`total_cost_usd`, `total_latency_ms`) on `.last_run`. It implements the
same `name`/`complete()` shape as a single `LLMProvider`, so it is a
drop-in replacement anywhere a provider is accepted - verified directly by
passing a gateway to `run_agent()` with zero changes to the orchestrator
or response composer.

## Action workflow

`app/actions/workflow.py` implements one state-changing action
(`prepare_escalation`) as three separate calls - `prepare_action`,
`confirm_action`, `execute_action` - never fewer. `prepare_escalation` is
read-only against orders/tickets/accounts; its only write is inserting a
`PENDING_CONFIRMATION` row into the `actions` table, which is the audit
trail itself, not a separate log. Escalation eligibility is a
deterministic rule (P1 severity or an SLA breach), never an LLM
judgment. `confirm_action` re-validates authorization against the
*current* caller (not the original preparer's cached auth), checks
expiry, payload hash, and that the target's state hasn't changed since
prepare. `execute_action` is idempotent - calling it again on an already-
`EXECUTED` action returns the same result rather than repeating the
(mocked) effect.

The agent (`app/agent/orchestrator.py`) has no code path to
`confirm_action` or `execute_action` at all - not gated by a check, but
because the module never imports them. A recommendation to escalate
reaches the user only as text in the composed answer (via the
`needs_human_review` flag described above); actually preparing, confirming,
and executing an action is a separate operation this phase, outside the
question-answering loop.

## What this deliberately does not do

No multi-turn conversation memory. No bulk/aggregate queries across many
records - the planner is single-entity per request. No frontend beyond a
CLI dev harness (`scripts/run_agent_cli.py`). No Operations Radar. No
Airflow/scheduler - nothing here has the multi-stage, scheduled work a
DAG orchestrator is for. No second action type beyond `prepare_escalation`
- a ticket-update action was explicitly optional and wasn't built. These
are later-phase scope, not oversights.

## Known limitations

- No prompt-injection test targets a manipulated `payload_hash` submitted
  through a channel other than a direct function call (e.g. a
  hypothetical future HTTP API) - today's tests call `confirm_action`
  directly, which is the only entry point that exists.
- The action-eligibility rule (P1 or breached) is intentionally narrow;
  it does not account for account-level agreement terms the way the
  cancellation/service-credit calculators do.

See [`docs/evaluation_report.md`](evaluation_report.md) for the measured
numbers behind these claims.
