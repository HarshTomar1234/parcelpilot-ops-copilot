# Product Note: ParcelPilot Ops Copilot

## What it is

An internal assistant for ParcelPilot support/operations staff, delivered
as three surfaces on one deterministic core: **Support Copilot** answers
a plain-language question about a customer, order, or ticket with a
grounded, cited, trust-scored answer; **Operations Radar** proactively
surfaces operational issues before anyone asks about them; and a safe
**escalation workflow** lets an eligible ticket move from investigation
to a confirmed, audited escalation. All three are reachable through a
staff web UI and a typed HTTP API (`app/api/`), not just a script.

It is built to feel like an internal operations assistant, not a generic
chat model: every fee, deadline, severity, and alert it states is a real,
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
- All of the above through a staff web UI (three tabs: Support Copilot,
  Operations Radar, Action Panel) and a typed HTTP API, with the current
  demo identity, its role, and the fixed dataset snapshot always visible
  - not only through a developer CLI.

## Operations Radar: proactive issue detection

The selected extension problem. Everything above is *reactive* - it
answers a question someone already asked. Operations Radar is
*proactive*: it surfaces operational issues before an operator asks about
them at all - an SLA breach, a recurring cluster of high-severity
tickets, tickets matching a currently-active known product issue, a
carrier with repeated fault incidents, an order whose pickup window has
elapsed with nothing recorded.

**Why proactive detection.** The reactive assistant only helps once
someone already suspects a problem and asks the right question. The two
highest-cost failure modes in support operations are the ones nobody
asked about yet: an SLA quietly breaching while nobody is watching, and
the same known issue generating ticket after ticket without anyone
connecting them. Detection closes that gap without needing a human to
know what to ask.

**How the deterministic rules work.** Every alert comes from a named rule
in `app/detection/rules.py` - not a model's judgment. A rule reads
already-authorization-scoped structured data, applies an explicit,
documented threshold and time window, and either produces an alert with
real evidence or produces nothing. The LLM is invoked, optionally, only
after an alert already exists, to write a short explanation - it can
never change what was detected, how many records were involved, which
accounts are affected, or how severe the finding is.

**How false positives are controlled.** Every rule has an explicit
threshold (the minimum count that turns "an isolated incident" into "a
pattern") and window (how far back it looks), both named constants, both
tested at exactly the boundary: below threshold produces nothing, at
threshold produces the alert, an unrelated record never matches, a
resolved known issue never produces a current alert regardless of how
similar a new ticket's wording is. One real false positive was found and
fixed during development - a ticket about an unrelated API error matched
a known issue purely through generic vocabulary ("shipment," "creation")
that happened to appear in that issue's own text; excluding known-generic
domain words fixed it without weakening genuine matches.

**How operator evidence is shown.** Every alert carries the record IDs
(tickets, orders) and document citations it was built from, plus a
deterministic `alert_id` so the same underlying evidence always produces
the same alert on re-detection - never a duplicate. An operator can
always answer "why did I get this" by reading the evidence list, not by
trusting a summary.

**How this could evolve into production monitoring.** Today, detection
runs on demand (a script or a tool call) against a point-in-time
snapshot. A production version would run on a schedule against live data,
track alert state over time (new / acknowledged / resolved) instead of
recomputing from scratch each time, and route alerts to the people who
own each account - none of that exists yet, and none of it was needed to
prove the detection engine itself works.

## What it explicitly does not do yet

- **No automatic actions.** Escalation can be *prepared*, but confirming
  and executing it is a separate, explicit step - the assistant never
  does either on its own, and it never cancels an order or issues a
  credit at all. The same is true of Operations Radar: an alert can only
  *recommend* preparing an escalation, never trigger one.
- **No second action type.** A ticket-update action beyond escalation
  isn't built.
- **No scheduled monitoring.** Operations Radar runs on demand - a UI
  button, an API call, or `scripts/run_operations_radar_eval.py` - not on
  a schedule, and has no persistent alert state (new/acknowledged/
  resolved) across runs.
- **No bulk question-answering in the reactive assistant.** "Which open
  tickets are past their SLA target" as a *conversational* question isn't
  supported - that exact pattern is what Operations Radar's SLA-breach
  rule answers proactively instead.
- **No conversation memory.** Each question is answered independently.
- **No real identity provider.** The staff UI's identity picker maps a
  chosen demo identity (`ops_admin` / `support_agent` /
  `restricted_support`) to a real, server-owned `AuthContext` - a
  deliberate stand-in for a hosted assessment, never a design for
  production login. The account-scope enforcement it exercises is real;
  the "who is logged in" mechanism around it is not.

Recorded with concrete detail in
[`docs/evaluation_report.md`](evaluation_report.md).

## Product metrics

**Primary: Evidence-backed resolution rate.** Of all questions the system
investigates, the fraction that reach a `completed` or `escalated` status
backed by real citations - as opposed to `insufficient_evidence`,
`needs_clarification`, or `evidence_validation_failed`, all of which mean
the system correctly declined to guess. A high rate means the corpus and
rules cover what staff actually ask; a low rate is a prompt to add
coverage, never a prompt to lower the evidence bar.

**Secondary (Operations Radar): Actionable alert rate.** Of all alerts
Operations Radar generates, the fraction with `trust_state=CONFIDENT` and
at least one evidence reference - an alert an operator can act on
immediately, without first having to independently re-verify whether it's
real. Measured on the real pack today: **6 of 6 alerts (100%)**, because
every current rule only ever emits an alert once it has already confirmed
CONFIDENT trust and real evidence - there is no code path that produces a
weaker alert to inflate the count. This is a property of the rules'
design, not a filter applied after the fact, and the rate is expected to
stay near 100% for as long as that design holds.

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
