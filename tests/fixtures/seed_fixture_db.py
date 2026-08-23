"""A small, entirely fabricated, version-controlled dataset that exercises
the same code paths and rule shapes as the real assessment pack (a
cancellation waiver, an agreement that declines to override, a deprecated
source, a historical resolution that contradicts current policy, a
business-hour SLA target that cannot be computed exactly) without being
derived from or resembling the real confidential source pack in any
identifying way (Phase 3 pre-flight 2.1).

None of these company names, account IDs, order IDs, ticket IDs, dates,
fees, or thresholds appear anywhere in the real source pack or in
data/source_manifest.json/docs/initial_rules.md - every number here was
chosen independently for this fixture.

This does NOT go through PDF parsing or scripts/ingest_sources.py - it
INSERTs directly into the real schema (app/db/schema.sql). PDF-parsing
logic itself is already covered by pack-independent unit tests using
synthetic text (tests/unit/test_pdf_parser.py, test_sla_table.py); this
fixture exists to exercise everything downstream of ingestion (retrieval,
structured lookups, policy applicability, domain calculations, tool
contracts, authorization) without needing the real pack or a real PDF.

Never call a test built on this fixture "full evaluation" or "retrieval
evaluation" - see tests/fixture_backed/README.md and .github/workflows/ci.yml.
"""

from __future__ import annotations

import sqlite3

from app.domain.cancellation import CancellationFeeRule
from app.domain.service_credit import ServiceCreditRule
from app.policy.applicability import AgreementOverride, ClauseTopic

FIXTURE_SNAPSHOT = "2026-02-02T09:00:00+05:30"  # a Monday - deliberately unlike the real Sunday
FIXTURE_CURRENCY = "INR"

_SOURCES = [
    # source_id, filename, source_type, status, version, effective_date, expiry_date,
    # supersedes, superseded_by, scope_kind, scope_account_id, authority_class,
    # checksum, bytes, provenance
    ("FIX-01", "fixture_support_policy_v2.pdf", "support_policy", "CURRENT", "v2",
     "2026-01-01", None, "FIX-02", None, "global", None, "POLICY_CURRENT",
     "sha256:fixture-fix01", 1000, "tests/fixtures (synthetic, not the real pack)"),
    ("FIX-02", "fixture_support_policy_v1.pdf", "support_policy", "DEPRECATED", "v1",
     "2025-01-01", None, None, "FIX-01", "global", None, "DEPRECATED",
     "sha256:fixture-fix02", 1000, "tests/fixtures (synthetic, not the real pack)"),
    ("FIX-03", "fixture_cancellation_credit_sop.pdf", "sop", "CURRENT", "v2",
     "2026-01-15", None, None, None, "global", None, "POLICY_CURRENT",
     "sha256:fixture-fix03", 1000, "tests/fixtures (synthetic, not the real pack)"),
    ("FIX-04", "fixture_product_guide.pdf", "product_doc", "CURRENT", None,
     "2026-01-20", None, None, None, "global", None, "PRODUCT_DOC",
     "sha256:fixture-fix04", 1000, "tests/fixtures (synthetic, not the real pack)"),
    ("FIX-05", "fixture_meridian_agreement.pdf", "agreement", "ACTIVE", None,
     "2026-01-01", "2026-12-31", None, None, "account", "FX-001", "AGREEMENT",
     "sha256:fixture-fix05", 1000, "tests/fixtures (synthetic, not the real pack)"),
    ("FIX-06", "fixture_cobalt_agreement.pdf", "agreement", "ACTIVE", None,
     "2026-01-01", "2026-12-31", None, None, "account", "FX-002", "AGREEMENT",
     "sha256:fixture-fix06", 1000, "tests/fixtures (synthetic, not the real pack)"),
]

