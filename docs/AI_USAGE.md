# AI-Assisted Development (Phase 3)

Built with Claude (Anthropic) via Claude Code across Phases 1-3, including
this phase's agent orchestration layer. This note covers what Claude Code
actually did, in the specific and verifiable sense: which commands were
run, what they found, and what changed as a result - not a general
disclosure.

## What was AI-assisted

Implementation of `app/agent/` (13 modules), `app/llm/gateway.py`,
`app/evaluation/adapters/agent_trajectory_adapter.py`, all associated
tests (orchestrator, security, fixture-backed, gateway, evaluation
harness), the two new scripts (`run_agent_cli.py`,
`run_agent_trajectory_eval.py`), and this documentation set.

## What was verified, not assumed

Every claim of "done" in this phase's docs and the private phase report
corresponds to a command that was actually run:

- Every new module was checked with `ruff check` and `pyright` after
  writing it, not just at the end.
- Every new test file was run in isolation before being folded into the
  full suite.
- The full suite was run repeatedly (215 passed with the real pack; 98
  passed / 110 skipped / 0 failed with none) to catch regressions as work
  progressed, not once at the end.
- `scripts/run_agent_cli.py` was run against the real database with real
  questions, not just unit-tested, before being called working.
- `scripts/run_agent_trajectory_eval.py` was run against the real golden
  dataset twice - once before and once after a mid-phase bug fix - so the
  reported improvement (status-match rate 0.71 -> 0.82) is a measured
  delta, not a claimed one.

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

One near-miss was also caught and corrected before being committed: a new
test file was written to a path that (unnoticed at first) already held a
committed test file from an earlier phase, silently overwriting it in the
working tree. Caught by running `git status` before wrapping up and
noticing the file was flagged as modified rather than new. The original
tests were restored under an accurately renamed file, and the new tests
moved to their own file - both verified passing afterward. No commit had
been made, so nothing was actually lost, but the near-miss itself is
recorded because it's the honest account of what happened.

## What was not done

No live LLM call was made this phase - no `ANTHROPIC_API_KEY` was
available. Every "quality" number in this phase's evaluation report that
would normally need a real model (RAG faithfulness/relevancy, agent task
completion) is explicitly reported as harness-verified-but-unscored, not
approximated or estimated by Claude on the model's behalf.

## Human role

Harsh Tomar directed scope, deadline, and architectural constraints (the
full Phase 3 specification), reviewed and can inspect every diff before
any commit (none were made without being asked in this phase), and made
the final call on what shipped versus what's recorded as a known
limitation for Phase 4.
