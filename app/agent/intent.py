"""Deterministic intent resolution (Phase 3 s5). A keyword/entity-shape
classifier, not an LLM call: "do not automatically create an additional
LLM classification call if the planner can safely determine intent in one
[non-LLM] pass... add a separate classifier only if evaluation demonstrates
measurable quality benefit." This is cheaper, faster, fully unit-testable,
and traceable - the single LLM call in the pipeline is reserved for final
answer composition (app/agent/response_composer.py).
"""

from __future__ import annotations

import re
from enum import StrEnum

from app.agent.entities import EntityResolution

_CANCELLATION = re.compile(r"\bcancel(l?ation)?\b", re.IGNORECASE)
_SERVICE_CREDIT = re.compile(r"\b(credit|refund|compensat\w*)\b", re.IGNORECASE)
_SLA = re.compile(r"\b(sla|deadline|breach\w*|first[- ]response|response time)\b", re.IGNORECASE)
_KNOWN_ISSUE = re.compile(r"\b(known issue|bug|ki-\d+|webhook|outage)\b", re.IGNORECASE)
_SEVERITY = re.compile(r"\bsever(ity|e)\b|\bpriorit(y|ize)\b", re.IGNORECASE)


class Intent(StrEnum):
    INFORMATIONAL = "informational"
    ORDER_INVESTIGATION = "order_investigation"
    TICKET_INVESTIGATION = "ticket_investigation"
    ACCOUNT_INVESTIGATION = "account_investigation"
    CANCELLATION = "cancellation"
    SERVICE_CREDIT = "service_credit"
    SLA = "sla"
    SEVERITY = "severity"
    KNOWN_ISSUE = "known_issue"
    MULTI_SOURCE = "multi_source"
    CLARIFICATION = "clarification"
    UNSUPPORTED = "unsupported"


def resolve_intent(question: str, entities: EntityResolution) -> Intent:
    if entities.needs_clarification:
        return Intent.CLARIFICATION
    if not question.strip():
        return Intent.UNSUPPORTED

    signals: list[Intent] = []
    if _CANCELLATION.search(question) and entities.order_ids:
        signals.append(Intent.CANCELLATION)
    if _SERVICE_CREDIT.search(question) and entities.order_ids:
        signals.append(Intent.SERVICE_CREDIT)
    if _SLA.search(question) and entities.ticket_ids:
        signals.append(Intent.SLA)
    if _SEVERITY.search(question) and entities.ticket_ids:
        signals.append(Intent.SEVERITY)
    if _KNOWN_ISSUE.search(question):
        signals.append(Intent.KNOWN_ISSUE)

    if len(signals) > 1:
        return Intent.MULTI_SOURCE
    if signals:
        return signals[0]

    if entities.order_ids:
        return Intent.ORDER_INVESTIGATION
    if entities.ticket_ids:
        return Intent.TICKET_INVESTIGATION
    if entities.account_ids:
        return Intent.ACCOUNT_INVESTIGATION
    return Intent.INFORMATIONAL
