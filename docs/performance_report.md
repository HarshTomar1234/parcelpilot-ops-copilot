# Performance Report

Structured-data and domain-calculation latency, measured locally against the full workbook (30 repetitions per operation). Retrieval latency is in docs/retrieval_evaluation.md. This is not a claim of production latency under load - it establishes that nothing here is accidentally quadratic or I/O-bound at this corpus size.

| Operation | p50 (ms) | p95 (ms) | n |
|---|---|---|---|
| get_account | 0.0626 | 0.0751 | 30 |
| get_order | 0.0737 | 0.0938 | 30 |
| get_ticket | 0.0735 | 0.1064 | 30 |
| search_orders | 0.103 | 0.1329 | 30 |
| search_tickets | 0.0961 | 0.1171 | 30 |
| evaluate_cancellation | 0.1262 | 0.2065 | 180 |
| evaluate_service_credit | 0.11 | 0.2007 | 180 |
| calculate_sla | 0.3779 | 0.5431 | 210 |
| classify_severity | 0.1369 | 0.1541 | 210 |

## Action workflow (Phase 4)

**Mock-executor latency only.** No real external action system exists to call - execute_action only updates the local actions audit row. This is not a production external-action latency claim. Unlike the read-only table above, every action workflow call durably commits its audit row to disk (sqlite3.Connection.commit()) before returning, which is why these numbers run roughly 1000x higher - that is a deliberate durability choice for the audit trail, not something to optimize away.

| Operation | p50 (ms) | p95 (ms) | n |
|---|---|---|---|
| prepare_escalation | 104.9403 | 137.3369 | 30 |
| confirm_action | 104.8864 | 116.5844 | 30 |
| execute_action | 104.7532 | 788.0603 | 30 |
