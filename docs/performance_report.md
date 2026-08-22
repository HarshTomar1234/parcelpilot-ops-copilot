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

## API layer (Phase 6)

Measured with `scripts/run_api_load_test.py` against the Dockerized API
(`docker build . && docker run ...`), real pack, `MockProvider`, real
HTTP round trips through the full ASGI stack - not the in-process
function-call numbers above. **`MockProvider` latency is not production
LLM latency** - `/api/chat`'s LLM-call time below is mock-call overhead
only; no real network round trip to a model provider has been measured
(no `ANTHROPIC_API_KEY` in this environment, consistent with every prior
phase).

**Single request, `/api/chat`** ("Is TKT-501 within its first-response
SLA?"): total 23.98ms = tool/backend time 19.38ms (3 tool calls) + LLM
(mock) time ~4.60ms.

**Single request, action workflow** (real pack, `TKT-501`/`TKT-505`):
prepare 125ms, confirm 81ms, execute 70ms - the same "commits its audit
row to disk before returning" cost already documented above for the
direct function calls, now measured through HTTP too.

**Concurrency smoke test** (`scripts/run_api_load_test.py`, 1/5/10
concurrent requests, single Docker container, one uvicorn worker):

| Endpoint | Concurrency | req/s | p50 (ms) | p95 (ms) | max (ms) | Errors |
|---|---|---|---|---|---|---|
| /api/chat | 1 | 14.1 | 69.9 | 69.9 | 69.9 | 0 |
| /api/chat | 5 | 52.3 | 89.6 | 91.8 | 94.3 | 0 |
| /api/chat | 10 | 38.5 | 241.9 | 252.7 | 252.7 | 0 |
| /api/radar/run | 1 | 4.5 | 224.0 | 224.0 | 224.0 | 0 |
| /api/radar/run | 5 | 20.2 | 228.7 | 235.4 | 243.5 | 0 |
| /api/radar/run | 10 | 7.4 | 1265.3 | 1302.4 | 1305.1 | 0 |

Zero errors at every level - but only after a real bug found by this
exact test was fixed (see below). Latency clearly degrades under
concurrent load (`/api/radar/run` p50 goes from 224ms at concurrency 1 to
1.27s at concurrency 10) - expected and already documented: SQLite here
is single-writer, one uvicorn worker, no connection pool. This is a smoke
test proving the API doesn't error under light concurrent load, not a
capacity claim; scaling past this would mean more workers and/or a
different datastore, not something this corpus size currently needs.

**A real concurrency bug found and fixed this phase:** the first run of
this exact test produced errors at concurrency 5 (3/5 failed) and 10
(10/10 failed) with `sqlite3.ProgrammingError: SQLite objects created in
a thread can only be used in that same thread`. Cause: FastAPI runs a
sync dependency's setup/teardown and the route handler as separate
`anyio` threadpool calls, which are not guaranteed to land on the same OS
thread - `sqlite3.connect()`'s default `check_same_thread=True` then
rejects the connection when a later step lands on a different thread.
Fixed in `app/db/connection.py::connect()` with `check_same_thread=False`
(safe here - every caller already gives each connection to exactly one
logical owner at a time, never true concurrent access to one connection).
Re-running the test after the fix: 0 errors at every level above.

## Final validation phase (red team, concurrency + races)

Re-measured against a freshly rebuilt Docker image (real pack,
`MockProvider`):

| Endpoint | Concurrency | req/s | p50 (ms) | p95 (ms) | max (ms) | Errors |
|---|---|---|---|---|---|---|
| /api/chat | 1 | 17.8 | 55.2 | 55.2 | 55.2 | 0 |
| /api/chat | 5 | 46.0 | 91.6 | 93.4 | 106.7 | 0 |
| /api/chat | 10 | 35.2 | 264.9 | 274.2 | 281.2 | 0 |
| /api/radar/run | 1 | 5.4 | 184.6 | 184.6 | 184.6 | 0 |
| /api/radar/run | 5 | 22.9 | 199.6 | 204.8 | 217.5 | 0 |
| /api/radar/run | 10 | 8.4 | 1178.2 | 1189.3 | 1191.8 | 0 |

**Action confirm/execute race, same action, 20 concurrent HTTP requests**
(the highest-priority check this phase - see
[`red_team_report.md`](red_team_report.md) F1 for the full writeup):

- `/api/actions/confirm`: **before the fix**, 4 of 20 concurrent requests
  all reported `success: true` for what should be a single valid
  transition. **After** the atomic compare-and-swap fix
  (`app/actions/store.py::save_action_if_status`): exactly 1 of 20
  succeeds, the other 19 get `error_code=wrong_state` - re-verified
  against both the fixture-backed test suite and a live rebuilt
  container.
- `/api/actions/execute`: all 20 concurrent requests report
  `success: true` (correct - execution is documented idempotent), but
  only one of them performs the real `CONFIRMED -> EXECUTED` transition;
  the other 19 detect they lost the race and return the already-executed
  record instead of a second, redundant write.

No corrupted audit record, no duplicate row, in either case - verified by
reading the `actions` table directly after the race, not just trusting
the HTTP responses.
