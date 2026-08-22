# Product Note: ParcelPilot Ops Copilot

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
- Refuse to guess about an off-topic question. A question with no
  genuinely relevant evidence in the corpus returns "insufficient
  evidence" rather than a low-confidence guess.
- Ask for clarification when a question needs a specific order, ticket,
  or account but doesn't name one and more than one is in scope, rather
  than silently guessing which one was meant.
- Prepare a ticket escalation for explicit human confirmation. Escalation
  eligibility (a P1 ticket or an SLA breach) is a deterministic check, not
  a judgment call - and nothing is actually escalated until a separate,
  explicit confirmation step happens; the assistant itself only ever
  recommends.

## What it explicitly does not do yet

- **No automatic actions.** Escalation can be *prepared*, but confirming
  and executing it is a separate, explicit step - the assistant never
  does either on its own, and it never cancels an order or issues a
  credit at all.
- **No second action type.** A ticket-update action beyond escalation
  isn't built.
- **No Operations Radar** or any dashboard/monitoring view.
- **No bulk questions.** "Which open tickets are past their SLA target"
  (a sweep across many records) isn't supported yet - ask about one order
  or ticket at a time.
- **No conversation memory.** Each question is answered independently.
- **No polished interface.** Today it's a command-line tool
  (`scripts/run_agent_cli.py`) for internal verification and demos, not a
  staff-facing product surface; the action workflow has no CLI yet either.

Recorded with concrete detail in
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
