"""Ambiguous-entity clarification gate (Phase 4 s3). A question whose
keywords suggest a specific-instance intent (cancellation, service credit,
SLA, severity) but names no order/ticket/account, and whose caller's
account scope does not narrow to exactly one account, is genuinely
ambiguous - proceeding with a generic document search and answering
anyway (the Phase 3 behavior) risks answering about a different account's
situation than the one actually meant. This module only decides whether
to ask; it never guesses which account/order was meant.

Known, accepted limitation: a genuinely general policy question phrased
with these same keywords ("What is your cancellation policy?") and no
account context will also trigger this gate rather than being recognized
as not needing a specific instance - distinguishing "asking about an
instance" from "asking about the policy in general" reliably needs more
than a keyword check. Every real question in the golden dataset that
matches these keywords also names a specific order/ticket/account except
the one case this gate exists for (GC-002), so this is a documented
trade-off, not an unnoticed regression.

A bulk/aggregate question ("review every open ticket...") is explicitly
carved out (_AGGREGATE_SIGNALS) rather than gated - it is not ambiguous
about *which* account, it is intentionally asking across many at once,
which is a different (and separately unsupported - the planner is
single-entity per request, see app/agent/planner.py) gap than this gate
exists to catch.
"""

from __future__ import annotations

import re

from app.agent.entities import EntityResolution
from app.authorization.context import AuthContext

_INSTANCE_SIGNALS = re.compile(
    r"\b(cancel(l?ation)?|credit|refund|compensat\w*|sla|breach\w*|first[- ]response|"
    r"deadline|sever(ity|e)|priorit(y|ize))\b",
    re.IGNORECASE,
)
_AGGREGATE_SIGNALS = re.compile(
    r"\b(every|all|each|which ones|across (all|every)|review\b.*\btickets?)\b", re.IGNORECASE
)


def needs_account_clarification(
    question: str, entities: EntityResolution, auth: AuthContext
) -> str | None:
    """Returns a clarification reason, or None if there is enough to
    proceed: an explicit order/ticket, an explicit account, exactly one
    account in the caller's scope, or a bulk/aggregate question that was
    never going to be resolved to one account in the first place."""
    if entities.order_ids or entities.ticket_ids:
        return None  # already has the specific entity these questions need
    if not _INSTANCE_SIGNALS.search(question):
        return None  # not the kind of question that implies one instance
    if _AGGREGATE_SIGNALS.search(question):
        return None  # asking across many records on purpose, not ambiguous about one
    if entities.account_ids:
        return None  # an explicit account was named
    if auth.account_scope is not None and len(auth.account_scope) == 1:
        return None  # only one account this caller could possibly mean

    scope_desc = (
        "any account" if auth.account_scope is None else f"{len(auth.account_scope)} accounts"
    )
    return (
        "this question needs a specific order, ticket, or account to investigate, "
        f"but none was named and the caller's access spans {scope_desc} - please "
        "specify which account, order, or ticket"
    )
