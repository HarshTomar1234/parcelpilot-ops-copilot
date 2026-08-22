# Performance Report

Structured-data and domain-calculation latency, measured locally against the full workbook (30 repetitions per operation). Retrieval latency is in docs/retrieval_evaluation.md. This is not a claim of production latency under load - it establishes that nothing here is accidentally quadratic or I/O-bound at this corpus size.

| Operation | p50 (ms) | p95 (ms) | n |
|---|---|---|---|
| get_account | 0.0371 | 0.0459 | 30 |
| get_order | 0.0445 | 0.0523 | 30 |
| get_ticket | 0.0423 | 0.0474 | 30 |
| search_orders | 0.09 | 0.1008 | 30 |
| search_tickets | 0.0821 | 0.0889 | 30 |
| evaluate_cancellation | 0.1126 | 0.1778 | 180 |
| evaluate_service_credit | 0.0943 | 0.1801 | 180 |
| calculate_sla | 0.3881 | 0.4523 | 210 |
| classify_severity | 0.1289 | 0.1459 | 210 |

## Action workflow (Phase 4)

**Mock-executor latency only.** No real external action system exists to call - execute_action only updates the local actions audit row. This is not a production external-action latency claim. Unlike the read-only table above, every action workflow call durably commits its audit row to disk (sqlite3.Connection.commit()) before returning, which is why these numbers run roughly 1000x higher - that is a deliberate durability choice for the audit trail, not something to optimize away.

| Operation | p50 (ms) | p95 (ms) | n |
|---|---|---|---|
| prepare_escalation | 105.0048 | 121.9502 | 30 |
| confirm_action | 104.8714 | 127.3828 | 30 |
| execute_action | 104.739 | 535.9921 | 30 |

## Operations Radar (Phase 5)

`full_snapshot_scan` runs every detection rule unrestricted (all accounts); `scoped_account_query` runs the same with the caller restricted to one account. Both measured against the real pack, not the fixture corpus.

| Operation | p50 (ms) | p95 (ms) | n |
|---|---|---|---|
| full_snapshot_scan | 6.9032 | 7.3816 | 30 |
| scoped_account_query | 3.0759 | 3.4057 | 30 |
