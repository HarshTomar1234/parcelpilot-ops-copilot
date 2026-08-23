# Source Inventory

All findings below were read from the actual files in `D:\AI-Projects\parcelpilot-assessment`
on 2026-08-22. Every PDF is **1 page**, so all page citations are `p.1`;
section numbers carry the real locating precision.

Regenerate the evidence behind this document with:

```
python scripts/inspect_sources.py --source-dir "D:\AI-Projects\parcelpilot-assessment\source-pack" --out build/inspection
```

## Assessment brief

`assessment-brief/CalQuity AI Engineer — Job Description & AI Agent Assessment.docx`

Not a system input — it is the requirement spec. Key constraints it imposes:

- The chatbot must use **only** the supplied data pack as its information base.
- Use the **README snapshot time** as reference time for all time-based questions.
- Historical ticket resolutions are context only and **may be incorrect**.
- Access control must be enforced in the **data/tool layer**, not model instructions.
- At least three distinct tools: document retrieval, structured lookup/calculation, state-changing action.
- State-changing actions require explicit confirmation.
- Multi-step requests must work.
- Two illustrative questions (must not be hard-coded; graders will use other records).
- Two extension problems: proactive issue detection, and trust/reliability.

## Document sources

| id | file | type | status | effective | scope | authority |
|---|---|---|---|---|---|---|
| `SRC-01` | 01_Support_Policy_v3_CURRENT.pdf | support_policy | CURRENT | 2026-05-01 | all accounts | `POLICY_CURRENT` |
| `SRC-02` | 02_Support_Policy_v2_DEPRECATED.pdf | support_policy | DEPRECATED | 2025-01-01 | all accounts | `DEPRECATED` |
| `SRC-03` | 03_Cancellation_and_Service_Credit_SOP_v4.pdf | sop | CURRENT | 2026-06-15 | all accounts | `POLICY_CURRENT` |
| `SRC-04` | 04_Product_Operations_Guide_and_Known_Issues.pdf | product_doc | CURRENT | 2026-08-14 (updated) | all accounts | `PRODUCT_DOC` |
| `SRC-05` | 05_Northstar_Logistics_Enterprise_Agreement.pdf | agreement | ACTIVE | 2026-01-01 → 2026-12-31 | `ACCT-001` only | `AGREEMENT` |
| `SRC-06` | 06_LumenWorks_Service_Agreement.pdf | agreement | ACTIVE | 2026-03-01 → 2027-02-28 | `ACCT-002` only | `AGREEMENT` |
| `SRC-07` | ParcelPilot_Assessment_Data.xlsx | structured_data | CURRENT | snapshot 2026-08-16 11:00 IST | all accounts | `STRUCTURED` |

### SRC-01 — Support Policy v3 (CURRENT)

Effective 1 May 2026, supersedes v2.

- **§1 Scope and source precedence** — states the precedence chain the whole
  system is built on: signed customer agreement → current support policy →
  current product documentation; historical tickets and internal notes are
  context only and may contain incorrect past guidance.
- **§2 Severity definitions** — P1 Critical (complete production outage
  preventing all shipment creation for a customer; confirmed security incident
  or suspected credential exposure; immediate material business risk with no
  workaround). P2 High (major feature unavailable or materially degraded, core
  operations still possible or a workaround exists). P3 Normal (minor defect,
  how-to, configuration request, limited operational impact).
- **§3 Default first-response targets** — Enterprise 30 min 24x7 / 2 h / 1
  business day; Growth 2 business hours / 4 business hours / 2 business days;
  Standard 4 business hours / 1 business day / 2 business days.
- **§4 Escalation** — P1 escalates immediately. If a target is already breached,
  the agent must state the breach and recommend escalation rather than hide
  uncertainty.

**Caveat:** only the Enterprise P1 target is unambiguously clock-based (24x7).
Every other target depends on an undefined business calendar.

### SRC-02 — Support Policy v2 (DEPRECATED)

Effective 1 Jan 2025, superseded by v3 on 1 May 2026. Enterprise P1 is **1 hour**
here vs 30 minutes in v3. The file states it "must not be used as current policy".

**Trap role:** retrieving v2 instead of v3 flips SLA breach outcomes. Excluded
from answers by `authority_class = DEPRECATED`.

### SRC-03 — Cancellation & Service Credit SOP v4 (CURRENT)

Effective 15 June 2026.

- **§1 Order cancellation** — DRAFT free; BOOKED-not-yet-PICKED_UP free within
  30 min of booking, INR 250 after, *unless a customer agreement explicitly
  waives the fee*; PICKED_UP do not cancel, use return-to-origin; DELIVERED
  cannot be cancelled.
