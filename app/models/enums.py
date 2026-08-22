"""Enumerations grounded in data/source_manifest.json and the workbook schema.
Values match docs/source_inventory.md and docs/data_dictionary.md exactly -
no value here was invented for convenience.
"""

from __future__ import annotations

from enum import StrEnum


class SourceType(StrEnum):
    SUPPORT_POLICY = "support_policy"
    SOP = "sop"
    PRODUCT_DOC = "product_doc"
    AGREEMENT = "agreement"
    STRUCTURED_DATA = "structured_data"


class SourceStatus(StrEnum):
    CURRENT = "CURRENT"
    DEPRECATED = "DEPRECATED"
    ACTIVE = "ACTIVE"  # agreements use ACTIVE rather than CURRENT in the pack


class AuthorityClass(StrEnum):
    """Precedence order per Support Policy v3 s1 (docs/initial_rules.md R1):
    AGREEMENT > POLICY_CURRENT > PRODUCT_DOC > HISTORICAL (context only).
    DEPRECATED is excluded from answer construction (docs/architecture_decision_record.md ADR-004).
    """

    AGREEMENT = "AGREEMENT"
    POLICY_CURRENT = "POLICY_CURRENT"
    PRODUCT_DOC = "PRODUCT_DOC"
    HISTORICAL = "HISTORICAL"
    DEPRECATED = "DEPRECATED"
    STRUCTURED = "STRUCTURED"

    @property
    def rank(self) -> int | None:
        """Lower rank wins. None = excluded from precedence entirely."""
        return {
            AuthorityClass.AGREEMENT: 1,
            AuthorityClass.POLICY_CURRENT: 2,
            AuthorityClass.PRODUCT_DOC: 3,
            AuthorityClass.HISTORICAL: 4,
        }.get(self)


class ScopeKind(StrEnum):
    GLOBAL = "global"
    ACCOUNT = "account"


class OrderStatus(StrEnum):
    """DRAFT is a valid SOP branch (docs/initial_rules.md R2) even though no
    DRAFT order exists in the supplied workbook (data_dictionary.md anomaly #7)."""

    DRAFT = "DRAFT"
    BOOKED = "BOOKED"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"


class TicketStatus(StrEnum):
    OPEN = "open"
    CLOSED = "closed"


class Severity(StrEnum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"
