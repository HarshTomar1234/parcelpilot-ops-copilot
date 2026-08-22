# Product Note: ParcelPilot Ops Copilot (Phase 3)

## What it is

An internal assistant for ParcelPilot support/operations staff. A staff
member asks a plain-language question about a customer, order, or ticket;
the system resolves what's being asked, looks up real account/order/ticket
data and policy documents, runs the same deterministic calculations a
trained agent would run by hand, and returns a grounded, cited answer with
an explicit confidence level.

It is built to feel like an internal operations assistant, not a generic
chat model: every fee, deadline, and severity it states is a real,
computed number tied to a real source, not a plausible-sounding guess.

## What it can do today

- Answer cancellation-fee questions for a specific order, including when a
  signed customer agreement overrides the standard policy.
- Answer service-credit eligibility questions for a specific order.
- Answer SLA-status questions for a specific ticket, including flagging a
  P1 breach for operational follow-up while still answering confidently.
- Classify ticket severity from its description.
- Answer general policy/product questions via document search.
- State its confidence level plainly (`CONFIDENT` / `CONDITIONAL` /
  `UNCERTAIN` / `ESCALATE`) and explain *why*, including when two sources
  disagree and which one won.
- Refuse to guess. When the evidence doesn't support an answer, it says so
  instead of producing a plausible-sounding one.
- Respect account-scoped access. A support agent scoped to one account
  cannot get information about another account's orders or tickets through
  this system - not via a direct request, and not via a question crafted
  to try to talk it into ignoring that scope.

## What it explicitly does not do yet

- **No actions.** It never cancels an order, issues a credit, or changes a
  ticket - it only tells you what the calculation says. Confirming and
  executing an action is a later phase.
- **No Operations Radar** or any dashboard/monitoring view.
- **No bulk questions.** "Which open tickets are past their SLA target"
  (a sweep across many records) isn't supported yet - ask about one order
  or ticket at a time.
- **No conversation memory.** Each question is answered independently.
- **No polished interface.** Today it's a command-line tool
  (`scripts/run_agent_cli.py`) for internal verification and demos, not a
  staff-facing product surface.

## Two known rough edges

- If you ask something entirely off-topic, it currently still tries to
  find something relevant rather than clearly saying "I don't have
  anything for that" - the underlying search will return its best (weak)
  guess rather than refusing outright. A confidence-level check should
  still keep you from trusting a weak answer, but it isn't a clean refusal
  yet.
- If you ask a question that needs a specific order or account but you
  have more than one in scope and don't say which, it should ask you to
  clarify - today it sometimes just searches policy documents in general
  instead of asking.

Both are recorded as known limitations with concrete next steps in
[`docs/evaluation_report.md`](evaluation_report.md).

## Example interaction

```
$ python scripts/run_agent_cli.py --question \
    "Can Northstar cancel ORD-1001 without a cancellation fee? Explain why."

status:       completed
trust_state:  CONFIDENT
tools called: ['lookup_structured_data', 'calculate_support_outcome', 'search_documents']

citations:
  - [SRC-07:orders:ORD-1001]
  - [SRC-05:p1:2] ...Northstar may cancel any BOOKED shipment before pickup with no fee...

conflicts:
  - SRC-05 overrides SRC-03: Northstar may cancel any BOOKED shipment before
    pickup with no fee, regardless of how long ago it was booked (SRC-05 s2).
```

The system found the standard policy (a fee would normally apply), found
that Northstar's signed agreement overrides it for this exact scenario,
resolved the conflict in the agreement's favor with a stated reason, and
answered confidently - all before the LLM wrote a single word of
explanation.
