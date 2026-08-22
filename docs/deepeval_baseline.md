# DeepEval Baseline

**No quality scores were produced.** DeepEval's LLM-judged metrics require the judge to return structured JSON verdicts; MockProvider returns a fixed placeholder string, which is not that. This is not a bug being routed around - it is the honest signal that a real score needs a real judge model. What this run *did* verify: retrieval via the real `search_documents` tool, `LLMTestCase` construction, and the `GatewayDeepEvalModel` bridge all execute correctly up to the point DeepEval calls the judge - the wiring works, the score does not exist yet. Re-run with `--provider anthropic --model <name>` and a real `ANTHROPIC_API_KEY` for genuine scores.

DeepEval's error, for the first case it failed on: `Evaluation LLM outputted an invalid JSON. Please use a better evaluation model.`

## Method

16 golden cases with a real question and at least one expected document source (the same eligibility as docs/retrieval_evaluation.md). For each: retrieve via the real search_documents tool, generate an answer from the retrieved evidence via the configured LLMProvider, then score with DeepEval's ContextualRelevancyMetric (is the retrieved context relevant to the question) and FaithfulnessMetric (does the answer stay grounded in that context).

## Results

- Provider: `mock` / model `mock-model`
- Judge: `mock/mock-model`
- Cases evaluated: **16** (scored: 0, harness-blocked: 16)

## Per-case results

| Case | Contextual relevancy | Faithfulness |
|---|---|---|
| GC-001 | harness-blocked | harness-blocked |
| GC-002 | harness-blocked | harness-blocked |
| GC-003 | harness-blocked | harness-blocked |
| GC-004 | harness-blocked | harness-blocked |
| GC-005 | harness-blocked | harness-blocked |
| GC-006 | harness-blocked | harness-blocked |
| GC-007 | harness-blocked | harness-blocked |
| GC-008 | harness-blocked | harness-blocked |
| GC-009 | harness-blocked | harness-blocked |
| GC-010 | harness-blocked | harness-blocked |
| GC-011 | harness-blocked | harness-blocked |
| GC-012 | harness-blocked | harness-blocked |
| GC-013 | harness-blocked | harness-blocked |
| GC-014 | harness-blocked | harness-blocked |
| GC-016 | harness-blocked | harness-blocked |
| GC-027 | harness-blocked | harness-blocked |
