# Fixture-backed tests

Everything in this directory runs against `tests/fixtures/seed_fixture_db.py`
- an entirely fabricated, version-controlled dataset (fake companies, fake
account/order/ticket IDs, fake dates and thresholds) that exercises the same
code paths and rule *shapes* as the real assessment pack, without being
derived from or resembling it in any identifying way.

**This is the public, always-runs CI tier** (Phase 3 pre-flight 2.1). It
never needs `PARCELPILOT_SOURCE_DIR` and never skips.

## What this is not

- **Not "retrieval evaluation."** That term is reserved for
  `scripts/run_retrieval_eval.py` against the real pack -
  `docs/retrieval_evaluation.md`.
- **Not "domain regression" in the golden-case sense.** That term is
  reserved for `tests/evaluation/test_golden_domain_cases.py`, which checks
  real numbers against `tests/evaluation/golden_cases.json`.
- **Not "full evaluation."** Nothing here touches DeepEval, MLflow, or a
  real LLM. It is deterministic Python exercising deterministic Python.

Protected, real-corpus evaluation - the actual PDFs/XLSX, the actual
snapshot, real retrieval numbers, real DeepEval scores, real agent
trajectories - lives in `.github/workflows/eval.yml` and the
`tests/integration/`, `tests/regression/`, `tests/evaluation/` suites that
use the `conn`/`clock`/`auth`/`source_dir` fixtures (`tests/conftest.py`),
which skip gracefully when the real pack is not available and must never be
mistaken for this tier.

## What this proves

That `app/domain/*.py` and `app/policy/applicability.py` are generic over
their registries' *contents* - the same functions, called with a
completely different (fabricated) `overrides`/`defaults`/`fee_rules`/
`credit_rules` set via keyword arguments, produce correct results for an
account/agreement pair that has never existed in the real pack.
