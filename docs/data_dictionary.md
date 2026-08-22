# Data Dictionary — ParcelPilot_Assessment_Data.xlsx

Schema below is the **actual** workbook schema, read from the file. Row counts
are the real counts (excluding headers). SHA256 `4e69dbfd…9a11e0a72`.

## Sheet: `README` (5 rows × 2 cols, key/value)

| Key | Value | Type in cell |
|---|---|---|
| *(title)* | ParcelPilot AI Agent Assessment - Structured Data | str |
| Dataset snapshot | `2026-08-16 11:00 Asia/Kolkata` | **str, not a datetime** |
| Currency | INR | str |
| Notes | Synthetic dataset created for a hiring assessment. | str |
| Important | Some historical ticket resolutions may be incorrect. Treat them as historical context, not policy authority. | str |

**Snapshot semantics.** `2026-08-16 11:00 Asia/Kolkata` is the authoritative
reference time for every time-based question. It is stored as free text and must
be parsed (timezone name included), not read as a cell datetime. **2026-08-16 is
a Sunday.**

## Sheet: `accounts` (4 rows × 8 cols)

| Column | Type | Null? | Notes |
|---|---|---|---|
| `account_id` | str | no | PK. Format `ACCT-NNN`. |
| `account_name` | str | no | Northstar Logistics, LumenWorks, Beacon Retail, Axis Labs. |
| `plan` | enum str | no | `Enterprise` (2), `Growth` (1), `Standard` (1). Joins to SLA tables in SRC-01 §3. |
| `status` | enum str | no | `active` for all 4. No inactive example. |
| `csm` | str | no | Free text name. |
| `contract_file` | str | **yes** | Filename of the agreement PDF; empty for ACCT-003/004. The account→agreement join key. |
| `premium_support` | bool | no | `True` only for ACCT-001. **Orphan field — no document defines its meaning. Do not derive entitlements from it.** |
| `notes` | str | no | Human prose; context only, not authority. |

Values:

| account_id | account_name | plan | contract_file | premium_support |
|---|---|---|---|---|
| ACCT-001 | Northstar Logistics | Enterprise | 05_Northstar_Logistics_Enterprise_Agreement.pdf | True |
| ACCT-002 | LumenWorks | Growth | 06_LumenWorks_Service_Agreement.pdf | False |
| ACCT-003 | Beacon Retail | Standard | *(empty)* | False |
| ACCT-004 | Axis Labs | Enterprise | *(empty)* | False |

## Sheet: `orders` (6 rows × 13 cols)

| Column | Type | Null? | Notes |
|---|---|---|---|
| `order_id` | str | no | PK, `ORD-NNNN`. First digit tracks the account number. |
| `account_id` | str | no | FK → `accounts`. **The authorization scope key.** |
| `carrier` | str | no | SwiftShip (3), BlueDart Pro (1), RoadRunner (2). `SwiftShip` is the carrier named in KI-211. |
| `status` | enum str | no | `BOOKED` (4), `PICKED_UP` (1), `DELIVERED` (1). **No `DRAFT` or cancelled row exists**, though the SOP defines DRAFT. |
| `booked_at` | datetime | no | Naive; assumed Asia/Kolkata. Cancellation-window anchor. |
| `pickup_window_start` | datetime | no | Naive. |
| `pickup_window_end` | datetime | no | Naive. **Service-credit delay anchor.** |
| `pickup_actual_at` | datetime | **yes** | Null for all 4 BOOKED orders. Null + carrier fault = still-accruing delay. |
| `shipment_fee_inr` | float | no | 1200.0 – 5100.0. Input to the 10% default credit. |
| `carrier_fault` | bool | no | `True` only for ORD-2002. Service-credit precondition. |
| `customer_fault` | bool | no | `False` for all rows. Service-credit disqualifier. |
| `cancellation_requested_at` | datetime | **yes** | Null for ORD-2002, ORD-4001. Compared against `booked_at` for the 30-minute rule. |
| `notes` | str | no | Prose; context only. |

