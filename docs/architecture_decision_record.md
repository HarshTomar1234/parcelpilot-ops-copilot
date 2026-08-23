# Architecture Decision Record

Decisions taken at the end of Phase 0, informed by what the source pack actually
contains. Status of every ADR here: **Accepted (Phase 0)** unless noted.

---

## ADR-001 — Build the internal ops copilot, not the customer-facing bot

**Context.** The brief allows either, or both. The pack's centre of gravity is
internal: cross-account tickets, historical resolutions flagged as unreliable,
known-issue triage, SLA breach detection, and an explicitly requested "internal
view for authorized support and operations users" (extension Problem 1).

**Decision.** Ship the internal copilot for `operations_admin`, `support_agent`,
`restricted_support`. Customer-facing mode is out of scope.

**Consequences.** Authorization is *role + account scope* rather than a single
customer identity, which is a harder and more interesting test. Operations Radar
becomes a first-class surface rather than a bolt-on. If a customer-facing mode is
added later it is a narrower special case of the same scoping (one account, no
aggregates, no historical resolutions) — the model does not need to change.

---

## ADR-002 — Modular monolith, SQLite, no microservices

**Decision.** FastAPI + Pydantic v2 + SQLite in one deployable. Documents,
structured data, audit, and action state all live in one SQLite file built by an
ingestion step.

**Rationale.** The entire corpus is 6 one-page PDFs and 17 data rows. Anything
distributed would be theatre. SQLite gives transactions, FTS5, and a single
artefact to deploy.

**Trade-off.** Single-writer concurrency limits throughput; acceptable at this
scale and measured rather than assumed in Phase 7. Production evolution to
Postgres is documented, not built.

---

## ADR-003 — Deterministic BM25 retrieval first; embeddings only if measured to help

**Decision.** SQLite FTS5/BM25 over page- and section-aware chunks, with metadata
filters (`authority_class`, `status`, `account_scope`) applied **before** ranking.
No embeddings in Phase 1.

**Rationale.** Six one-page documents with distinctive vocabulary
("cancellation fee", "service credit", "first-response", "KI-208"). Lexical
search is very likely sufficient, is deterministic, adds no model latency or
cost, and is trivially inspectable — which matters more than recall here because
every answer must be citable.

**Revisit trigger.** If Phase 7 retrieval Recall@K on the golden set falls below
target, add embeddings + rerank behind the same tool interface and re-measure.
BM25 remains the fallback.

---

## ADR-004 — Source authority is metadata-driven, and the ranking is quoted, not invented

**Decision.** Every chunk carries `authority_class`; precedence is
`AGREEMENT` > `POLICY_CURRENT` > `PRODUCT_DOC` > `HISTORICAL`, with `DEPRECATED`
excluded from answer construction. The ranking is taken verbatim from Support
Policy v3 §1 (see `initial_rules.md` R1).

**Sub-decision — scoped override.** An agreement overrides only clauses it
addresses. The pack proves this is necessary in both directions: LumenWorks §2
*declines* to override cancellation terms, and LumenWorks §3 *raises* the credit
threshold so the agreement makes the customer **less** entitled than the default.
A naive "agreement wins wholesale" rule produces wrong money on both.

**Open question.** SOP v4 is not literally named in v3's precedence list. It is
classed `POLICY_CURRENT` alongside v3. The two never address the same subject in
this pack, so their relative order is never exercised — recorded so the inference
is visible rather than silent.

---

## ADR-005 — Snapshot time is the only clock

**Decision.** `2026-08-16 11:00 Asia/Kolkata`, parsed from the README sheet, is
injected as the reference time for all dataset reasoning. The machine clock is
never read on an answer path.

**Consequence.** Results are reproducible and the golden set stays valid
indefinitely. All workbook datetimes are naive and treated as Asia/Kolkata
(recorded assumption — no timezone column exists).

---

## ADR-006 — An un-happened pickup accrues delay from the snapshot

**Context.** `ORD-2002` has `pickup_actual_at = null`, a window that ended at
06:30, and `carrier_fault = true`. The SOP defines the delay as time "past the
end of the scheduled pickup window" but does not spell out the still-open case.

**Decision.** When `pickup_actual_at` is null, measure delay as
`snapshot − pickup_window_end` and label the result as *accruing*.

**Rationale.** The alternative — treating a pickup that never happened as
zero delay — would deny a credit precisely when the failure is worst.