# (chunk_id, source_id, page, section, text)
_CHUNKS = [
    ("FIX-01:p1:1", "FIX-01", 1, "1", "Default first-response targets by plan and severity."),
    ("FIX-01:p1:2", "FIX-01", 1, "2",
     "P1 Critical: complete outage preventing all shipment creation for a customer, "
     "or a confirmed security incident, or suspected credential exposure, with no workaround."),
    ("FIX-02:p1:1", "FIX-02", 1, "1", "Deprecated default first-response targets. Do not use."),
    ("FIX-03:p1:1", "FIX-03", 1, "1",
     "BOOKED orders not yet picked up may be cancelled free within 20 minutes of booking. "
     "After 20 minutes, an INR 150 fee applies unless a signed agreement explicitly waives it."),
    ("FIX-03:p1:2", "FIX-03", 1, "2",
     "A failed-pickup service credit applies when the pickup is more than 3 hours past the "
     "scheduled window, the carrier is at fault, and there is no customer-caused issue. "
     "Default credit is the lower of INR 400 or 8 percent of the shipment fee."),
    ("FIX-04:p1:1", "FIX-04", 1, "1",
     "Bulk upload is supported up to 4000 rows per file on Growth and Enterprise plans."),
    ("FIX-04:p1:2", "FIX-04", 1, "2",
     "Known issue FXKI-01: intermittent bulk-upload failures above 2000 rows, even though "
     "the supported limit remains 4000. Workaround: split uploads below 2000 rows."),
    ("FIX-05:p1:1", "FIX-05", 1, "1",
     "Meridian Freight first-response targets replace the default policy."),
    ("FIX-05:p1:2", "FIX-05", 1, "2",
     "Meridian Freight may cancel any BOOKED shipment before pickup with no fee, "
     "regardless of how long ago it was booked."),
    ("FIX-05:p1:3", "FIX-05", 1, "3",
     "Meridian Freight's monthly aggregate service credits are capped at INR 3000; "
     "the per-credit threshold and amount are unchanged."),
    ("FIX-06:p1:1", "FIX-06", 1, "1",
     "Cobalt Express first-response targets replace the default policy."),
    ("FIX-06:p1:2", "FIX-06", 1, "2",
     "No special cancellation-fee waiver applies. Use the current SOP."),
    ("FIX-06:p1:3", "FIX-06", 1, "3",
     "If a pickup is more than 5 hours past the scheduled window, the carrier is at fault, "
     "and the customer is not at fault, Cobalt Express receives a fixed INR 250 credit. "
     "This replaces the default threshold and amount."),
]

# (source_id, scope_kind, plan, account_id, severity, target_text,
#  target_minutes, is_24x7, requires_business_calendar)
_SLA_TARGETS = [
    ("FIX-01", "plan", "Enterprise", None, "P1", "20 minutes, 24x7", 20, 1, 0),
    ("FIX-01", "plan", "Enterprise", None, "P2", "90 minutes", 90, 0, 0),
    ("FIX-01", "plan", "Enterprise", None, "P3", "1 business day", None, 0, 1),
    ("FIX-01", "plan", "Growth", None, "P1", "3 business hours", None, 0, 1),
    ("FIX-01", "plan", "Growth", None, "P2", "5 business hours", None, 0, 1),
    ("FIX-01", "plan", "Growth", None, "P3", "2 business days", None, 0, 1),
    ("FIX-01", "plan", "Standard", None, "P1", "5 business hours", None, 0, 1),
    ("FIX-01", "plan", "Standard", None, "P2", "1 business day", None, 0, 1),
    ("FIX-01", "plan", "Standard", None, "P3", "3 business days", None, 0, 1),
    ("FIX-02", "plan", "Enterprise", None, "P1", "45 minutes", 45, 0, 0),
    ("FIX-02", "plan", "Enterprise", None, "P2", "3 hours", 180, 0, 0),
    ("FIX-02", "plan", "Enterprise", None, "P3", "2 business days", None, 0, 1),
    ("FIX-02", "plan", "Growth", None, "P1", "6 business hours", None, 0, 1),
    ("FIX-02", "plan", "Growth", None, "P2", "1 business day", None, 0, 1),
    ("FIX-02", "plan", "Growth", None, "P3", "3 business days", None, 0, 1),
    ("FIX-02", "plan", "Standard", None, "P1", "1 business day", None, 0, 1),
    ("FIX-02", "plan", "Standard", None, "P2", "2 business days", None, 0, 1),
    ("FIX-02", "plan", "Standard", None, "P3", "4 business days", None, 0, 1),
    ("FIX-05", "account", None, "FX-001", "P1", "10 minutes, 24x7", 10, 1, 0),
    ("FIX-05", "account", None, "FX-001", "P2", "45 minutes", 45, 0, 0),
    ("FIX-05", "account", None, "FX-001", "P3", "4 business hours", None, 0, 1),
    ("FIX-06", "account", None, "FX-002", "P1", "1 business hour", None, 0, 1),
    ("FIX-06", "account", None, "FX-002", "P2", "2 business hours", None, 0, 1),
    ("FIX-06", "account", None, "FX-002", "P3", "1 business day", None, 0, 1),
]

