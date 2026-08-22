"""Lexical relevance threshold for search_documents_tool (Phase 4 s2).
MIN_RELEVANCE_SCORE (app/agent/tools.py) is calibrated against real BM25
scores, not invented - see that module's docstring for the real-pack
numbers behind the -1.0 cutoff. This file proves the filter actually
changes behavior for a genuinely off-topic query while leaving a genuinely
relevant one untouched, using the fixture corpus's own real scores (which
differ from the real pack's, since BM25 is noisier over a much smaller
corpus - verified here, not assumed to transfer).
"""

from __future__ import annotations

import pytest

from app.agent.context import AgentRequestContext
from app.agent.orchestrator import run_agent
from app.agent.tools import MIN_RELEVANCE_SCORE, SearchDocumentsRequest, search_documents_tool
from app.llm.mock_provider import MockProvider
from app.observability.tracing import RequestContext


@pytest.fixture()
def provider() -> MockProvider:
    return MockProvider()


def _ctx(auth, snapshot) -> AgentRequestContext:
    rc = RequestContext.new()
    return AgentRequestContext(
        request_id=rc.request_id, trace_id=rc.trace_id, user_id="test-user",
        auth=auth, dataset_snapshot_time=snapshot,
    )


def test_off_topic_query_is_filtered_out_entirely(conn, auth):
    # Verified against the fixture corpus: every result scores weaker than
    # MIN_RELEVANCE_SCORE (max observed here is -0.99).
    request = SearchDocumentsRequest(query="recommend a pizza restaurant", top_k=5)
    response = search_documents_tool(conn, request, auth, RequestContext.new())
    assert response.results == []


def test_relevant_query_survives_the_filter(conn, auth):
    request = SearchDocumentsRequest(
        query="Can Meridian Freight cancel a shipment without a fee", top_k=5
    )
    response = search_documents_tool(conn, request, auth, RequestContext.new())
    assert response.results
    assert all(r.score <= MIN_RELEVANCE_SCORE for r in response.results)


def test_off_topic_question_reaches_insufficient_evidence_end_to_end(conn, auth, clock, provider):
    result = run_agent(
        "Please recommend a good pizza restaurant nearby",
        _ctx(auth, clock.now()), conn, provider,
    )
    assert result.status == "insufficient_evidence"


def test_relevant_question_still_completes_end_to_end(conn, auth, clock, provider):
    result = run_agent(
        "Can Meridian Freight cancel FXO-1001 without a cancellation fee?",
        _ctx(auth, clock.now()), conn, provider,
    )
    assert result.status == "completed"
    assert result.citations