**Status.** Assumption, surfaced in the response. Flagged here because it is an
inference, not quoted policy.

---

## ADR-007 — Business hours are configuration, and business-hour SLAs are `CONDITIONAL`

**Context.** This is the single largest gap in the pack. Most SLA targets are
expressed in "business hours" / "business days", none of which the pack defines,
and the snapshot falls on a **Sunday**. LumenWorks additionally has contractual
"no weekend or after-hours support coverage" with no coverage window given.

**Decision.**
1. A business calendar (working days, working hours, timezone) is **configuration**
   with a stated default, never a constant inside rule code.
2. Any SLA result that depends on it returns trust state `CONDITIONAL` with the
   assumption in the response `assumptions` array.
3. 24x7 targets (Enterprise P1 under v3, Northstar P1 under SRC-05) are computed
   exactly and may be `CONFIDENT`.

**Consequence.** Of the five open tickets, two get exact answers and three get
honest conditional ones. That split is a feature: the two exact answers happen to
be the two genuine breaches.

---

## ADR-008 — SLA *compliance* is not measurable; only deadline vs snapshot is

**Context.** The workbook has no `first_response_at` column.

**Decision.** The system computes the deadline and reports whether the snapshot
has passed it *with no recorded response*, and states that limitation in the
answer. It never claims the team failed to respond.

**Rationale.** Claiming a missed response from an absent column would be exactly
the confidently-incorrect failure mode the brief warns about.

---

## ADR-009 — Severity is derived and labelled as an inference

**Context.** No severity column exists; severity drives every SLA answer.

**Decision.** Classify `description` against Support Policy v3 §2 with the
matching definition text carried through as evidence. Severity is presented as a
derived classification with its justification, not as a looked-up fact.

**Trade-off.** Classification is the one place an LLM judgement enters a
numeric path. Mitigation: the classifier returns one of exactly three values
plus the matched clause; the arithmetic downstream is fully deterministic; and
all five pack tickets map to near-verbatim definition language, so the golden
set pins the expected labels.

---

## ADR-010 — Typed tools only; no model-generated SQL

**Decision.** Six tools: `search_documents`, `lookup_structured_data`,
`calculate_support_outcome`, `prepare_action`, `confirm_action`, `detect_issues`.
Each takes a Pydantic-validated argument model and receives the server-validated
auth context out-of-band from the conversation.

**Rationale.** A narrow surface is auditable and testable. Unrestricted SQL would
make authorization unenforceable below the model, violating an explicit brief
requirement.

---

## ADR-011 — Authorization is filter-before-query, enforced in the data layer

**Decision.** Account scope and field allowlists are applied inside the data
access layer, so an out-of-scope record is never loaded, never enters model
context, and never reaches a log. Denials are produced by the tool layer, not by
the model choosing to refuse. Role and scope come from server-validated context
and are not settable from conversation text.

**Consequence.** Cross-account aggregates are a distinct permission, because a
count over rows the caller cannot read is still a leak. Derived values are
checked too: `restricted_support` cannot read `shipment_fee_inr`, so it also
cannot receive a 10%-of-fee credit figure that reconstructs it.

---

## ADR-012 — Two-phase actions with hash, expiry, and idempotency

**Decision.** `prepare_action` is non-mutating and returns `action_id`, target,
proposed changes, rationale, evidence, risk, `payload_hash`, `expires_at`.
`confirm_action` re-checks authorization, ownership, expiry, payload hash,
evidence validity, current state, and prior execution before mutating.
Execution is idempotent on `action_id`.

**Rationale.** SOP v4 §3 already requires verification before a state-changing
action when data conflicts, so this is a business requirement, not just hygiene.

---

## ADR-013 — Deterministic detection; the LLM only narrates

**Decision.** Operations Radar rules are pure Python over the snapshot. Every
alert carries `alert_id`, severity, reason, time window, threshold, count,
representative records, affected accounts, linked evidence, recommended action.
The LLM may summarise an alert; it may never produce a count or a causal claim.

**Honesty constraint.** With 17 rows, blast radius must not be overstated: the
`KI-208` recurrence is two tickets on **one** account and must say so.

---

## ADR-014 — Provider-abstracted LLM with bounded budgets

