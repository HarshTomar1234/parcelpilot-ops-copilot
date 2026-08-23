# Red Team & Release Validation Report

Final adversarial validation phase before release. Every finding below
comes from an executable test in `tests/red_team/` or a manual attack
against a real, running Docker container - never from reading the code
and assuming it's safe.

## Scope

The deployed HTTP application (`app/api/`), the bounded agent
(`app/agent/`), Operations Radar (`app/detection/`), the action workflow
(`app/actions/`), and the Docker deployment path. Out of scope: new
product features (none added this phase - every code change here is a
fix for a demonstrated failure).

## Threat model

The frontend, the prompt, retrieved documents, structured input, HTTP
headers, action IDs, and tool arguments are all treated as attacker-
controlled. The backend/domain authorization and safety boundaries
(`AuthContext` account-scope filtering inside
`app/structured_data/repository.py`, the deterministic action-eligibility
and state-machine rules in `app/actions/workflow.py`, the trust gate in
`app/agent/trust_gate.py`) are the only things trusted to hold, and this
phase exists to prove they actually do under adversarial input rather
than assuming it from their design.

The `X-Demo-User` identity mechanism is explicitly **a testing/deployment
stand-in for a production identity provider, not itself a security
boundary** - it lets a client select which server-owned `AuthContext` to
act as; the account-scope enforcement beneath it is the real, independent
boundary this report validates.

## Attack classes and tests executed

| Class | File | Tests |
|---|---|---|
| Demo identity spoofing | `test_identity_spoofing.py` | 6 |
| API authorization | `test_api_authorization.py` | 20 |
| Action attack matrix (prepare/confirm/execute) | `test_action_attacks.py` | 21 |
| Prompt injection (question + retrieved document) | `test_prompt_injection.py` | 4 |
| Tool argument injection | `test_tool_injection.py` | 11 |
| Information leakage / enumeration / aggregate leakage | `test_information_leakage.py` | 9 |
| Invalid input / resource abuse | `test_invalid_input.py` | 16 |
| Deployment failure scenarios + provider failure injection | `test_deployment_failures.py` | 8 |
| Concurrency / race conditions | `test_concurrency.py` | 11 |
| Agent abuse + retrieval abuse | `test_agent_abuse.py` | 8 |
| **Total** | | **114** |

All 114 pass. Full project suite (including these, and the 8 new
`app/agent/evidence_sufficiency.py` unit tests from the F4 fix):
**453 passed, 0 failed** (real pack); fixture-backed + red-team tiers
never need the real pack or a live server.

Findings F4 and F5 below were originally opened as KNOWN LIMITATION in
this report's first pass; both were subsequently fixed in the final
release hardening phase and are recorded here as MITIGATED/FIXED, with
the original finding text preserved for the record.

## Findings

### F1 - Confirm/execute race condition (CRITICAL, MITIGATED)

- **Test:** `tests/red_team/test_concurrency.py` -
  `test_concurrent_save_action_if_status_lets_exactly_one_caller_win`,
  `test_http_concurrent_confirm_against_the_same_action_yields_exactly_one_success`,
  plus a manual attack against a live Docker container (20 concurrent
  `POST /api/actions/confirm` calls on one `PENDING_CONFIRMATION` action).
- **Expected behavior:** exactly one concurrent caller can transition an
  action's state; every other concurrent caller gets a safe, explicit
  failure.
- **Observed behavior (before fix):** `app/actions/workflow.py` read the
  action's status, checked it in Python, then wrote unconditionally
  (`save_action()`, no `WHERE status = ...` guard) - a classic
  time-of-check-to-time-of-use race. Live measurement against a real
  container: **4 of 20** concurrent `confirm_action` calls on the same
  action all returned `success: true`.
- **Resolution:** `app/actions/store.py::save_action_if_status()` -
  every state transition is now a single atomic
  `UPDATE actions SET ... WHERE action_id = ? AND status = ?`, checked
  via `cursor.rowcount`. `confirm_action`/`execute_action` in
  `app/actions/workflow.py` now use it; a lost race returns
  `error_code=wrong_state` (confirm) or the real, already-executed record
  (execute, preserving its documented idempotency). Re-measured after the
  fix: **exactly 1 of 20** concurrent confirms succeeds, on both the
  fixture-backed test and a live Docker container. `execute_action`'s
  idempotent contract (all callers see `success: true`) is preserved, but
  now backed by a real atomic transition rather than an accidentally-safe
  read-then-write.

### F2 - `docker-entrypoint.sh` crashes the whole container on a bad secret (HIGH, MITIGATED)

- **Test:** manual Docker attack (scenario E, phase spec s16) - a file
  mounted at the `PARCELPILOT_DB_B64_FILE` path containing invalid
  base64 content.
- **Expected behavior (phase spec s16):** "No startup crash if only
  readiness is unavailable."