**Fault modelling caveat.** `carrier_fault` and `customer_fault` are separate
booleans, so "unknown" is not representable — a `False` could mean "not at
fault" or "not yet determined". SOP §3 forbids promising a credit when fault is
unknown, so the system must treat a fully-`False` row on a delayed pickup as a
verification prompt rather than silently reading it as "carrier not at fault".

## Sheet: `tickets` (7 rows × 10 cols)

| Column | Type | Null? | Notes |
|---|---|---|---|
| `ticket_id` | str | no | PK, `TKT-NNN`. |
| `account_id` | str | no | FK → `accounts`. **Authorization scope key.** |
| `created_at` | datetime | no | Naive. **SLA first-response clock start.** |
| `status` | enum str | no | `open` (5), `closed` (2). |
| `subject` | str | no | Short title. |
| `description` | str | no | Prose. **The severity signal** — classified against SRC-01 §2. |
| `channel` | enum str | no | `email` (4), `chat` (3). No SLA rule depends on channel. |
| `assigned_to` | str | no | `Rohit` (3), `Maya` (3)… free text, not joined to any user table. |
| `last_customer_message_at` | datetime | no | Present on all rows. **No policy in the pack defines a rule over this field** — no follow-up-response SLA exists. Orphan for rule purposes. |
| `historical_resolution` | str | **yes** | Populated only on the 2 `closed` tickets. **`HISTORICAL` authority class — context only, known to contain incorrect guidance.** |

**No severity column exists.** Severity is *derived* from `description` against
SRC-01 §2 and is therefore an inference the system must show its reasoning for,
not a fact it can cite from data.

**No `resolved_at` / `first_response_at` column exists.** The workbook records
when a ticket was created but never when support first responded. SLA
*compliance* therefore cannot be measured; only the **deadline** and whether the
snapshot time is past it (an *elapsed-without-recorded-response* breach). This
limitation must be stated in any SLA answer.

## Relationships

```
accounts (account_id)
   ├──< orders.account_id
   ├──< tickets.account_id
   └──> contract_file ──> document source (SRC-05 / SRC-06)
```

Referential integrity holds: every `orders.account_id` and `tickets.account_id`
resolves to an existing account. There is **no order↔ticket foreign key** —
`TKT-504` refers to a SwiftShip order in prose only, so linking a ticket to an
order requires text inference and must be presented as an inference.

## Data-quality anomalies (verified, not assumed)

| # | Finding | Impact |
|---|---|---|
| 1 | `ORD-1002` has `cancellation_requested_at` 10:20 **after** `pickup_actual_at` 09:35 | Legitimate: cancel requested post-pickup. Must route to the PICKED_UP branch, not the 30-minute branch. Naive `booked_at`-delta logic gets this wrong. |
| 2 | `ORD-2002` pickup window ended 06:30 but status is still `BOOKED` at the 11:00 snapshot with `pickup_actual_at` null | Delay is **still accruing**. Delay must be measured from the snapshot, not from a pickup that never happened. |
| 3 | `customer_fault` is `False` in every row | The disqualifier branch is never exercised by the data. Implement it anyway; note it is untested by the pack. |
| 4 | `premium_support` referenced by no document | Orphan; never use as an entitlement source. |
| 5 | `last_customer_message_at` referenced by no policy | Orphan for rules; usable only as display context. |
| 6 | All datetimes are naive with no timezone column | Assumed Asia/Kolkata to match the README snapshot. Recorded as an explicit assumption. |
| 7 | No `DRAFT` order, no cancelled order, no RTO record | SOP branches exist with no data to exercise them. |
| 8 | Snapshot date is a **Sunday** | Every business-hour/business-day SLA in the pack is affected, and LumenWorks has contractual "no weekend coverage". |
