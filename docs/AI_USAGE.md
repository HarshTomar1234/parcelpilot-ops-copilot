# AI-Assisted Development

Built with Claude (Anthropic) via Claude Code across all phases: agent
orchestration (Phase 3), agent hardening plus the state-changing action
workflow (Phase 4), Operations Radar deterministic detection (Phase 5),
the FastAPI/staff-UI product surface plus deployment (Phase 6), and a
final red-team/release-validation pass (`tests/red_team/`, 114
adversarial tests, plus manual attacks against a live Docker container).
This note covers what Claude Code actually did, in the specific and
verifiable sense: which commands were run, what they found, and what
changed as a result - not a general disclosure.

## What was AI-assisted

Phase 3: implementation of `app/agent/` (13 modules), `app/llm/gateway.py`,
`app/evaluation/adapters/agent_trajectory_adapter.py`, all associated
tests, `run_agent_cli.py`, `run_agent_trajectory_eval.py`.

Phase 4: budget enforcement, tool timeout/retry, provider-failure
classification, citation bounded-repair, a lexical relevance threshold
for retrieval, an ambiguous-entity clarification gate, retrieved-document
prompt-injection tests, the full `app/actions/` state-changing action
workflow (prepare/confirm/execute, audit trail, security tests), and this
documentation set.

Phase 5: `app/detection/` (deterministic detection rules, fingerprinting,
service layer, optional LLM summary), the `detect_issues` agent tool,
and the associated test suites.

Phase 6: `app/api/` (FastAPI routes, dependency injection, middleware,
error handling), the static staff UI (`app/api/static/`), `Dockerfile` /
`docker-entrypoint.sh`, `scripts/run_api_load_test.py`, the API test
suite, and this phase's documentation updates.

Final red-team phase: `tests/red_team/` (10 files, 114 executable
adversarial tests), the atomic compare-and-swap fix in
`app/actions/store.py`/`app/actions/workflow.py`, the
`docker-entrypoint.sh` crash-on-bad-secret fix, `docs/red_team_report.md`,
and this phase's evaluation/performance/README updates.

Final release hardening: `app/agent/evidence_sufficiency.py` (the F4
fix), the `GET /api/actions/{id}` enumeration fix (F5), regression tests
for both, and the final consolidated evaluation/red-team report updates.

## What was verified, not assumed

Every claim of "done" in this phase's docs and the private phase report
corresponds to a command that was actually run:

- Every new module was checked with `ruff check` and `pyright` after
  writing it, not just at the end.
- Every new test file was run in isolation before being folded into the
  full suite.
- The full suite was run repeatedly through every phase (453 passed with
  the real pack; 339 passed / 114 skipped / 0 failed with none, as of
  final release hardening) to catch regressions as work progressed, not
  once at the end.
- The evidence-sufficiency fix (F4) was evaluated before and after with
  the real golden dataset, not assumed safe: agent status-match rate
  0.88 -> 0.94, Recall@3/Recall@5 unchanged at 1.0/1.0 - confirming
  recall for genuinely supported questions was not reduced, the explicit
  constraint the phase spec set for this fix.
- The confirm/execute race-condition fix (below) was verified three
  separate ways before being called done: a deterministic direct-function
  test, an HTTP-level `TestClient` test under real thread concurrency,
  and a manual 20-concurrent-request attack against a live, rebuilt
  Docker container - not just one of the three.
- The Docker image was actually built and run this phase (not just
  authored) - `docker build`, then `docker run` against the real,
  ingested database via all three documented delivery mechanisms (file
  mount, `PARCELPILOT_DB_B64_FILE`, `PARCELPILOT_DB_B64`) - and the
  concurrency smoke test was run against that live container, not
  `TestClient`.
- `scripts/run_agent_cli.py` was run against the real database with real
  questions, not just unit-tested, before being called working.
- `scripts/run_agent_trajectory_eval.py` was run against the real golden
  dataset four times across both phases - each time a fix was made, not
  once at the end - so the reported improvement (status-match rate
  0.71 -> 0.82 -> a regression to fix -> 0.88) is a measured history, not
  a claimed one.

## What Claude Code found, not just fixed

Two real bugs were found by *running* the code against real and fabricated
data, not by inspection:

1. Entity ID resolution was hardcoded to the real pack's `ORD-`/`TKT-`/
   `ACCT-` ID prefixes. Running the agent against the project's own
   fabricated fixture corpus (which deliberately uses different prefixes
   to test exactly this) showed every fixture question routing to the
   wrong intent. Fixed by generalizing to ID *shape*, not prefix.
