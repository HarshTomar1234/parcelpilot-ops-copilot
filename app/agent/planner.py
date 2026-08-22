"""Minimal structured planner (Phase 3 s12). Produces a compact, bounded
list of PlanSteps using only registered tool names (app/agent/registry.py)
- never a free-form or LLM-generated tool invocation. Different intents
produce different tool paths (s13): a pure informational question never
touches calculate_support_outcome, a severity question never touches
service_credit, etc. Deterministic and fully unit-testable, matching the
"no additional LLM call for planning" decision in intent.py.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.agent.entities import EntityResolution
from app.agent.intent import Intent


class PlanStep(BaseModel):
    model_config = ConfigDict(frozen=True)

    tool: str
    purpose: str
    args: dict


class Plan(BaseModel):
    model_config = ConfigDict(frozen=True)

    intent: Intent
    steps: list[PlanStep]


def _lookup_order(order_id: str) -> PlanStep:
    return PlanStep(
        tool="lookup_structured_data",
        purpose=f"resolve order {order_id}",
        args={"kind": "get_order", "entity_id": order_id},
    )


def _lookup_ticket(ticket_id: str) -> PlanStep:
    return PlanStep(
        tool="lookup_structured_data",
        purpose=f"resolve ticket {ticket_id}",
        args={"kind": "get_ticket", "entity_id": ticket_id},
    )


def _lookup_account(account_id: str) -> PlanStep:
    return PlanStep(
        tool="lookup_structured_data",
        purpose=f"resolve account {account_id}",
        args={"kind": "get_account", "entity_id": account_id},
    )


def _search(query: str, purpose: str, *, source_types: list[str] | None = None) -> PlanStep:
    args: dict = {"query": query, "top_k": 5}
    if source_types:
        args["source_types"] = source_types
    return PlanStep(tool="search_documents", purpose=purpose, args=args)


def _calculate(calc_type: str, entity_id: str, purpose: str) -> PlanStep:
    return PlanStep(
        tool="calculate_support_outcome",
        purpose=purpose,
        args={"calculation_type": calc_type, "entity_id": entity_id},
    )


def build_plan(question: str, intent: Intent, entities: EntityResolution) -> Plan:
    steps: list[PlanStep] = []

    if intent is Intent.CANCELLATION:
        for order_id in entities.order_ids:
            steps.append(_lookup_order(order_id))
            purpose = f"cancellation outcome for {order_id}"
            steps.append(_calculate("cancellation", order_id, purpose))
        steps.append(_search(question, "retrieve applicable cancellation policy/agreement"))

    elif intent is Intent.SERVICE_CREDIT:
        for order_id in entities.order_ids:
            steps.append(_lookup_order(order_id))
            purpose = f"service credit outcome for {order_id}"
            steps.append(_calculate("service_credit", order_id, purpose))
        steps.append(_search(question, "retrieve applicable service-credit policy/agreement"))

    elif intent is Intent.SLA:
        for ticket_id in entities.ticket_ids:
            steps.append(_lookup_ticket(ticket_id))
            steps.append(_calculate("sla", ticket_id, f"SLA outcome for {ticket_id}"))
        steps.append(_search(question, "retrieve applicable SLA/first-response policy"))

    elif intent is Intent.SEVERITY:
        for ticket_id in entities.ticket_ids:
            steps.append(_lookup_ticket(ticket_id))
            purpose = f"severity classification for {ticket_id}"
            steps.append(_calculate("severity", ticket_id, purpose))
        steps.append(
            _search(question, "retrieve severity definitions", source_types=["support_policy"])
        )

    elif intent is Intent.KNOWN_ISSUE:
        steps.append(
            _search(
                question,
                "retrieve product documentation / known issues",
                source_types=["product_doc"],
            )
        )

    elif intent is Intent.ORDER_INVESTIGATION:
        for order_id in entities.order_ids:
            steps.append(_lookup_order(order_id))
        steps.append(_search(question, "retrieve any relevant policy context"))

    elif intent is Intent.TICKET_INVESTIGATION:
        for ticket_id in entities.ticket_ids:
            steps.append(_lookup_ticket(ticket_id))
        steps.append(_search(question, "retrieve any relevant policy context"))

    elif intent is Intent.ACCOUNT_INVESTIGATION:
        for account_id in entities.account_ids:
            steps.append(_lookup_account(account_id))
        steps.append(_search(question, "retrieve the account's agreement, if any"))

    elif intent is Intent.MULTI_SOURCE:
        for order_id in entities.order_ids:
            steps.append(_lookup_order(order_id))
        for ticket_id in entities.ticket_ids:
            steps.append(_lookup_ticket(ticket_id))
        steps.append(
            _search(question, "retrieve applicable policy across the referenced entities")
        )
        for order_id in entities.order_ids:
            cancel_purpose = f"cancellation outcome for {order_id}"
            credit_purpose = f"service credit outcome for {order_id}"
            steps.append(_calculate("cancellation", order_id, cancel_purpose))
            steps.append(_calculate("service_credit", order_id, credit_purpose))
        for ticket_id in entities.ticket_ids:
            steps.append(_calculate("sla", ticket_id, f"SLA outcome for {ticket_id}"))

    elif intent is Intent.INFORMATIONAL:
        steps.append(_search(question, "retrieve relevant policy/document evidence"))

    # CLARIFICATION and UNSUPPORTED produce no steps - the orchestrator
    # short-circuits to a terminal state before ever building a plan for them.

    return Plan(intent=intent, steps=steps)