# (account_id, account_name, plan, status, csm, contract_file, premium_support, notes)
_ACCOUNTS = [
    ("FX-001", "Meridian Freight", "Enterprise", "active", "Fixture CSM A",
     "fixture_meridian_agreement.pdf", 1, "Fixture account for CI - not a real customer."),
    ("FX-002", "Cobalt Express", "Growth", "active", "Fixture CSM B",
     "fixture_cobalt_agreement.pdf", 0, "Fixture account for CI - not a real customer."),
    ("FX-003", "Harbor Retail", "Standard", "active", "Fixture CSM C",
     None, 0, "Fixture account for CI - not a real customer."),
    ("FX-004", "Vertex Labs", "Enterprise", "active", "Fixture CSM A",
     None, 0, "Fixture account for CI - not a real customer."),
]

# (order_id, account_id, carrier, status, booked_at, pickup_window_start,
#  pickup_window_end, pickup_actual_at, shipment_fee_inr, carrier_fault,
#  customer_fault, cancellation_requested_at, notes)
_ORDERS = [
    ("FXO-1001", "FX-001", "FixtureCarrier", "BOOKED",
     "2026-02-02T07:00:00+05:30", "2026-02-02T08:00:00+05:30", "2026-02-02T09:00:00+05:30",
     None, 2000.0, 0, 0, "2026-02-02T07:40:00+05:30", "Cancel requested 40 min after booking."),
    ("FXO-1002", "FX-001", "FixtureCarrier", "PICKED_UP",
     "2026-02-02T06:00:00+05:30", "2026-02-02T06:30:00+05:30", "2026-02-02T07:30:00+05:30",
     "2026-02-02T07:00:00+05:30", 2500.0, 0, 0, "2026-02-02T07:50:00+05:30",
     "Cancel requested after pickup."),
    ("FXO-2001", "FX-002", "FixtureCarrier", "BOOKED",
     "2026-02-02T07:00:00+05:30", "2026-02-02T08:00:00+05:30", "2026-02-02T09:00:00+05:30",
     None, 1500.0, 0, 0, "2026-02-02T07:35:00+05:30", "Cancel requested 35 min after booking."),
    ("FXO-2002", "FX-002", "FixtureCarrier", "BOOKED",
     "2026-02-02T00:00:00+05:30", "2026-02-02T01:00:00+05:30", "2026-02-02T02:00:00+05:30",
     None, 3000.0, 1, 0, None, "Pickup missed, carrier at fault, still not picked up at snapshot."),
    ("FXO-3001", "FX-003", "FixtureCarrier", "BOOKED",
     "2026-02-02T07:00:00+05:30", "2026-02-02T08:00:00+05:30", "2026-02-02T09:00:00+05:30",
     None, 1200.0, 0, 0, "2026-02-02T07:10:00+05:30", "Cancel requested 10 min after booking."),
    ("FXO-4001", "FX-004", "FixtureCarrier", "DELIVERED",
     "2026-01-30T07:00:00+05:30", "2026-01-31T08:00:00+05:30", "2026-01-31T09:00:00+05:30",
     "2026-01-31T08:20:00+05:30", 1800.0, 0, 0, None, "Completed delivery."),
]

