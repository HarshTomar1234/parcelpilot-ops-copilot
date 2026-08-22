# Operations Radar Evaluation

Real-pack detection run. Provider: `mock` / model `mock-model`. Every alert below came from a deterministic rule in app/detection/rules.py - the LLM summary column is explanatory prose only, generated after detection and never able to change count/threshold/severity/affected_accounts/evidence.

**Total alerts: 6**

| Alert type | Count |
|---|---|
| known_issue_pattern | 2 |
| overdue_pickup | 1 |
| recurring_issue | 1 |
| sla_breach | 2 |

## Per-alert results

| Alert ID | Type | Severity | Observed/Threshold | Accounts | Evidence | Trust |
|---|---|---|---|---|---|---|
| ALERT-811fa8dad17e59cb | sla_breach | critical | 1/1 | ACCT-004 | 4 | CONFIDENT |
| ALERT-918d92569e8d048a | sla_breach | critical | 1/1 | ACCT-001 | 4 | CONFIDENT |
| ALERT-83352af2fbf0c38e | recurring_issue | high | 2/2 | ACCT-001, ACCT-004 | 2 | CONFIDENT |
| ALERT-cd5ef8aadc656a5a | overdue_pickup | high | 1/1 | ACCT-002 | 1 | CONFIDENT |
| ALERT-24cbaad4aaacdbf7 | known_issue_pattern | medium | 1/1 | ACCT-001 | 2 | CONFIDENT |
| ALERT-e4a5525c71160f55 | known_issue_pattern | medium | 2/1 | ACCT-002 | 3 | CONFIDENT |

## LLM summary cost/latency (per alert)

| Alert ID | Tokens | Latency (ms) | Cost (USD) |
|---|---|---|---|
| ALERT-811fa8dad17e59cb | 336 | 0.0402 | 0.000000 |
| ALERT-918d92569e8d048a | 336 | 0.032 | 0.000000 |
| ALERT-83352af2fbf0c38e | 347 | 0.0293 | 0.000000 |
| ALERT-cd5ef8aadc656a5a | 334 | 0.0286 | 0.000000 |
| ALERT-24cbaad4aaacdbf7 | 351 | 0.0292 | 0.000000 |
| ALERT-e4a5525c71160f55 | 352 | 0.0292 | 0.000000 |
