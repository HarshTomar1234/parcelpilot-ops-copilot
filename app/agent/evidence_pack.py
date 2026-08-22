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
from app.domain.outcomes import Conflict, EvidenceRef, TrustState


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
            structured_facts.extend(record.model_dump(mode="json") for record in output.records)
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
