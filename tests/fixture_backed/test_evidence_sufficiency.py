"""Direct unit tests for app/agent/evidence_sufficiency.py (final release
hardening, finding F4). Uses synthetic DocumentSearchResult objects, not
a real corpus - deterministic, corpus-independent proof of each signal
the gate combines: token overlap, score + margin, and chunk count. The
full end-to-end behavior (through run_agent()/the HTTP API, against real
corpus data) is covered separately in tests/red_team/test_agent_abuse.py
and tests/integration/test_agent_orchestrator.py.
"""

from __future__ import annotations

from datetime import date

from app.agent.evidence_sufficiency import is_document_evidence_sufficient
from app.documents.retrieval import DocumentSearchResult
from app.models.enums import AuthorityClass, SourceStatus, SourceType


def _chunk(snippet: str, score: float) -> DocumentSearchResult:
    return DocumentSearchResult(
        chunk_id="C-1", source_id="SRC-01", filename="f.pdf", page=1, section="1",
        snippet=snippet, score=score, status=SourceStatus.CURRENT,
        source_type=SourceType.SUPPORT_POLICY, authority_class=AuthorityClass.POLICY_CURRENT,
        effective_date=date(2026, 1, 1), account_scope=None,
    )


def test_no_evidence_at_all_is_insufficient():
    assert is_document_evidence_sufficient("What is the cancellation policy?", []) is False


def test_query_with_no_significant_tokens_is_insufficient():
    # every token here is a stopword or too short
    chunk = _chunk("The cancellation fee policy is explained here.", -5.0)
    assert is_document_evidence_sufficient("what is it", [chunk]) is False


def test_strong_token_overlap_is_sufficient_regardless_of_modest_score():
    chunk = _chunk("The cancellation fee policy applies to all orders.", -1.2)
    result = is_document_evidence_sufficient(
        "What is the cancellation fee policy?", [chunk]
    )
    assert result is True


def test_zero_overlap_and_weak_score_is_insufficient():
    # Mirrors the real F4 case: a chunk about pickup windows coincidentally
    # clears the per-chunk relevance floor for an unrelated "weather" query.
    chunk = _chunk("The carrier is responsible once pickup is confirmed.", -1.05)
    result = is_document_evidence_sufficient(
        "What is the weather forecast for tomorrow?", [chunk]
    )
    assert result is False


def test_zero_overlap_but_a_single_strong_score_alone_is_still_insufficient():
    """A single strong-scoring chunk without token overlap and without a
    second corroborating chunk must not be enough on its own - proves the
    chunk-count signal genuinely participates, not just score+overlap."""
    chunk = _chunk("Escalation procedures for critical incidents.", -6.0)
    result = is_document_evidence_sufficient(
        "Describe the refund timeline for a cancelled shipment.", [chunk]
    )
    assert result is False


def test_zero_overlap_strong_score_with_a_corroborating_second_chunk_is_sufficient():
    """A genuine paraphrase - different vocabulary, but two independently
    strong-scoring chunks corroborate each other."""
    chunks = [
        _chunk("Escalation procedures for critical incidents.", -6.0),
        _chunk("Critical incidents must be routed to a human immediately.", -4.5),
    ]
    result = is_document_evidence_sufficient(
        "How should the most severe problems be handled?", chunks
    )
    assert result is True


def test_overlap_is_checked_across_every_chunk_not_only_the_top_scoring_one():
    chunks = [
        _chunk("Unrelated content that merely scores well lexically.", -5.0),
        _chunk("The service credit eligibility policy is described here.", -1.1),
    ]
    result = is_document_evidence_sufficient(
        "What is the service credit eligibility policy?", chunks
    )
    assert result is True


def test_gate_never_reduces_recall_for_a_precise_multi_token_match():
    chunk = _chunk(
        "Default first-response targets by plan and severity for P1 tickets.", -2.0
    )
    result = is_document_evidence_sufficient(
        "What are the standard SLA response time targets?", [chunk]
    )
    assert result is True
