# Quality Gates

Phase 2 s20's rule: no single aggregate score is the release gate, and no
threshold is invented before a baseline exists to invent it from. This
document separates what is measured and enforced today from what is
pending a real baseline.

## Enforced today (deterministic, run on every push via `.github/workflows/ci.yml`)

| Gate | Target | Measured value | Evidence |
|---|---|---|---|
| Unauthorized access | 0 | **0** | 6 `NotAuthorizedError` regression tests across `tests/integration/test_domain_*.py`, `test_agent_tools.py`, `test_structured_repository.py` - all currently pass |
| Deterministic calculation regressions | 0 | **0** | `tests/evaluation/test_golden_domain_cases.py`: 10/10 golden cases with domain-computable facts match the real engine's output |
| Lint / type errors | 0 | **0** | `ruff check`, `pyright` - both clean as of this phase |
| Full test suite | 100% pass (excluding source-pack-gated skips) | **140/140** locally with the pack available | `pytest -q` |

A failure in any of these blocks CI (see `.github/workflows/ci.yml`).

## Not yet applicable

| Gate | Status | Why |
|---|---|---|
| Unsafe actions = 0 | N/A | No action-execution engine exists yet - `prepare_action`/`confirm_action` are Phase 5. Nothing can be unsafe that cannot yet act. |
| Task completion threshold | N/A | No agent orchestration exists yet (Phase 3). There is no trajectory to score. |

## Pending a real baseline

| Gate | Status | Why |
|---|---|---|
| Faithfulness threshold | **Not set** | `scripts/run_deepeval_baseline.py` ran against the golden set; MockProvider cannot produce the structured judge output DeepEval's `FaithfulnessMetric` requires (0 of 16 cases scored - see `docs/deepeval_baseline.md`). No real number exists to set a threshold from. |
| Contextual relevancy threshold | **Not set** | Same blocker - no `ANTHROPIC_API_KEY` was available while building this phase. |
| Citation integrity (agent-level) | **Not set** | No agent produces a final cited answer yet. What *is* measured today is retrieval-evidence accuracy (`docs/retrieval_evaluation.md`: source hit rate 96%), which is a necessary but not sufficient precondition - an agent could still retrieve the right evidence and cite it wrong. |

**Rule going forward:** the first time `scripts/run_deepeval_baseline.py
--provider anthropic` produces real scores, those scores become the
baseline recorded in this document, and only then does a threshold get
set - never the reverse.