# (ticket_id, account_id, created_at, status, subject, description, channel, assigned_to,
#  last_customer_message_at, historical_resolution)
_TICKETS = [
    ("FXT-501", "FX-001", "2026-02-02T08:30:00+05:30", "open",
     "All shipment creation is failing",
     "Every user at Meridian gets a 500 error when creating any shipment. "
     "Existing shipments can still be viewed.",
     "email", "Fixture Agent 1", "2026-02-02T08:45:00+05:30", None),
    ("FXT-502", "FX-002", "2026-02-02T08:00:00+05:30", "open",
     "Bulk upload fails above 2000 rows",
     "The CSV upload fails past roughly 2000 rows. Creating shipments one-by-one still works.",
     "chat", "Fixture Agent 2", "2026-02-02T08:20:00+05:30", None),
    ("FXT-503", "FX-003", "2026-02-02T08:10:00+05:30", "open",
     "How do we change the billing contact?",
     "Customer wants to replace the billing-contact email on their account.",
     "email", "Fixture Agent 1", "2026-02-02T08:10:00+05:30", None),
    ("FXT-504", "FX-001", "2026-02-02T08:40:00+05:30", "open",
     "Order still shows BOOKED after pickup",
     "Driver collected the parcel a few minutes ago but the order still shows BOOKED.",
     "chat", "Fixture Agent 2", "2026-02-02T08:48:00+05:30", None),
    ("FXT-505", "FX-004", "2026-02-02T07:30:00+05:30", "open",
     "Possible API key exposure",
     "An employee accidentally posted a screenshot containing a production API key "
     "in a public channel.",
     "email", "Fixture Agent 1", "2026-02-02T07:50:00+05:30", None),
    ("FXT-450", "FX-001", "2026-01-05T14:00:00+05:30", "closed",
     "Cancellation fee after 20 minutes",
     "Meridian asked whether a BOOKED shipment could be cancelled 60 minutes after "
     "booking before pickup.",
     "email", "Fixture Agent 2", "2026-01-05T15:00:00+05:30",
     "Agent told the customer an INR 150 cancellation fee applied after 20 minutes."),
    ("FXT-451", "FX-002", "2026-01-10T11:00:00+05:30", "closed",
     "Bulk upload fails for large CSV",
     "Cobalt Express reported failures uploading a 2200-row CSV file.",
     "chat", "Fixture Agent 1", "2026-01-10T12:00:00+05:30",
     "Agent told the customer the Growth plan only supports 1500 rows."),
]


# --- Policy/domain registries for this fixture universe --------------------
# Passed to evaluate_cancellation/evaluate_service_credit/calculate_sla's
# overrides/defaults/fee_rules/credit_rules keyword arguments (see
# app/policy/applicability.py and app/domain/{cancellation,service_credit}.py)
# instead of the real ones - proving those functions are generic over the
# registry's *contents*, not hardcoded to the real pack's IDs.

FIXTURE_DEFAULT_SOURCE: dict[ClauseTopic, tuple[str, str] | None] = {
    ClauseTopic.CANCELLATION_FEE: ("FIX-03", "1"),
    ClauseTopic.SERVICE_CREDIT_THRESHOLD_AND_AMOUNT: ("FIX-03", "2"),
    ClauseTopic.SERVICE_CREDIT_AGGREGATE_CAP: None,
    ClauseTopic.SLA_FIRST_RESPONSE: ("FIX-01", "1"),
}