- **Observed behavior (before fix):** the entrypoint ran under `set -eu`;
  `base64 -d` on invalid input exits non-zero, which killed the entire
  container before `uvicorn` ever started - `/health` and `/ready` were
  both unreachable (`curl` exit code 7, connection refused), not a
  graceful "not ready."
- **Resolution:** the decode step is now wrapped in an `if`/`else` (POSIX
  shells exempt an `if` condition from `set -e`'s exit-on-error), logs a
  `WARNING` to stderr, removes any partial output, and lets the app start
  regardless. Re-verified against a rebuilt image: `/health` → `200 ok`,
  `/ready` → `503 not_ready` with `database_file_present: false`, no
  crash, the warning visible in `docker logs`.

### F3 - Test fixture had the same thread-affinity bug as the app did before Phase 6's fix (MEDIUM, MITIGATED)

- **Test:** `tests/red_team/test_concurrency.py`'s HTTP-level tests,
  first run.
- **Expected behavior:** concurrent requests through the `TestClient`
  fixture behave like concurrent requests to a real server.
- **Observed behavior:** `tests/red_team/conftest.py` and
  `tests/fixture_backed/conftest.py`'s `client` fixture both opened their
  per-request SQLite connection with `sqlite3.connect(path)` directly
  (not through `app.db.connection.connect()`, which already carries the
  Phase 6 `check_same_thread=False` fix) - so any test exercising real
  thread concurrency against these fixtures hit the identical
  `sqlite3.ProgrammingError` the production code had before that fix,
  just in test infrastructure instead of the app.
- **Resolution:** both `_get_conn` overrides now pass
  `check_same_thread=False` explicitly, with a comment pointing at why.
  No production code changed - this was a test-fixture-only gap.

### F4 - Relevance floor doesn't fully filter every off-topic query (LOW, MITIGATED)

- **Test:** `tests/red_team/test_agent_abuse.py::test_irrelevant_query_never_gets_a_fabricated_confident_answer`,
  `tests/fixture_backed/test_evidence_sufficiency.py` (8 unit tests),
  `tests/integration/test_agent_orchestrator.py`, plus real-pack
  before/after evaluation runs.
- **Expected (per prior evaluation docs' own framing):** an off-topic
  query like "What is the weather today?" returns `insufficient_evidence`.
- **Observed (before fix):** against both the fixture corpus and the real
  pack, that exact question returned `status: completed`,
  `trust_state: CONDITIONAL` - `MIN_RELEVANCE_SCORE` let a coincidentally-
  scoring chunk through on a small corpus, rather than rejecting it.
- **Resolution:** `app/agent/evidence_sufficiency.py` - a deterministic,
  generic gate applied only to the document-search-only path (no domain
  calculation grounding an answer already). Four signals: the existing
  relevance floor, a score margin below it, meaningful query-token
  overlap checked across every returned chunk (not just the top-scoring
  one), and a corroborating-chunk-count requirement for a strong score
  with no overlap. No keyword list, no example-specific special case.
  Verified against the required test matrix (supported policy/order/SLA
  questions still pass on real data; obviously unrelated, weakly-related,
  and coincidentally-overlapping questions now correctly return
  `insufficient_evidence`) and live against a rebuilt container. Real
  before/after evaluation: agent status-match rate 0.88 -> 0.94 (golden
  case GC-015 fixed), Recall@3/Recall@5 unchanged at 1.0/1.0 - recall for
  genuinely supported queries was not reduced.
- **Residual scope:** a harder, still-open problem - *semantic
  sufficiency* (retrieved text that is topically strong and lexically
  overlapping but doesn't contain the specific fact asked, golden case
  GC-016) - is explicitly not solved by this fix and not claimed to be.
  A lexical/score-based gate cannot resolve deep semantic mismatch by
  construction; see `docs/evaluation_report.md`.

### F5 - Action existence was technically observable via 403-vs-404 for a non-owner (INFO, MITIGATED)

- **Test:** `tests/red_team/test_information_leakage.py::test_another_users_action_is_not_distinguishable_from_a_nonexistent_one`,
  `tests/fixture_backed/test_api_actions.py::test_get_action_denies_a_non_owner_non_admin_caller`,
  plus a live verification against a rebuilt container.
- **Expected:** enumeration cannot distinguish "this action never
  existed" from "it exists but you can't see it."
- **Observed (before fix):** `GET /api/actions/{id}` returned `403` for
  an action that exists but belongs to someone else, versus `404` for one
  that never existed - the ownership check read the record before
  deciding, so existence was technically distinguishable from a
  truly-unknown ID.
- **Resolution:** `app/api/routes/actions.py::_get_owned_action_or_404`
  - `GET /api/actions/{id}` now returns the identical-shaped 404 for both
  "never existed" and "exists but isn't yours"; owner and admin still get
  `200`. Verified live: nonexistent action -> 404, another user's real
  action -> 404 (same generic `"no action <id>"` detail shape, no ticket/
  reason/evidence leaked), owner -> 200, admin -> 200.
- **Deliberately unchanged:** `POST /api/actions/execute` keeps a
  distinct `403` for a non-owner - the phase spec scoped this fix to
  enumeration via `GET`, and a mutating-action denial is meaningfully
  different from a passive read (the caller reaching `execute` already
  has the action_id from their own prepare/confirm flow). Not a
  redesign of the Phase 4 action-store API, per the standing instruction
  to keep the existing single-row audit design unless a test demonstrates
  it's unsafe.

## Severity summary

| Finding | Severity | Status |
|---|---|---|
| F1 - confirm/execute race condition | CRITICAL | MITIGATED |
| F2 - entrypoint crash on bad secret | HIGH | MITIGATED |
| F3 - test-fixture thread-affinity gap | MEDIUM | MITIGATED |
| F4 - relevance floor incomplete on off-topic queries | LOW | MITIGATED |
| F5 - action existence observable via 403/404 (GET only) | INFO | MITIGATED |

## What passed outright (PASS, no finding)

- **Identity spoofing:** switching `X-Demo-User` only ever changes which
  server-configured `AuthContext` is used; account-scope enforcement
  beneath it holds regardless of which identity is selected, including
  for chat, radar, and actions.
- **API authorization:** no request schema (`ChatRequest`, `RadarRequest`,
  action bodies) accepts a role/account_scope field at all - unknown
  fields are silently dropped by pydantic, never processed. SQL-like
  content in any field is treated as inert text; the corpus survives.
- **Action attack matrix:** every prepare/confirm/execute attack (wrong
  user, wrong hash, expired, already-confirmed, already-executed,
  nonexistent, altered target state, cross-account) fails with a specific,
  correct `error_code` - never a silent success, never a raw exception.
- **Prompt injection (question + document):** a worst-case "compliant"
  fake provider that actively tries to obey embedded instructions cannot
  add a tool call, change `trust_state`, leak a fabricated citation, or
  widen authorization - the plan is built deterministically before any
  LLM call, and the citation validator rejects markers that don't resolve
  to a real `EvidenceRef`.
- **Tool injection:** every tool function raises the correct typed error
  (`NotAuthorizedError`, `UnknownEntityError`) for malicious/mismatched
  arguments; no raw SQL path exists to attack in the first place.
- **Information leakage:** no response body (403/404/422/500/`/ready`)
  ever contains a stack trace, a filesystem path, a database path, or an
  env var value - verified by direct string search on real response
  bodies, not by reading the handler source.
- **Aggregate leakage (Operations Radar):** a scoped caller's
  `recurring_issue` alert only ever reflects their own visible tickets;
  `grouped_by_account` never introduces an account outside scope.
- **Invalid input:** every oversized/malformed/wrong-typed field is a
  clean `422`, never a crash; 30 rapid `/health` calls never destabilize
  the process.
- **Deployment failures (A, B, D, F, G):** valid DB, missing DB,
  read-only DB (action writes fail explicitly; reads still work),
  missing/empty config all behave exactly as specified - `/health` stays
  up, `/ready` reports the real state honestly, never fabricated data.
- **Agent/retrieval abuse:** every adversarial question stays within
  `DEFAULT_BUDGET` (≤6 tool calls, ≤2 LLM calls, <30s, ≤$0.50); no
  question ever reaches `confirm_action`/`execute_action`; deprecated
  source language never overrides the current policy in a conflict.

## Residual risks

- The evidence-sufficiency gate (F4, fixed) is a lexical/score-based
  heuristic, not a semantic-understanding system - it closes the
  zero-overlap/coincidental-match failure mode by construction, but a
  topically-adjacent, factually-wrong match with real (if partial) token
  overlap can still pass (golden case GC-016, unchanged, documented as an
  open limitation, not claimed fixed).
- `POST /api/actions/execute` still distinguishes a non-owner (403) from
  a nonexistent action (404) - a deliberate scope decision (F5), not an
  oversight; only `GET /api/actions/{id}` was normalized.
- No live LLM has been exercised this phase either (no
  `ANTHROPIC_API_KEY` in this environment) - retry/fallback classification
  is unit-tested against real SDK exception *types*, not a live provider
  outage.
- SQLite remains single-writer with one connection per request under real
  concurrency - the CAS fix (F1) makes state transitions *correct* under
  concurrency, not *fast*; `docs/performance_report.md`'s concurrency
  numbers still show real latency growth at 10 concurrent requests.
- `tests/red_team/test_deployment_failures.py` simulates scenarios B-D,
  F-G, and the corrupt/invalid-base64-decode *outcome* directly against
  the running app (fast, always-runs-in-CI); scenarios C and E were also
  independently verified against a real, rebuilt Docker container this
  phase (not simulated) - both are recorded above as real findings (F2),
  not assumed safe from the pytest layer alone.