2. The orchestrator conflated an operational escalation flag with an
   epistemic trust downgrade, forcing confidently-answerable SLA-breach
   questions into an `escalated` status that contradicted the golden
   dataset's own expectations. Found by running the real golden cases
   through the real agent and reading the resulting score, not by
   guessing it might be wrong.

One near-miss was also caught and corrected before being committed (Phase
3): a new test file was written to a path that (unnoticed at first)
already held a committed test file from an earlier phase, silently
overwriting it in the working tree. Caught by running `git status` before
wrapping up and noticing the file was flagged as modified rather than
new. The original tests were restored under an accurately renamed file,
and the new tests moved to their own file - both verified passing
afterward.

Phase 4 found one more, this time a genuine self-introduced regression,
not a pre-existing bug: adding the ambiguous-entity clarification gate
(fixing GC-002) broke a different, already-passing case (GC-028, a
bulk/aggregate query) by treating its unrestricted admin scope as
"ambiguous" the same way it treats a scoped agent's multi-account access.
Caught by re-running `scripts/run_agent_trajectory_eval.py` immediately
after the fix rather than assuming it only helped - the status-match rate
did rise (0.71 -> 0.82 in the earlier fix), but per-case inspection showed
GC-028 had flipped from correct to incorrect. Fixed with a narrow
aggregate-language carve-out, re-verified with a third eval run
(0.82 -> 0.88, both mismatches gone that a keyword rule could realistically
fix). The lesson generalizes: an aggregate score improving is not proof
that nothing regressed - the per-case table is what actually shows that.

Phase 6 found a real concurrency bug via its own load-test script, not
code review: the first run of `scripts/run_api_load_test.py` against a
live Docker container produced errors at concurrency 5 and 10
(`sqlite3.ProgrammingError: SQLite objects created in a thread can only
be used in that same thread`) - FastAPI's threadpool doesn't guarantee a
sync dependency's setup and the route handler share one OS thread. Fixed
with `check_same_thread=False` in `app/db/connection.py::connect()`;
re-running the same test confirmed 0 errors at every level. The same
session's manual container testing also found that mounting the database
read-only breaks `prepare_escalation`'s audit-row write - not a code bug,
but a real deployment-configuration trap now documented explicitly in
the README and `docker-entrypoint.sh` rather than left for an operator to
discover the same way.

The final red-team phase found two real bugs by actually attacking a
live system, not by inspection - full writeup in
[`docs/red_team_report.md`](red_team_report.md):

1. A genuine confirm/execute race condition: `app/actions/workflow.py`
   checked an action's status in Python, then wrote unconditionally -
   under real concurrent HTTP load, 4 of 20 concurrent `confirm_action`
   calls on the *same* action all reported success. Fixed with an atomic
   `UPDATE ... WHERE status = expected` compare-and-swap
   (`app/actions/store.py::save_action_if_status`), re-verified at
   exactly 1 of 20 succeeding, on both the test suite and a live
   container.
2. `docker-entrypoint.sh` crashed the entire container (no `/health`, no
   `/ready`, nothing) when given an invalid base64 secret - the opposite
   of the phase's own "no startup crash if only readiness is unavailable"
   requirement. Found by deliberately supplying a malformed secret to a
   real container and getting `curl: (7) Failed to connect` instead of a
   graceful `not_ready`. Fixed by making the decode step fail soft
   (log a warning, continue starting) instead of exiting the whole
   script.

A third, lower-severity gap was found and left as a documented, accepted
trade-off rather than "fixed" by a redesign: `GET /api/actions/{id}`
returns 403 for an action that exists but belongs to someone else, versus
404 for one that never existed - the ownership check reads the record
before deciding, so its bare existence (not its contents) is technically
distinguishable. Recorded as a known limitation
(`docs/red_team_report.md` F5), consistent with the instruction to keep
the existing single-row audit design unless a test demonstrates it's
unsafe, not to redesign preemptively.

## What was not done

No live LLM call was made this phase - no `ANTHROPIC_API_KEY` was
available. Every "quality" number in this phase's evaluation report that
would normally need a real model (RAG faithfulness/relevancy, agent task
completion) is explicitly reported as harness-verified-but-unscored, not
approximated or estimated by Claude on the model's behalf.

## Human role

Harsh Tomar directed scope, deadline, and architectural constraints (the
full phase specifications), reviewed and can inspect every diff before
any commit, and made the final call on what shipped versus what's
recorded as a known limitation for the next phase.
