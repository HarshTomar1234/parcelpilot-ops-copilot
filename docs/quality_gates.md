# Quality Gates

Phase 2 s20's rule: no single aggregate score is the release gate, and no
threshold is invented before a baseline exists to invent it from. This
document separates what is measured and enforced today from what is
pending a real baseline.

## Enforced today (deterministic, run on every push via `.github/workflows/ci.yml`)

| Gate | Target | Measured value | Evidence |
|---|---|---|---|
| Unauthorized access | 0 | **0** | `tests/fixture_backed/test_security.py` + `test_authorization.py`: 9 + 4 authorization/cross-account regression tests, all currently pass, in the always-runs public tier |
| Unsafe actions | 0 | **0** | No action-execution capability exists yet (`prepare_action`/`confirm_action` are Phase 5) - nothing can be unsafe that cannot yet act |
| Deterministic calculation regressions | 0 | **0** | `tests/evaluation/test_golden_domain_cases.py`: 10/10 golden cases with domain-computable facts match the real engine's output |
| Invalid required citations | 0 | **0** | `app/agent/citations.py::validate_citations` runs on every composed answer; an invalid marker is stripped, never shown as valid - `tests/integration/test_agent_orchestrator.py` |
| Lint / type errors | 0 | **0** | `ruff check`, `pyright` - both clean as of this phase |
| Full test suite | 100% pass (excluding source-pack-gated skips) | **215/215** locally with the pack available; **105 passed, 110 skipped, 0 failed** with no pack | `pytest -q` |

A failure in any of these blocks CI (see `.github/workflows/ci.yml`).

## Pending a real baseline

| Gate | Status | Why |
|---|---|---|
| Faithfulness threshold | **Not set** | `scripts/run_deepeval_baseline.py` ran against the golden set; MockProvider cannot produce the structured judge output DeepEval's `FaithfulnessMetric` requires (0 of 16 cases scored - see `docs/deepeval_baseline.md`). No real number exists to set a threshold from. |
| Contextual relevancy threshold | **Not set** | Same blocker - no `ANTHROPIC_API_KEY` was available while building this phase. |
| Agent task completion threshold | **Not set** | `scripts/run_agent_trajectory_eval.py`: `TaskCompletionMetric` requires the same structured judge output as above (0 of 19 cases scored - see `docs/agent_trajectory_evaluation.md`). No real number exists to set a threshold from. |
| Tool correctness / status match | **Measured, no threshold set yet** | These need no judge, so real numbers exist today (mean tool correctness 0.89, status match 0.82 of 17 checkable cases - see `docs/agent_trajectory_evaluation.md`). Not yet promoted to a hard gate: the 3 remaining status mismatches are documented, unfixed limitations (retrieval relevance, ambiguity clarification), not flaky measurement - a threshold set now would either mask them or be set arbitrarily low. |

**Rule going forward:** the first time `scripts/run_deepeval_baseline.py
--provider anthropic` produces real scores, those scores become the
baseline recorded in this document, and only then does a threshold get
set - never the reverse.
