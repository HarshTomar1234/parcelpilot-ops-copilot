"""The verified evidence pack (Phase 3 s14) built from actual ToolResult
outputs collected during plan execution - never from anything the LLM
said. This is what response_composer.py renders over; the final LLM call
should behave primarily as an explainer of this pack, not a second source
of facts.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.agent.entities import EntityResolution
from app.agent.intent import Intent
from app.agent.tool_result import ToolResult
from app.documents.retrieval import DocumentSearchResult
from app.domain.evidence import cite_structured
from app.domain.outcomes import Conflict, EvidenceRef, TrustState
from app.models.structured import Account, Order, Ticket


def _cite_record(record: Account | Order | Ticket) -> EvidenceRef:
    if isinstance(record, Account):
        return cite_structured("accounts", record.account_id)
    if isinstance(record, Order):
        return cite_structured("orders", record.order_id)
    return cite_structured("tickets", record.ticket_id)


class EvidencePack(BaseModel):
    model_config = ConfigDict(frozen=True)

    question: str
    intent: Intent
    entities: EntityResolution
    structured_facts: list[dict] = []
    document_evidence: list[DocumentSearchResult] = []
    domain_results: list[dict] = []
    domain_trust_states: list[TrustState] = []
    citations: list[EvidenceRef] = []
    assumptions: list[str] = []
    conflicts: list[Conflict] = []
    needs_human_review: bool = False
    snapshot_time: datetime
    account_scope: list[str] | None


def build_evidence_pack(
    question: str,
    intent: Intent,
    entities: EntityResolution,
    tool_results: list[ToolResult],
    snapshot_time: datetime,
    account_scope: list[str] | None,
) -> EvidencePack:
    structured_facts: list[dict] = []
    document_evidence: list[DocumentSearchResult] = []
    domain_results: list[dict] = []
    domain_trust_states: list[TrustState] = []
    citations: list[EvidenceRef] = []
    assumptions: list[str] = []
    conflicts: list[Conflict] = []
    needs_human_review = False

    for result in tool_results:
        if not result.success or result.output is None:
            continue
        output = result.output
        if result.tool_name == "lookup_structured_data":
            # A record fetched here (e.g. an Account's real status/plan) is
            # the ground truth for any question that never reaches
            # calculate_support_outcome (order/ticket/account investigation
            # intents). Both the raw fields (for the prompt) and a citation
            # (so the model can reference it) are required, or the model has
            # nothing but generic document text to answer from - reproduced
            # live as a real account-status hallucination before this fix.
            for record in output.records:
                structured_facts.append(record.model_dump(mode="json"))
                citations.append(_cite_record(record))
        elif result.tool_name == "search_documents":
            document_evidence.extend(output.results)
            for doc in output.results:
                citations.append(
                    EvidenceRef(
                        kind="document",
                        source_id=doc.source_id,
                        locator=f"p{doc.page}:{doc.section}",
                        note=doc.snippet,
                    )
                )
        elif result.tool_name == "calculate_support_outcome":
            if output.result is not None:
                domain_results.append(output.result)
            domain_trust_states.append(output.trust_state)
            citations.extend(output.evidence)
            assumptions.extend(output.assumptions)
            conflicts.extend(output.conflicts)
            needs_human_review = needs_human_review or output.needs_human_review

    # A calculation (e.g. evaluate_cancellation) already cites the same
    # structured record its own lookup_structured_data step fetched, so the
    # citation just added above for that record would otherwise duplicate
    # it - keep the first occurrence only, by (source_id, locator).
    seen_citation_keys: set[tuple[str, str | None]] = set()
    deduped_citations: list[EvidenceRef] = []
    for ref in citations:
        key = (ref.source_id, ref.locator)
        if key in seen_citation_keys:
            continue
        seen_citation_keys.add(key)
        deduped_citations.append(ref)
    citations = deduped_citations

    return EvidencePack(
        question=question,
        intent=intent,
        entities=entities,
        structured_facts=structured_facts,
        document_evidence=document_evidence,
        domain_results=domain_results,
        domain_trust_states=domain_trust_states,
        citations=citations,
        assumptions=assumptions,
        conflicts=conflicts,
        needs_human_review=needs_human_review,
        snapshot_time=snapshot_time,
        account_scope=account_scope,
    )
