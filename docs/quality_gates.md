# Quality Gates

Phase 2 s20's rule: no single aggregate score is the release gate, and no
threshold is invented before a baseline exists to invent it from. This
document separates what is measured and enforced today from what is
pending a real baseline.

## Enforced today (deterministic, run on every push via `.github/workflows/ci.yml`)

| Gate | Target | Measured value | Evidence |
|---|---|---|---|
| Unauthorized access | 0 | **0** | `tests/fixture_backed/test_security.py`, `test_authorization.py`, `test_document_prompt_injection.py`, `test_action_security.py`: cross-account/injection regression tests across question-answering and the action workflow, all currently pass, in the always-runs public tier |
| Unsafe actions | 0 | **0** | `tests/fixture_backed/test_action_security.py`: unauthorized/cross-account prepare, expired/replayed/duplicate confirmation, changed target state, and a manipulated payload all fail safely with a structured error code; duplicate execution is idempotent, never a repeated effect; the agent orchestrator has no code path to `confirm_action`/`execute_action` at all (verified structurally) |
| Deterministic calculation regressions | 0 | **0** | `tests/evaluation/test_golden_domain_cases.py`: 10/10 golden cases with domain-computable facts match the real engine's output |
| Invalid required citations | 0 | **0** | `app/agent/citations.py::validate_citations` runs on every composed answer; an invalid marker gets one bounded repair attempt, then a controlled `evidence_validation_failed` result if still invalid - never silently shown as valid - `tests/fixture_backed/test_citation_repair.py` |
| Lint / type errors | 0 | **0** | `ruff check`, `pyright` - both clean as of this phase |
| Full test suite | 100% pass (excluding source-pack-gated skips) | **265/265** locally with the pack available; **155 passed, 110 skipped, 0 failed** with no pack | `pytest -q` |

A failure in any of these blocks CI (see `.github/workflows/ci.yml`).

## Pending a real baseline

| Gate | Status | Why |
|---|---|---|
| Faithfulness threshold | **Not set** | `scripts/run_deepeval_baseline.py` ran against the golden set; MockProvider cannot produce the structured judge output DeepEval's `FaithfulnessMetric` requires (0 of 16 cases scored - see `docs/deepeval_baseline.md`). No real number exists to set a threshold from. |
| Contextual relevancy threshold | **Not set** | Same blocker - no `ANTHROPIC_API_KEY` was available while building this phase. |
| Agent task completion threshold | **Not set** | `scripts/run_agent_trajectory_eval.py`: `TaskCompletionMetric` requires the same structured judge output as above (0 of 19 cases scored - see `docs/agent_trajectory_evaluation.md`). No real number exists to set a threshold from. |
| Tool correctness / status match | **Measured, no threshold set yet** | These need no judge, so real numbers exist today (mean tool correctness 0.84, status match 0.88 of 17 checkable cases - see `docs/agent_trajectory_evaluation.md`). Not yet promoted to a hard gate: the 2 remaining status mismatches (GC-015, GC-016) are a documented, unfixed limitation - retrieved evidence scores strongly but doesn't contain the specific fact asked for (semantic, not lexical, insufficiency) - not flaky measurement, but a threshold set now would either mask it or be set arbitrarily low. |

**Rule going forward:** the first time `scripts/run_deepeval_baseline.py
--provider anthropic` produces real scores, those scores become the
baseline recorded in this document, and only then does a threshold get
set - never the reverse.
