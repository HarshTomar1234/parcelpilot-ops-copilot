"""EvaluationCase -> DeepEval LLMTestCase.

For each eligible golden case (a real natural-language question, not an
action-flow placeholder), builds retrieval_context from the actual
search_documents tool output and actual_output from the configured
LLMProvider given that context. Phase 2 has no agent to generate a real
grounded answer yet, so this exercises the metric pipeline end to end - it
is a harness-verification signal, not an answer-quality signal, until a
real agent and a real judge model are wired in (see
docs/_internal/phase-reports/phase-02.md).
"""

from __future__ import annotations

import sqlite3

from deepeval.test_case import LLMTestCase

from app.agent.tools import SearchDocumentsRequest, search_documents_tool
from app.authorization.context import AuthContext
from app.evaluation.cases import EvaluationCase
from app.llm.base import LLMProvider
from app.llm.types import LLMMessage, LLMRequest
from app.observability.tracing import RequestContext

_ANSWER_PROMPT = (
    "Answer the support question using only the evidence below. Cite sources by "
    "their bracketed ID. If the evidence does not answer the question, say so.\n\n"
    "Question: {question}\n\nEvidence:\n{evidence}"
)


def build_test_case(
    conn: sqlite3.Connection,
    case: EvaluationCase,
    auth: AuthContext,
    provider: LLMProvider,
    model: str,
    top_k: int = 5,
) -> LLMTestCase:
    search_response = search_documents_tool(
        conn,
        SearchDocumentsRequest(query=case.question, top_k=top_k),
        auth,
        RequestContext.new(),
    )
    retrieval_context = [
        f"[{r.source_id} p{r.page}:{r.section}] {r.snippet}" for r in search_response.results
    ]
    evidence_block = "\n".join(retrieval_context) or "(no evidence retrieved)"
    prompt = _ANSWER_PROMPT.format(question=case.question, evidence=evidence_block)

    request = LLMRequest(messages=[LLMMessage(role="user", content=prompt)], model=model)
    response = provider.complete(request, RequestContext.new())

    return LLMTestCase(
        input=case.question,
        actual_output=response.content,
        retrieval_context=retrieval_context,  # type: ignore[arg-type]  # list invariance false-positive
        name=case.case_id,
    )
