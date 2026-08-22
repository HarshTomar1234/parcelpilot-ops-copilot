"""Source applicability / clause-level override resolution.

This module answers exactly one question: for a given topic and account,
which source's clause governs? It does NOT compute the outcome that clause
implies (docs/domain/*.py owns that) - conflating "who wins" with "what the
winner says" is what would make an agreement's authority look like a
blanket override, which docs/initial_rules.md R1.1 explicitly warns against.

AGREEMENT_OVERRIDES is not invented data: every entry cites the section of
the actual agreement PDF that states it (docs/initial_rules.md R1.1, R2.1,
R2.2, R3.2, R3.3, R5). Absence of an entry is itself meaningful - SRC-06
section 2 explicitly declines to override cancellation terms, so no
CANCELLATION_FEE entry exists for ACCT-002.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.documents.source_repository import get_source


class ClauseTopic(StrEnum):
    CANCELLATION_FEE = "cancellation_fee"
    SERVICE_CREDIT_THRESHOLD_AND_AMOUNT = "service_credit_threshold_and_amount"
    SERVICE_CREDIT_AGGREGATE_CAP = "service_credit_aggregate_cap"
    SLA_FIRST_RESPONSE = "sla_first_response"


@dataclass(frozen=True)
class AgreementOverride:
    account_id: str
    source_id: str
    section: str
    topic: ClauseTopic
    note: str


# Every entry is a direct restatement of a printed agreement clause -
# see docs/initial_rules.md for the citation each note paraphrases.
AGREEMENT_OVERRIDES: tuple[AgreementOverride, ...] = (
    AgreementOverride(
        "ACCT-001", "SRC-05", "2", ClauseTopic.CANCELLATION_FEE,
        "Northstar may cancel any BOOKED shipment before pickup with no fee, "
        "regardless of how long ago it was booked (SRC-05 s2).",
    ),
    AgreementOverride(
        "ACCT-001", "SRC-05", "3", ClauseTopic.SERVICE_CREDIT_AGGREGATE_CAP,
        "Northstar's monthly aggregate service credits are capped at INR 5,000; "
        "the per-credit threshold and amount are unchanged (SRC-05 s3).",
    ),
    AgreementOverride(
        "ACCT-001", "SRC-05", "1", ClauseTopic.SLA_FIRST_RESPONSE,
        "Northstar's agreement replaces the standard first-response targets (SRC-05 s1).",
    ),
    AgreementOverride(
        "ACCT-002", "SRC-06", "3", ClauseTopic.SERVICE_CREDIT_THRESHOLD_AND_AMOUNT,
        "LumenWorks' agreement replaces both the default failed-pickup delay "
        "threshold and credit amount (SRC-06 s3).",
    ),
    AgreementOverride(
        "ACCT-002", "SRC-06", "1", ClauseTopic.SLA_FIRST_RESPONSE,
        "LumenWorks' agreement replaces the standard first-response targets; "
        "no weekend or after-hours coverage (SRC-06 s1).",
    ),
    # No CANCELLATION_FEE entry for ACCT-002: SRC-06 s2 explicitly states
    # "No special cancellation-fee waiver applies." The agreement's silence
    # on this topic is itself the fact, not an omission to fill in.
)

# (source_id, section) a topic falls back to when no agreement addresses it.
# None means there is no default - the concept (e.g. an aggregate cap) only
# exists because an agreement introduces it.
DEFAULT_SOURCE: dict[ClauseTopic, tuple[str, str] | None] = {
    ClauseTopic.CANCELLATION_FEE: ("SRC-03", "1"),
    ClauseTopic.SERVICE_CREDIT_THRESHOLD_AND_AMOUNT: ("SRC-03", "2"),
    ClauseTopic.SERVICE_CREDIT_AGGREGATE_CAP: None,
    ClauseTopic.SLA_FIRST_RESPONSE: ("SRC-01", "3"),
}


class ApplicabilityResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    topic: ClauseTopic
    account_id: str
    winning_source_id: str
    winning_section: str
    overridden_source_id: str | None
    overridden_section: str | None
    reason: str
    needs_human_review: bool = False


def resolve_applicability(
    conn: sqlite3.Connection,
    topic: ClauseTopic,
    account_id: str,
    at: date,
    *,
    overrides: tuple[AgreementOverride, ...] = AGREEMENT_OVERRIDES,
    defaults: dict[ClauseTopic, tuple[str, str] | None] = DEFAULT_SOURCE,
) -> ApplicabilityResult:
    """overrides/defaults default to the real registry above; tests inject a
    separate fixture registry (tests/fixtures/seed_fixture_db.py) to prove
    this function - and every domain module built on it - is generic over
    the registry's *contents*, not hardcoded to the real pack's account/
    source IDs (Phase 3 pre-flight 2.6)."""
    default = defaults[topic]
    override = next(
        (o for o in overrides if o.account_id == account_id and o.topic is topic), None
    )

    if override is None:
        if default is None:
            raise ValueError(f"{topic.value} has no default and no agreement covers {account_id}")
        source_id, section = default
        return ApplicabilityResult(
            topic=topic,
            account_id=account_id,
            winning_source_id=source_id,
            winning_section=section,
            overridden_source_id=None,
            overridden_section=None,
            reason=(
                f"No agreement for {account_id} addresses {topic.value}; default policy applies."
            ),
        )

    agreement = get_source(conn, override.source_id)
    if not agreement.is_active_at(at):
        if default is None:
            raise ValueError(
                f"{override.source_id} is inactive at {at} and {topic.value} "
                "has no default to fall back to"
            )
        source_id, section = default
        return ApplicabilityResult(
            topic=topic,
            account_id=account_id,
            winning_source_id=source_id,
            winning_section=section,
            overridden_source_id=None,
            overridden_section=None,
            reason=(
                f"{override.source_id} is not active at {at} "
                f"({agreement.effective_date}..{agreement.expiry_date}); falling back to default "
                "policy. This account has an agreement whose term does not currently cover the "
                "request - verify before relying on it."
            ),
            needs_human_review=True,
        )

    default_source_id, default_section = default if default else (None, None)
    return ApplicabilityResult(
        topic=topic,
        account_id=account_id,
        winning_source_id=override.source_id,
        winning_section=override.section,
        overridden_source_id=default_source_id,
        overridden_section=default_section,
        reason=override.note,
    )
