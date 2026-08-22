# Evaluation Report (Phase 3)

Consolidates every measured result across the project. Every number here
came from an actual run, listed with the command that produced it. Nothing
here is estimated or projected.

## Test suites

| Suite | Real pack | No pack (hosted CI) |
|---|---|---|
| Full `pytest` | 215 passed | 105 passed, 110 skipped, 0 failed |
| `tests/fixture_backed/` only | 39 passed | 39 passed (never skips - see below) |

`tests/fixture_backed/` is the only suite `.github/workflows/ci.yml`
guarantees runs and never skips - it uses a fabricated, version-controlled
dataset (`tests/fixtures/seed_fixture_db.py`) instead of the real,
never-committed source pack. It includes all 9 security regression tests
and 5 tests proving agent entity resolution generalizes past the real
pack's `ORD-`/`TKT-`/`ACCT-` ID convention to the fixture's deliberately
different `FXO-`/`FXT-`/`FX-` prefixes.

## Retrieval

`scripts/run_retrieval_eval.py` - see
[`retrieval_evaluation.md`](retrieval_evaluation.md) for the full report.
Unchanged this phase.

## RAG quality (DeepEval, Phase 2)

`scripts/run_deepeval_baseline.py` - see
[`deepeval_baseline.md`](deepeval_baseline.md). 16 cases evaluated, 0
scored: `MockProvider` cannot satisfy DeepEval's structured-JSON judge
requirement. Not fixed this phase (still no `ANTHROPIC_API_KEY`).

## Agent trajectory (DeepEval, Phase 3 - new)

`scripts/run_agent_trajectory_eval.py` - full per-case table in
[`agent_trajectory_evaluation.md`](agent_trajectory_evaluation.md). Run
against the real pack, `MockProvider`:

| Metric | Value | Judge needed? |
|---|---|---|
| Cases evaluated | 19 | - |
| Mean tool correctness | **0.89** | No (exact match) |
| Status match rate | **0.82** (14/17 checkable) | No (exact match) |
| Task completion scored | 0 of 19 | Yes - harness-blocked, same limitation as RAG quality above |

Tool correctness and status match are genuine, non-fabricated scores -
they compare the real agent's actual tool calls and terminal status
against the golden dataset and need no LLM judge, unlike RAG quality above.

**Status-match rate improved from 0.71 to 0.82 during this phase**, after
fixing a real bug where the orchestrator treated an operational
"needs human follow-up" flag (P1 SLA breach routing) as if it were an
epistemic trust downgrade, incorrectly forcing a confident answer into an
`escalated` status. See the private phase report for the full story.

The 3 remaining status mismatches are documented, unfixed limitations, not
test gaps:

| Case | Expected | Actual | Why |
|---|---|---|---|
| GC-002 | needs_clarification | completed | No planner rule yet for "ambiguous multi-account, no explicit entity" |
| GC-015 | insufficient_evidence | completed | Retrieval-relevance gap: BM25 returns results even for weak matches |
| GC-016 | insufficient_evidence | completed | Same retrieval-relevance gap |

## Security

All 9 tests in `tests/fixture_backed/test_security.py` pass, in the
always-runs public CI tier:

- Cross-account access denial (direct tool call and full agent pipeline)
- Unknown tool name handled without a raw exception
- Authorization cannot be widened via smuggled tool arguments
- SQL-injection-shaped input treated as inert text, tables intact
- Prompt-injection question text does not bypass authorization or extract
  the system prompt

No test targets prompt injection embedded in retrieved *document* content
specifically - recorded as a gap, not covered by the above.

## Performance

Structured-data/domain-calculation latency: unchanged from Phase 2, see
[`performance_report.md`](performance_report.md) (sub-millisecond at this
corpus size). A full `run_agent()` call (3-tool cancellation case, real
pack, `MockProvider`): ~2.6ms total. Not a production latency claim - the
real cost is a network round trip to a model provider, unexercised this
phase (no API key).

## Cost

$0.00 for every run this phase - `MockProvider` is priced at $0/M tokens
by definition. The cost-accounting mechanism itself (`TokenUsage`,
`CostEstimate`, `PricingTable`, and now `ParcelPilotLLMGateway.last_run.
total_cost_usd`) is built and unit-tested, not yet exercised against a
real, paid call.

## Provider resilience

`ParcelPilotLLMGateway`'s fallback routing is unit-tested with stub
providers (primary failure -> fallback success, all-providers-fail raises
with every attempt recorded, per-candidate model substitution) and
verified as a drop-in replacement for a single `LLMProvider` by direct
smoke test against the real agent. No live second-provider fallback was
exercised (no second API key available).

## Release gates

Per [`quality_gates.md`](quality_gates.md):

| Gate | Status |
|---|---|
| 0 unauthorized access | Met - 9/9 security tests pass |
| 0 unsafe actions | Met - no action-execution capability exists this phase |
| 0 deterministic regressions | Met - 215/215 pytest, including the full Phase 1/2 domain suite |
| 0 invalid required citations | Met - citation validation runs on every composed answer; an invalid marker is stripped, never silently shown as valid |
| RAG/agent quality thresholds | **Not set** - no real judge-scored baseline exists yet (MockProvider limitation, both phases) |

## Known limitations (full list)

See the "Known limitations" section of
[`architecture_note.md`](architecture_note.md) and the private phase
report's "Risks / trade-offs" for the complete, prioritized list.
