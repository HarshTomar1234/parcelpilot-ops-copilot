# AGENTS.md â€” Persistent engineering instructions

Read this before any coding session on ParcelPilot Ops Copilot.

## Product

Internal ops copilot for **authorized ParcelPilot support/operations staff**.
Not a customer-facing bot. Not a generic chatbot.

## Permanent rules

1. Never invent business rules or records. If the source pack does not state it, it does not exist.
2. Never hard-code example answers or example IDs (`ORD-1001`, `ACCT-001`, â€¦). Reason over loaded data.
3. Never use the LLM as the security boundary.
4. Authorization is enforced in the API/tool/data layers, before retrieval and before query execution.
5. Critical arithmetic and business calculations are deterministic Python. The LLM explains results; it never produces or alters them.
6. Every substantive answer carries traceable evidence (file+page+section, or table+record id, or calculation id).
7. Deprecated and historical sources must be labeled wherever they surface.
8. Conflicts that change a material outcome must be surfaced explicitly, never silently resolved.
9. State-changing actions require explicit confirmation via prepare â†’ confirm.
10. Agent and tool execution is bounded (steps, tool calls, tokens, wall time).
11. Do not expose unrestricted model-generated SQL. Typed, narrow operations only.
12. Evaluation is part of the product, not an afterthought.
13. Measure latency; do not claim it.
14. Measure tokens and cost; do not guess.
15. Measure throughput under basic concurrency.
16. Maintain structured observability with a `request_id` per request.
17. Do not commit secrets.
18. Do not commit assessment/customer source files (`D:\AI-Projects\parcelpilot-assessment`) to the public repository.
19. Prefer simple, inspectable architecture over unnecessary complexity.
20. Never claim completion without verification. Show the command and its output.

## Source authority (documented, not invented)

Support Policy v3 Â§1 states the precedence explicitly:

> signed customer agreement â†’ current support policy â†’ current product documentation.
> Historical tickets and internal notes are context only and may contain incorrect past guidance.

Implemented `authority_class` ranking:

| Rank | Class | Members |
|---|---|---|
| 1 | `AGREEMENT` | 05 Northstar, 06 LumenWorks |
| 2 | `POLICY_CURRENT` | 01 Support Policy v3, 03 Cancellation & Service Credit SOP v4 |
| 3 | `PRODUCT_DOC` | 04 Product Operations Guide & Known Issues |
| 4 | `HISTORICAL` | `tickets.historical_resolution` â€” context only, never authority |
| â€” | `DEPRECATED` | 02 Support Policy v2 â€” excluded from answers; may only be cited to explain that it is superseded |

An agreement only overrides the clauses it actually addresses. Silence in an
agreement falls back to the next class down. Both agreements say this in their
own text; do not generalize a waiver beyond its clause.

## Time

The reference "now" for all dataset reasoning is the **README snapshot time**,
never the machine clock. Snapshot: `2026-08-16 11:00 Asia/Kolkata` (a **Sunday**).
All workbook timestamps are naive and assumed Asia/Kolkata.

## Business hours

The source pack **never defines business hours or business days**, yet most SLA
targets are expressed in them. Business-hour SLA results must be returned as
`CONDITIONAL` with the assumption stated in the response, never as `CONFIDENT`.
The calendar is configuration, not a constant baked into logic.

## Verification discipline

Every phase ends with: implement â†’ test â†’ inspect â†’ document â†’ report pass/fail.
A written explanation is not a substitute for a passing test.