**Decision.** One `LLMProvider` interface; provider, model, timeouts, max output
tokens, context budget, temperature, retries, and pricing metadata all live in
config. Token counts and estimated cost are recorded per request from day one.

**Rationale.** Phase 7 needs to compare models on latency and cost without
touching agent code, and cost cannot be reported honestly if it is not
instrumented from the start.

---

## ADR-015 — Source files stay out of the public repository

**Decision.** `D:\AI-Projects\parcelpilot-assessment` is never copied into the repo.
`data/source_manifest.json` carries checksums and metadata so ingestion is
verifiable and reproducible without redistributing customer material. `.gitignore`
blocks the file types defensively.

**Consequence.** README must document how a reviewer supplies their own copy of
the pack via `PARCELPILOT_SOURCE_DIR`.

---

## ADR-016 - Domain services own outcomes; policy owns applicability only

**Context.** Phase 2 needed to encode which agreement clause overrides which
default rule (docs/initial_rules.md R1.1: an agreement's authority is scoped
to the clauses it actually addresses, never blanket).

**Decision.** Split into two layers with a hard boundary. `app/policy/
applicability.py` answers exactly one question - for a (topic, account),
which source's clause governs - via a small explicit registry
(`AGREEMENT_OVERRIDES`) where every entry cites the agreement section it
restates. `app/domain/*.py` owns what the winning clause actually computes,
via a `{source_id: rule_fn}` dispatch table per topic.

**Rationale.** Conflating "who wins" with "what they say" is exactly how a
system ends up treating agreement authority as blanket - the two questions
have genuinely different failure modes (a stale/expired agreement term vs.
a wrong fee formula) and belong in different, independently testable places.

**Consequence.** Adding a new agreement clause is a two-part change (a
registry entry in policy/, a rule function in the relevant domain module) by
design - the friction is intentional, so it can never happen by only editing
one side.

---

## ADR-017 - LLM gateway: one Protocol, provider swap never touches call sites

**Decision.** `app/llm/base.py` defines `LLMProvider` as a `Protocol`
(`complete(request, context) -> response`), not an ABC or a concrete client
type. `MockProvider` (deterministic, no network) and `AnthropicProvider`
(lazy-imports `anthropic`, only present via the optional `llm` extra) both
satisfy it. No business or domain module imports an SDK.

**Rationale.** Phase 2 has no agent yet and no API key was available while
building it (docs/_internal/phase-reports/phase-02.md), so the gateway had
to be fully exercisable without either. A `Protocol` costs nothing at import
time (unlike an ABC requiring the concrete class hierarchy to exist), and
`MockProvider` makes cost/token accounting and the DeepEval harness testable
in CI with zero secrets and zero network calls.

**Trade-off.** `AnthropicProvider` is construction-tested only, not
call-tested against a live API - documented plainly in its docstring and in
the test that exercises it, rather than claimed as verified.

---

## ADR-018 - Pricing is data, not code

**Decision.** `app/llm/pricing.json` holds USD-per-million-token rates;
`PricingTable` only computes `tokens / 1e6 * rate`. No model name or price
appears in Python logic.

**Consequence.** Updating a rate, or adding a model, never requires a code
change or a new test beyond a JSON edit - and an unpriced model fails loudly
(`KeyError`) rather than silently reporting zero cost.

---

## ADR-019 - Tracing interface now, no monitoring platform yet

**Decision.** `app/observability/tracing.py` wraps `opentelemetry-api`
(API package only, no SDK/exporter) behind `RequestContext` +
`span()`. With no `TracerProvider` configured, every span is a documented
OTel no-op - real, standard behavior, not a stub this codebase invented.

**Rationale.** The ask was "make every future request traceable," not "stand
up a monitoring platform" (explicitly out of scope this phase). Using the
real OTel API now means a later phase turns tracing on by configuring one
exporter, with zero call-site changes - versus writing a bespoke tracing
interface now and swapping it for OTel later, which would touch every call
site twice.

---

## ADR-020 - MLflow tracking store: sqlite, not the plain filesystem backend

**Context.** Phase 2 s16 asked for "a lightweight local tracking
configuration," and the MLflow docs/most tutorials default to
`file:./mlruns`.

**Decision.** `app/evaluation/mlflow_tracking.py` defaults to
`sqlite:///build/mlflow.db` instead.

