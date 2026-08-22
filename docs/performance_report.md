# Performance Report

Structured-data and domain-calculation latency, measured locally against the full workbook (30 repetitions per operation). Retrieval latency is in docs/retrieval_evaluation.md. This is not a claim of production latency under load - it establishes that nothing here is accidentally quadratic or I/O-bound at this corpus size.

| Operation | p50 (ms) | p95 (ms) | n |
|---|---|---|---|
| get_account | 0.0365 | 0.0454 | 30 |
| get_order | 0.0436 | 0.0526 | 30 |
| get_ticket | 0.0414 | 0.0461 | 30 |
| search_orders | 0.0868 | 0.1258 | 30 |
| search_tickets | 0.0791 | 0.0861 | 30 |
| evaluate_cancellation | 0.106 | 0.1756 | 180 |
| evaluate_service_credit | 0.0909 | 0.162 | 180 |
| calculate_sla | 0.3649 | 0.4201 | 210 |
| classify_severity | 0.1235 | 0.1399 | 210 |