FIXTURE_AGREEMENT_OVERRIDES: tuple[AgreementOverride, ...] = (
    AgreementOverride(
        "FX-001", "FIX-05", "2", ClauseTopic.CANCELLATION_FEE,
        "Meridian Freight may cancel any BOOKED shipment before pickup with no fee (FIX-05 s2).",
    ),
    AgreementOverride(
        "FX-001", "FIX-05", "3", ClauseTopic.SERVICE_CREDIT_AGGREGATE_CAP,
        "Meridian Freight's monthly aggregate credits are capped at INR 3000 (FIX-05 s3).",
    ),
    AgreementOverride(
        "FX-001", "FIX-05", "1", ClauseTopic.SLA_FIRST_RESPONSE,
        "Meridian Freight's agreement replaces the standard first-response targets (FIX-05 s1).",
    ),
    AgreementOverride(
        "FX-002", "FIX-06", "3", ClauseTopic.SERVICE_CREDIT_THRESHOLD_AND_AMOUNT,
        "Cobalt Express' agreement replaces the default threshold and amount (FIX-06 s3).",
    ),
    AgreementOverride(
        "FX-002", "FIX-06", "1", ClauseTopic.SLA_FIRST_RESPONSE,
        "Cobalt Express' agreement replaces the standard first-response targets (FIX-06 s1).",
    ),
    # No CANCELLATION_FEE entry for FX-002: FIX-06 s2 explicitly declines to
    # override it, mirroring the real pack's LumenWorks/SRC-06 s2 pattern.
)

FIXTURE_FEE_RULES: dict[str, CancellationFeeRule] = {
    "FIX-03": CancellationFeeRule(kind="threshold_fee", threshold_minutes=20, fee_inr=150.0),
    "FIX-05": CancellationFeeRule(kind="full_waiver"),
}

FIXTURE_CREDIT_RULES: dict[str, ServiceCreditRule] = {
    "FIX-03": ServiceCreditRule(
        threshold_hours=3, kind="percentage_with_cap", cap_inr=400.0, percentage=0.08
    ),
    "FIX-06": ServiceCreditRule(threshold_hours=5, kind="fixed_amount", fixed_amount_inr=250.0),
}


def build_fixture_db(conn: sqlite3.Connection) -> None:
    """Populates an already-initialized (schema.sql applied) connection with
    the fixture dataset described above. Idempotent only in the sense that
    it expects an empty database - call on a freshly init_db()'d connection.
    """
    for row in _SOURCES:
        conn.execute(
            "INSERT INTO sources (source_id, filename, source_type, status, version, "
            "effective_date, expiry_date, supersedes, superseded_by, scope_kind, "
            "scope_account_id, authority_class, checksum, bytes, provenance) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            row,
        )

    for chunk_id, source_id, page, section, text in _CHUNKS:
        source = next(s for s in _SOURCES if s[0] == source_id)
        cur = conn.execute(
            "INSERT INTO document_chunks (chunk_id, source_id, page, section, text, "
            "normalized_text, filename, status, source_type, account_scope, "
            "effective_date, authority_class) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                chunk_id, source_id, page, section, text, text,
                source[1], source[3], source[2], source[10], source[5], source[11],
            ),
        )
        conn.execute(
            "INSERT INTO document_chunks_fts (rowid, normalized_text) VALUES (?, ?)",
            (cur.lastrowid, text),
        )

    for row in _SLA_TARGETS:
        conn.execute(
            "INSERT INTO sla_targets (source_id, scope_kind, plan, account_id, severity, "
            "target_text, target_minutes, is_24x7, requires_business_calendar) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            row,
        )

    for row in _ACCOUNTS:
        conn.execute(
            "INSERT INTO accounts (account_id, account_name, plan, status, csm, "
            "contract_file, premium_support, notes) VALUES (?,?,?,?,?,?,?,?)",
            row,
        )

    for row in _ORDERS:
        conn.execute(
            "INSERT INTO orders (order_id, account_id, carrier, status, booked_at, "
            "pickup_window_start, pickup_window_end, pickup_actual_at, shipment_fee_inr, "
            "carrier_fault, customer_fault, cancellation_requested_at, notes) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            row,
        )

    for row in _TICKETS:
        conn.execute(
            "INSERT INTO tickets (ticket_id, account_id, created_at, status, subject, "
            "description, channel, assigned_to, last_customer_message_at, "
            "historical_resolution) VALUES (?,?,?,?,?,?,?,?,?,?)",
            row,
        )

    conn.executemany(
        "INSERT INTO meta (key, value) VALUES (?, ?)",
        [
            ("snapshot_time", FIXTURE_SNAPSHOT),
            ("currency", FIXTURE_CURRENCY),
            ("fixture", "true"),
        ],
    )
    conn.commit()