**Rationale.** Discovered by actually running it, not by reading docs first:
MLflow 3.x raises on the plain filesystem backend by default -
`the filesystem tracking backend ... is in maintenance mode ... Please
migrate to a database backend`. A file-based SQLite database is still fully
local, still gitignored, still zero-infrastructure - it is what "lightweight
local tracking" means in the version actually installed (`mlflow==3.15.1`),
not what it meant when file-backed tracking was still the default.
`scripts/run_retrieval_eval.py --mlflow` and
`scripts/run_deepeval_baseline.py --mlflow` both log real, queryable runs
against it - verified by querying the run back, not just by a write that
did not error.

---

## ADR-021 - Anthropic retries: classify by exception type, not blanket except

**Context.** Phase 2's `AnthropicProvider` retried on any exception,
including permanent failures (auth, malformed request, invalid model) that
retrying cannot fix - Phase 3 pre-flight 2.4 flagged this.

**Decision.** `app/llm/anthropic_provider.py` retries only
`APIConnectionError`/`APITimeoutError`/`RateLimitError`/
`InternalServerError`/`OverloadedError`/`ServiceUnavailableError` - a
closed, named list. Everything else (including any future/unknown
exception type) raises immediately. Backoff is exponential with full
jitter (`uniform(0, min(max_delay, base * 2**attempt))`), bounded by
`request.max_retries`, and the realized retry count is recorded on
`LLMResponse.retries`.

**Rationale, checked rather than assumed.** The SDK exposes a
`RetryableError` marker class; inspecting `__mro__` on every relevant
exception (`anthropic==1.0.0`) showed none of them actually inherit it, so
it is not usable for this classification - a plausible-looking shortcut
that turned out not to work, caught by checking rather than trusting the
name.

**Testing without a network call.** `tests/unit/test_anthropic_retry.py`
monkeypatches `_client.messages.create` to raise real SDK exception
instances (built from real `httpx2` - anthropic's vendored httpx fork -
`Request`/`Response` objects, not a duck-typed stand-in that might not
satisfy the exception's own `__init__`) on a scripted schedule, and
replaces `sleep_fn` with a recorder. 13 tests run in 0.14s and prove: every
transient type retries and eventually succeeds; every permanent type
raises on the first attempt with zero retries and zero backoff calls;
retries exhaust and re-raise the transient error past `max_retries`; and
backoff delays stay within the configured bounds.

---

## ADR-022 - Rules are declarative data, and the registries are injectable

**Context.** Building a fixture-backed public CI tier (Phase 3 pre-flight
2.1) meant proving `app/domain/*.py` works for an account/agreement pair
that has never existed in the real pack. It didn't, at first: `_FEE_RULES`
and `_CREDIT_RULES` were `{source_id: bespoke_python_function}` dispatch
tables hardcoded to the real `SRC-03`/`SRC-05`/`SRC-06` - not a per-
customer branch (2.6's literal example), but the same coupling one level
more abstract, and it would `KeyError` on any fixture source_id.

**Decision.** Rule *shapes* are now data: `CancellationFeeRule` (`kind:
"threshold_fee" | "full_waiver"`, with parameters) and `ServiceCreditRule`
(`kind: "percentage_with_cap" | "fixed_amount"`, with parameters) replace
the bespoke functions. `resolve_applicability()`, `evaluate_cancellation()`,
`evaluate_service_credit()`, and `calculate_sla()` all gained `overrides`/
`defaults`/`fee_rules`/`credit_rules` keyword arguments defaulting to the
real registries - production call sites never pass them; tests inject
`tests/fixtures/seed_fixture_db.py`'s fabricated registries instead.

**Verification, not assertion.** Every fixture number
(`tests/fixture_backed/test_domain_rules.py`,
`test_sla_and_severity.py`) was computed by actually running the real
domain functions against the fixture data before being written into an
assertion - not derived on paper and hoped to match. Re-ran the existing
160 real-pack tests after the refactor (same numbers: `ORD-1001` fee
`0.0`, `ORD-2001` fee `250.0`, `ORD-2002` credit `300.0`) to confirm the
refactor changed nothing about real-pack behavior.

**Consequence.** Adding a new real agreement is now a two-part *data*
change (a `AgreementOverride` entry, a rule-shape entry) with zero new
Python logic if the new agreement's rule fits an existing shape - and a
new rule shape (a third `kind`) is the one case that still requires a
code change, which is correct: that is a genuinely new kind of clause, not
a new customer.
