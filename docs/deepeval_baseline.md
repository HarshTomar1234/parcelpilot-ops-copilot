# DeepEval Baseline

This run used `anthropic/claude-haiku-4-5-20251001` as both answerer and judge - these are real LLM-judged quality scores.

## Method

16 golden cases with a real question and at least one expected document source (the same eligibility as docs/retrieval_evaluation.md). For each: retrieve via the real search_documents tool, generate an answer from the retrieved evidence via the configured LLMProvider, then score with DeepEval's ContextualRelevancyMetric (is the retrieved context relevant to the question) and FaithfulnessMetric (does the answer stay grounded in that context).

## Results

- Provider: `anthropic` / model `claude-haiku-4-5-20251001`
- Judge: `anthropic/claude-haiku-4-5-20251001`
- Cases evaluated: **16** (scored: 16, harness-blocked: 0)
- Mean contextual relevancy: **0.36**
- Mean faithfulness: **0.94**

## Per-case results

| Case | Contextual relevancy | Faithfulness |
|---|---|---|
| GC-001 | 0.57 | 1.00 |
| GC-002 | 0.50 | 1.00 |
| GC-003 | 0.67 | 1.00 |
| GC-004 | 0.33 | 1.00 |
| GC-005 | 0.33 | 1.00 |
| GC-006 | 0.50 | 1.00 |
| GC-007 | 0.33 | 1.00 |
| GC-008 | 0.00 | 1.00 |
| GC-009 | 0.20 | 1.00 |
| GC-010 | 0.00 | 0.50 |
| GC-011 | 0.25 | 1.00 |
| GC-012 | 0.20 | 1.00 |
| GC-013 | 0.50 | 0.50 |
| GC-014 | 0.67 | 1.00 |
| GC-016 | 0.20 | 1.00 |
| GC-027 | 0.50 | 1.00 |
