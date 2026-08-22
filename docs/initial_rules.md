# Initial Business Rules

Every rule below is quoted or paraphrased from a real source with a citation.
Nothing here is a generic assumption. Where the pack is silent, that is recorded
as a **gap**, not filled in.

Reference time throughout: **`2026-08-16 11:00 Asia/Kolkata` (Sunday)** — the
README snapshot.

---

## R1 — Source precedence

**Evidence:** SRC-01 p.1 §1.

> "When sources conflict, use the signed customer agreement first, then the
> current support policy, then current product documentation. Historical tickets
> and internal notes are context only and may contain incorrect past guidance."

`AGREEMENT` > `POLICY_CURRENT` > `PRODUCT_DOC` > `HISTORICAL` (context only).
`DEPRECATED` is excluded (SRC-02 p.1: "must not be used as current policy").

**R1.1 — Scoped override.** An agreement overrides only the clauses it
addresses; otherwise the next class applies. Stated in-source twice: SRC-05 §3
("Unless this agreement states otherwise, the current ParcelPilot service-credit
SOP applies") and SRC-06 §2 ("No special cancellation-fee waiver applies. Use
the current ParcelPilot Cancellation & Service Credit SOP").

**R1.2 — Agreement applicability.** An agreement applies only to its named
account and only within its term. SRC-05 → `ACCT-001`, 2026-01-01→2026-12-31.
SRC-06 → `ACCT-002`, 2026-03-01→2027-02-28. Both cover the snapshot date.

---

## R2 — Order cancellation

**Evidence:** SRC-03 p.1 §1.

| Order status | Rule | Fee |
|---|---|---|
| `DRAFT` | May be cancelled | none |
| `BOOKED`, not yet `PICKED_UP` | May be cancelled | none within 30 min of `booked_at`; **INR 250** after, *unless an agreement explicitly waives it* |
| `PICKED_UP` | **Do not cancel** — use return-to-origin workflow | n/a |
| `DELIVERED` | Cannot be cancelled | n/a |

**R2.1 — Northstar fee waiver.** SRC-05 p.1 §2: Northstar (`ACCT-001`) may
cancel **any** `BOOKED` shipment before pickup with no fee, "regardless of how
long ago the shipment was booked". Once `PICKED_UP`, standard RTO applies — the
waiver does **not** extend past pickup.

**R2.2 — LumenWorks has no waiver.** SRC-06 p.1 §2, explicitly.

**R2.3 — Elapsed time basis.** `cancellation_requested_at − booked_at`, not
snapshot − booked_at. The request time is what the rule is about.

**Verified outcomes over the actual orders:**

| order | account | status | mins since booking | default SOP | applied (with agreement) |
|---|---|---|---|---|---|
| ORD-1001 | Northstar | BOOKED | 120 | INR 250 | **INR 0** (R2.1) |
| ORD-1002 | Northstar | PICKED_UP | 130 | do not cancel → RTO | do not cancel → RTO (waiver does not apply) |
| ORD-2001 | LumenWorks | BOOKED | 75 | INR 250 | **INR 250** (R2.2) |
| ORD-2002 | LumenWorks | BOOKED | — | no cancellation requested | n/a |
| ORD-3001 | Beacon Retail | BOOKED | 15 | INR 0 | **INR 0** (within 30 min) |
| ORD-4001 | Axis Labs | DELIVERED | — | cannot cancel | cannot cancel |

---

## R3 — Failed-pickup service credits

**Evidence:** SRC-03 p.1 §2.

Default eligibility, **all three** required:
1. pickup more than **2 hours** past `pickup_window_end`;
2. `carrier_fault` is true;
3. no customer-caused issue.

Default credit = **min(INR 500, 10% × `shipment_fee_inr`)**.

**R3.1 — Delay reference time.** If `pickup_actual_at` is null the pickup has
not happened, so the delay is measured against the **snapshot time** and is still
accruing. (Assumption, recorded in ADR-006 — the SOP does not spell out the
still-open case.)

**R3.2 — LumenWorks replacement clause.** SRC-06 p.1 §3: >**4 hours** past
window end + carrier fault + no customer fault → fixed **INR 300**. Explicitly
"replaces the default failed-pickup credit amount and timing threshold". This
cuts **both ways**: a 3-hour carrier-fault delay yields a credit under the
default SOP but **nothing** for LumenWorks.

**R3.3 — Northstar monthly cap.** SRC-05 p.1 §3: monthly aggregate credits
capped at **INR 5,000**. The per-credit formula and threshold are unchanged —
the SOP default still applies to Northstar.

**R3.4 — Manager approval.** SRC-03 §3: any individual credit above **INR
1,000** requires manager approval.

**R3.5 — Uncertainty bar.** SRC-03 §3: "Do not promise a credit when carrier
fault, pickup timing, or customer fault is unknown." Combined with the data
model (no "unknown" fault state), a delayed pickup with `carrier_fault = False`
must trigger verification, not a denial stated as fact.

**R3.6 — Conflict before action.** SRC-03 §3: "When data conflicts, identify the
conflict and request verification before a state-changing action."

**Verified outcome — the only eligible order in the pack:**

| order | account | fee | window end | delay at snapshot | default SOP | agreement | applied |
|---|---|---|---|---|---|---|---|
| ORD-2002 | LumenWorks | 2400 | 06:30 | **4.5 h** (accruing) | INR 240 | INR 300 (R3.2) | **INR 300**, no manager approval (< 1,000) |

Note this is a *material* conflict: both paths grant a credit, but the amounts
differ, so the source choice changes the money.

---

## R4 — Severity classification

**Evidence:** SRC-01 p.1 §2. There is **no severity column** in the workbook —
severity is derived from `description` and must be presented as an inference.

| Severity | Definition (abridged from source) |
|---|---|
| P1 Critical | complete production outage preventing all shipment creation for a customer; confirmed security incident **or suspected credential exposure**; immediate material business risk with no workaround |
| P2 High | major feature unavailable or materially degraded, but core operations remain possible or a workaround exists |
| P3 Normal | minor defect, how-to question, configuration request, or limited operational impact |

**Derived severity for the open tickets, with the matching clause:**

| ticket | account | derived | matching definition text |
|---|---|---|---|
| TKT-501 | Northstar | **P1** | "Every user … gets HTTP 500 when creating any shipment" ↔ "complete production outage preventing all shipment creation for a customer" |
| TKT-502 | LumenWorks | **P2** | bulk upload fails, "creating shipments one-by-one still works" + KI-208 workaround ↔ "degraded … core operations remain possible or a workaround exists" |
| TKT-503 | Beacon Retail | **P3** | "How do we change the billing contact?" ↔ "how-to question, configuration request" |
| TKT-504 | Northstar | **P3** | status-display lag covered by KI-211 ↔ "minor defect … limited operational impact" |
| TKT-505 | Axis Labs | **P1** | "accidentally posted a screenshot containing a production API key" ↔ "suspected credential exposure" |

---

## R5 — First-response SLA targets

**Evidence:** SRC-01 p.1 §3 (defaults), SRC-05 §1 and SRC-06 §1 (agreements),
SRC-02 (deprecated — excluded).

| Source | Plan/Account | P1 | P2 | P3 |
|---|---|---|---|---|
| SRC-01 v3 CURRENT | Enterprise | 30 min, 24x7 | 2 h | 1 business day |
| SRC-01 v3 CURRENT | Growth | 2 business hours | 4 business hours | 2 business days |
| SRC-01 v3 CURRENT | Standard | 4 business hours | 1 business day | 2 business days |
| SRC-05 agreement | ACCT-001 Northstar | **15 min, 24x7** | 1 h | 8 business hours |
| SRC-06 agreement | ACCT-002 LumenWorks | 2 business hours | 4 business hours | 2 business days; **no weekend or after-hours coverage** |
| ~~SRC-02 v2~~ | ~~Enterprise~~ | ~~1 hour~~ | ~~4 hours~~ | ~~2 business days~~ | *(deprecated, excluded)* |

**R5.1 — Escalation.** SRC-01 §4: P1 escalates immediately; a breached target
must be stated plainly and escalation recommended, not hidden.

**R5.2 — Measurable limitation.** The workbook has no `first_response_at`
column, so actual compliance is unknowable. The system can only compute the
**deadline** and whether the snapshot has passed it with no recorded response.
Every SLA answer must say so.

**Verified — 24x7 targets (exactly computable):**

| ticket | account | sev | created | source | deadline | at snapshot 11:00 |
|---|---|---|---|---|---|---|
| TKT-501 | Northstar Ent. | P1 | 10:30 | **SRC-05 agreement, 15 min** | 10:45 | **BREACHED by 15 min** |
| TKT-501 | *(if v3 default were used)* | P1 | 10:30 | SRC-01, 30 min | 11:00 | exactly at deadline — not breached |
| TKT-501 | *(if deprecated v2 were used)* | P1 | 10:30 | SRC-02, 60 min | 11:30 | 30 min remaining |
| TKT-505 | Axis Labs Ent. | P1 | 08:30 | **SRC-01 v3, 30 min** (no agreement) | 09:00 | **BREACHED by 120 min** |

TKT-501 is the sharpest source-selection test in the pack: the same ticket reads
as *breached*, *exactly on the line*, or *comfortably fine* depending on which
of three sources is used.

**Business-hour targets (TKT-502, TKT-503, TKT-504): not computable — see G1.**

---

## R6 — Product capabilities and known issues

**Evidence:** SRC-04 p.1.

- Bulk Upload: Growth + Enterprise, up to **5,000 rows**; not included on Standard (§1).
- `KI-208` (Investigating, opened 2026-08-10): intermittent bulk-upload failures
  above ~3,000 rows **even though the supported limit remains 5,000**; workaround
  split below 3,000 rows; single shipment creation unaffected (§2).
- `KI-211` (Monitoring, opened 2026-08-12): SwiftShip pickup webhooks up to 20
  min late; a parcel may be collected while ParcelPilot still shows `BOOKED`;
  **verify carrier status before telling a customer a pickup did not occur** (§2).
- `KI-176` resolved 2026-07-18: must not be used to explain new incidents without
  specifically matching evidence (§3).

---

## R7 — Historical resolutions are not authority

**Evidence:** SRC-01 §1, SRC-03 (implicitly), README "Important" row.

Both closed tickets carry resolutions that **current sources contradict**:

| ticket | historical resolution | current truth | contradicting source |
|---|---|---|---|
| TKT-450 (Northstar, 2026-07-12) | "a INR 250 cancellation fee applied after 30 minutes" | Northstar pays **no** cancellation fee on a pre-pickup BOOKED shipment at any elapsed time | SRC-05 §2 |
| TKT-451 (LumenWorks, 2026-08-11) | "Growth plan only supports 3,000 rows" | Growth supports **5,000 rows**; the ~3,000-row failure is bug `KI-208`, not a plan limit | SRC-04 §1, §2 |

Both must be surfaced as *known-incorrect prior guidance* when retrieved, never
repeated as policy.

---

## Material conflicts to model explicitly

| # | Source A (wins) | Source B | Scope | Outcome delta |
|---|---|---|---|---|
| C1 | SRC-05 §2 agreement | SRC-03 §1 SOP | ACCT-001 | ORD-1001 fee: INR 0 vs INR 250 |
| C2 | SRC-06 §3 agreement | SRC-03 §2 SOP | ACCT-002 | ORD-2002 credit: INR 300 vs INR 240; and at 3 h delay, **credit vs no credit** |
| C3 | SRC-05 §1 agreement | SRC-01 §3 policy | ACCT-001 | TKT-501: breached vs on the line |
| C4 | SRC-01 v3 | SRC-02 v2 (deprecated) | all | Enterprise P1 30 min vs 60 min |
| C5 | SRC-04 §1 product doc | TKT-451 historical | ACCT-002 | 5,000-row limit vs incorrect 3,000-row claim |
| C6 | SRC-05 §2 agreement | TKT-450 historical | ACCT-001 | no fee vs incorrect INR 250 claim |

---

## Gaps — where the pack is silent (do **not** invent)

| # | Gap | Consequence |
|---|---|---|
| **G1** | **"Business hours" and "business day" are never defined**, nor is a holiday calendar — yet most SLA targets use them, and the snapshot falls on a **Sunday**. | Business-hour SLA results must be `CONDITIONAL` with the assumed calendar stated. Configurable, never hard-coded. |
| G2 | LumenWorks "no weekend or after-hours support coverage" has no start-of-coverage definition. | Same as G1; a LumenWorks ticket raised Sunday cannot get an exact deadline. |
| G3 | No `first_response_at` field. | SLA compliance is unmeasurable; only deadline vs snapshot is. |
| G4 | "Monthly aggregate" credits (R3.3) has no ledger — no credits-issued table exists. | The Northstar 5,000 cap cannot be evaluated against history; state the cap and flag it as unverifiable from the pack. |
| G5 | No documented procedure for changing a billing contact (TKT-503's actual question). | Genuine `insufficient_evidence` case. |
| G6 | No procedure for a suspected API-key exposure beyond severity (TKT-505). | Severity and escalation are answerable; remediation steps are not. |
| G7 | No definition of the return-to-origin workflow beyond its name. | Can name the workflow, cannot describe its steps. |
| G8 | `premium_support` and `last_customer_message_at` are defined by no rule. | Orphan fields; no entitlement or SLA may be derived from them. |
