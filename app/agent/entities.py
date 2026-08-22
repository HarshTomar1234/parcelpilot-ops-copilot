"""Deterministic entity resolution (Phase 3 s6). Explicit IDs are extracted
by a generic <letters>-<digits> shape - never a literal prefix like
"ORD-" - because the ID *convention* itself is per-deployment data, not a
constant of the domain (the fixture corpus deliberately uses FXO-/FXT-/FX-
instead of the real pack's ORD-/TKT-/ACCT- to prove this; see
tests/fixtures/seed_fixture_db.py). Each candidate token is verified
against the real repository (order, then ticket, then account) and
classified by whichever lookup actually succeeds, scoped by the caller's
authorization. A token that matches the ID shape but does not exist, or
that the caller cannot see, is dropped, not silently trusted from the regex
match alone. Account names are resolved by a scoped, case-insensitive
substring match against accounts.account_name - never a hardcoded mapping
of real company names.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable

from pydantic import BaseModel, ConfigDict

from app.authorization.context import AuthContext
from app.errors import NotAuthorizedError, UnknownEntityError
from app.structured_data.repository import get_account, get_order, get_ticket
from app.time.clock import SnapshotClock, tz_of

_ID_TOKEN = re.compile(r"\b[A-Za-z]{2,8}-\d{1,10}\b")


class EntityResolution(BaseModel):
    model_config = ConfigDict(frozen=True)

    order_ids: list[str] = []
    ticket_ids: list[str] = []
    account_ids: list[str] = []
    ambiguous_account_names: list[str] = []  # matched >1 account, needs clarification
    unresolved_mentions: list[str] = []  # matched the ID pattern but not found/authorized

    @property
    def is_empty(self) -> bool:
        return not (self.order_ids or self.ticket_ids or self.account_ids)

    @property
    def needs_clarification(self) -> bool:
        return bool(self.ambiguous_account_names)


def resolve_entities(
    question: str, conn: sqlite3.Connection, auth: AuthContext, clock: SnapshotClock
) -> EntityResolution:
    tz = tz_of(clock)
    checkers: tuple[tuple[str, Callable[[str], object]], ...] = (
        ("order", lambda eid: get_order(conn, eid, auth, tz)),
        ("ticket", lambda eid: get_ticket(conn, eid, auth, tz)),
        ("account", lambda eid: get_account(conn, eid, auth)),
    )
    buckets: dict[str, list[str]] = {"order": [], "ticket": [], "account": []}
    unresolved: list[str] = []
    seen: set[str] = set()

    for match in _ID_TOKEN.findall(question):
        entity_id = match.upper()
        if entity_id in seen:
            continue
        seen.add(entity_id)
        resolved = False
        for kind, checker in checkers:
            try:
                checker(entity_id)
            except UnknownEntityError:
                continue
            except NotAuthorizedError:
                break  # this ID is real, just not visible - stop, don't misclassify it
            else:
                buckets[kind].append(entity_id)
                resolved = True
                break
        if not resolved:
            unresolved.append(entity_id)

    order_ids, ticket_ids, account_ids = buckets["order"], buckets["ticket"], buckets["account"]

    # Fuzzy account-name matching only when no explicit ID of any kind was
    # found - an explicit ID reference is always more reliable than a name
    # guess, and we should not overwrite it.
    ambiguous_names: list[str] = []
    if not (order_ids or ticket_ids or account_ids):
        name_matches = _match_account_names(question, conn, auth)
        if len(name_matches) == 1:
            account_ids = [name_matches[0]]
        elif len(name_matches) > 1:
            ambiguous_names = name_matches

    return EntityResolution(
        order_ids=order_ids,
        ticket_ids=ticket_ids,
        account_ids=account_ids,
        ambiguous_account_names=ambiguous_names,
        unresolved_mentions=unresolved,
    )


def _match_account_names(question: str, conn: sqlite3.Connection, auth: AuthContext) -> list[str]:
    rows = conn.execute("SELECT account_id, account_name FROM accounts").fetchall()
    lowered = question.lower()
    matches = []
    for row in rows:
        name = row["account_name"]
        # Require a reasonably specific match (the full name or a
        # multi-word prefix) to avoid one common word matching everything.
        if len(name) >= 4 and name.lower() in lowered and auth.allows_account(row["account_id"]):
            matches.append(row["account_id"])
    return matches
