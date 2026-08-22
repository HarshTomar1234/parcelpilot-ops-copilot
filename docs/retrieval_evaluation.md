# Retrieval Evaluation

Measured against `tests/evaluation/golden_cases.json` by running `scripts/run_retrieval_eval.py` over a freshly built database. Regenerate with:

```
python scripts/run_retrieval_eval.py --source-dir "<pack>/source-pack"
```

## Method

16 of the 32 golden cases cite at least one document source (SRC-01..SRC-06) and pose a real natural-language question - the rest are structured-data lookups, action-flow steps, or authorization-denial cases with no document to retrieve. For each eligible case, `search_documents()` runs with the case's `question` text verbatim at top_k=5 (no query rewriting, no filters). A case is a hit at rank R if an expected source_id appears at position R in the results.

## Results

- Cases evaluated: **16**
- Recall@3: **100%**
- Recall@5: **100%**
- Source hit rate (expected sources actually retrieved, of all expected-source citations across eligible cases): **96%**
- Retrieval latency: p50 **0.38 ms**, p95 **0.43 ms** (16 queries, local SQLite, cold connection per run)

## Per-case detail

| Case | Rank | Expected | Retrieved (top 5) |
|---|---|---|---|
| GC-001 | 1 | SRC-03, SRC-05 | SRC-05, SRC-06, SRC-03, SRC-04, SRC-05 |
| GC-002 | 1 | SRC-03, SRC-06, SRC-05 | SRC-06, SRC-03, SRC-03, SRC-01, SRC-05 |
| GC-003 | 1 | SRC-03, SRC-05 | SRC-03, SRC-05, SRC-06, SRC-04, SRC-05 |
| GC-004 | 1 | SRC-03, SRC-06 | SRC-03, SRC-06, SRC-05, SRC-06, SRC-04 |
| GC-005 | 1 | SRC-03 | SRC-03, SRC-06, SRC-05, SRC-03, SRC-04 |
| GC-006 | 2 | SRC-03 | SRC-06, SRC-03, SRC-05, SRC-04 |
| GC-007 | 2 | SRC-03, SRC-06 | SRC-04, SRC-06, SRC-05, SRC-05, SRC-03 |
| GC-008 | 2 | SRC-01, SRC-05 | SRC-04, SRC-05, SRC-01, SRC-01, SRC-03 |
| GC-009 | 1 | SRC-01 | SRC-01, SRC-02, SRC-04, SRC-05, SRC-01 |
| GC-010 | 2 | SRC-01, SRC-06 | SRC-05, SRC-01, SRC-01, SRC-03, SRC-03 |
| GC-011 | 1 | SRC-04 | SRC-04, SRC-04, SRC-06, SRC-02, SRC-01 |
| GC-012 | 1 | SRC-05, SRC-03 | SRC-03, SRC-05, SRC-04, SRC-05, SRC-06 |
| GC-013 | 2 | SRC-01, SRC-02 | SRC-05, SRC-01, SRC-02, SRC-01, SRC-01 |
| GC-014 | 1 | SRC-04 | SRC-04, SRC-04, SRC-03, SRC-06, SRC-05 |
| GC-016 | 1 | SRC-05 | SRC-05, SRC-03, SRC-05, SRC-06, SRC-05 |
| GC-027 | 3 | SRC-06, SRC-03 | SRC-05, SRC-04, SRC-06, SRC-03, SRC-03 |

## Representative failures

No case-level miss: every eligible case retrieved at least one expected source in the top 3 (that is what Recall@3/@5 above measure).

### Partial source misses (source hit rate 96%)

A case can pass the rank-based hit test above (some expected source was found) while still missing one of several expected sources - this is what `source_hit_rate` catches that Recall@K does not.

- **GC-010**: missing SRC-06 from the top 5 (retrieved SRC-05, SRC-01, SRC-01, SRC-03, SRC-03). Query: "When is the first-response deadline for TKT-502?"

One known ranking sensitivity found during Phase 1 testing, not from the table above: a query built only from the words *"Northstar cancellation fee waiver"* ranks SRC-06 (LumenWorks) above SRC-05 (Northstar), because the literal word "waiver" appears in SRC-06's text ("No special cancellation-fee waiver applies") but nowhere in SRC-05's. The OR-of-terms BM25 query has no way to know "Northstar" is the more load-bearing term for this question. Every case actually phrased the way a user would ask it (naming the account or order) ranks correctly - this only surfaces for artificially sparse, keyword-only queries. Documented as a known limitation of plain BM25 rather than fixed, per ADR-003 (embeddings only if measured to help, and this corpus is 24 chunks).
