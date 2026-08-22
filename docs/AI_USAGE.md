# AI-Assisted Development

Built with Claude (Anthropic) via Claude Code across all phases,
including agent orchestration (Phase 3) and agent hardening plus the
state-changing action workflow (Phase 4). This note covers what Claude
Code actually did, in the specific and verifiable sense: which commands
were run, what they found, and what changed as a result - not a general
disclosure.

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

## What was verified, not assumed

Every claim of "done" in this phase's docs and the private phase report
corresponds to a command that was actually run:

- Every new module was checked with `ruff check` and `pyright` after
  writing it, not just at the end.
- Every new test file was run in isolation before being folded into the
  full suite.
- The full suite was run repeatedly (265 passed with the real pack; 155
  passed / 110 skipped / 0 failed with none) to catch regressions as work
  progressed, not once at the end.
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