- **§2 Failed-pickup service credits** — default eligibility: pickup more than
  **2 hours** past the end of the scheduled pickup window **and** carrier at
  fault **and** no customer-caused issue. Default credit = lower of INR 500 or
  10% of shipment fee. A signed agreement may replace the threshold, amount, or cap.
- **§3 Approval and uncertainty** — any individual credit above INR 1,000 needs
  manager approval; do not promise a credit when fault or timing is unknown;
  when data conflicts, identify the conflict and request verification **before**
  a state-changing action.

§3 is effectively a business requirement for the confirmation workflow.

### SRC-04 — Product Operations Guide & Known Issues (CURRENT)

Updated 14 August 2026.

- **§1 Plan capabilities** — Bulk Upload on Growth and Enterprise, up to
  **5,000 rows** per CSV; Standard has no Bulk Upload. BOOKED = created, pickup
  not yet confirmed; PICKED_UP = pickup confirmed.
- **§2 Known issues** — `KI-208` Bulk Upload failures above ~3,000 rows
  (Investigating, opened 10 Aug 2026; workaround: split below 3,000 rows; the
  supported limit is still 5,000). `KI-211` SwiftShip pickup webhook delay up to
  20 minutes (Monitoring, opened 12 Aug 2026; verify carrier status before
  telling a customer a pickup did not occur).
- **§3 Resolved issue** — `KI-176` address validation, resolved 18 July 2026;
  explicitly must not be used to explain new incidents without matching evidence.

`KI-208` is the counter-evidence that makes historical ticket `TKT-451` wrong.

### SRC-05 — Northstar Logistics Enterprise Agreement

Account `ACCT-001`, term 1 Jan 2026 → 31 Dec 2026, ACTIVE.

- **§1 Support terms** — replaces standard targets: P1 15 minutes 24x7, P2 1 hour, P3 8 business hours.
- **§2 Shipment cancellation** — may cancel **any** BOOKED shipment before
  pickup with **no fee, regardless of how long ago it was booked**. Once
  PICKED_UP, standard return-to-origin applies.
- **§3 Service credits** — monthly aggregate credits capped at **INR 5,000**;
  otherwise the current SOP applies.
- **§4** — dedicated CSM Priya Mehta.

**Scope caveat:** §3 caps the aggregate but does **not** replace the SOP's 2-hour
threshold or credit formula. Do not generalize the §2 cancellation waiver into a
credit waiver.

### SRC-06 — LumenWorks Service Agreement

Account `ACCT-002`, Growth plan, term 1 Mar 2026 → 28 Feb 2027, ACTIVE.

- **§1 Support terms** — P1 2 business hours, P2 4 business hours, P3 2 business
  days, and **no weekend or after-hours support coverage**.
- **§2 Cancellation terms** — explicitly **no** fee waiver; use the current SOP.
- **§3 Failed-pickup credits** — more than **4 hours** past window end + carrier
  fault + no customer fault → fixed **INR 300**. This clause explicitly replaces
  the SOP's default amount **and** timing threshold.

**Scope caveat:** §3 replaces the threshold in *both* directions. A 3-hour
carrier-fault delay earns a credit under the default SOP but **nothing** for
LumenWorks. §2 means an agreement can also *confirm* the default rather than override it.

### SRC-07 — ParcelPilot_Assessment_Data.xlsx

Four sheets: `README`, `accounts`, `orders`, `tickets`. Full schema in
[`data_dictionary.md`](data_dictionary.md).

- **Snapshot: `2026-08-16 11:00 Asia/Kolkata`** — authoritative reference time.
  This date is a **Sunday**, which materially affects every business-hour SLA.
- Currency INR. Synthetic data.
- README explicitly warns that some historical ticket resolutions are incorrect.

## Cross-source caveats

- `accounts.premium_support` is `True` for `ACCT-001` and `False` elsewhere, but
  **no document in the pack defines what premium support entitles**. Treat as an
  orphan field; never derive an entitlement from it.
- `accounts.contract_file` is empty for `ACCT-003` and `ACCT-004`, matching the
  absence of agreements for them. `ACCT-004` is Enterprise with no agreement, so
  standard Enterprise policy applies — a useful contrast against `ACCT-001`.
- The SOP covers `DRAFT` orders and a return-to-origin workflow, but the
  workbook contains no DRAFT order and no RTO records. Those rules are
  implementable but unexercised by the data.
