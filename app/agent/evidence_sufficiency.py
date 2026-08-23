"""Evidence-sufficiency gate for document-search-only answers (final
release hardening, finding F4). MIN_RELEVANCE_SCORE (app/agent/tools.py)
is a per-chunk lexical floor - it decides whether one chunk is worth
returning at all, not whether the *set* of returned chunks actually
supports answering the question. A clearly off-topic question can still
clear that floor on a small corpus (a coincidental term-frequency match
against unrelated content) and reach a "completed"/CONDITIONAL answer
instead of "insufficient_evidence".

This gate only runs when there is no domain calculation result to ground
the answer (app/agent/orchestrator.py only calls it when
pack.domain_results is empty) - a resolved entity with a real structured
record is already sufficient grounding on its own, deterministically, and
never needs a document-relevance judgment call.

Generic by construction: no keyword list, no example-specific special
case. Four signals, matching the phase spec's candidate list:
  - relevance score (the existing MIN_RELEVANCE_SCORE floor)
  - score margin (how far past that floor the best chunk is)
  - meaningful query-token overlap (shared non-stopword terms between the
    question and the actual matched text, across every returned chunk -
    not just the top-scoring one)
  - number of usable evidence chunks (single-chunk score-only matches are
    weaker corroboration than several)
"""

from __future__ import annotations

import re

from app.agent.tools import MIN_RELEVANCE_SCORE
from app.documents.retrieval import DocumentSearchResult

_TOKEN = re.compile(r"[a-z]{4,}")
_STOPWORDS = frozenset(
    {
        "what", "when", "where", "which", "who", "whom", "whose", "why", "how",
        "does", "did", "done", "have", "has", "had", "will", "would", "should",
        "could", "shall", "must", "about", "explain", "describe", "tell", "please",
        "the", "a", "an", "and", "or", "of", "to", "for", "in", "on", "at", "is",
        "are", "was", "were", "be", "been", "being", "this", "that", "these",
        "those", "with", "by", "as", "it", "its", "from", "into", "over", "under",
        "than", "then", "there", "here", "some", "any", "all", "each", "every",
        "not", "never", "just", "only", "also", "very", "more", "most", "such",
    }
)

# How much stronger than the existing per-chunk relevance floor a single
# chunk must be to count as corroborating evidence even without real term
# overlap (a genuine paraphrase, different vocabulary for the same
# topic) - a margin below MIN_RELEVANCE_SCORE, not an independent magic
# number.
_SCORE_MARGIN_BELOW_FLOOR = 2.0
_STRONG_SCORE = MIN_RELEVANCE_SCORE - _SCORE_MARGIN_BELOW_FLOOR

_MIN_SHARED_TOKENS = 2
_MIN_CORROBORATING_CHUNKS = 2


def _significant_tokens(text: str) -> set[str]:
    return {t for t in _TOKEN.findall(text.lower()) if t not in _STOPWORDS}


def is_document_evidence_sufficient(
    question: str,
    document_evidence: list[DocumentSearchResult],
    *,
    min_shared_tokens: int = _MIN_SHARED_TOKENS,
    strong_score: float = _STRONG_SCORE,
    min_corroborating_chunks: int = _MIN_CORROBORATING_CHUNKS,
) -> bool:
    """True iff document_evidence (already filtered by MIN_RELEVANCE_SCORE)
    is strong enough, as a set, to support answering `question` without
    any domain-calculation grounding."""
    if not document_evidence:
        return False

    query_tokens = _significant_tokens(question)
    if not query_tokens:
        return False

    best_overlap = max(
        (len(query_tokens & _significant_tokens(chunk.snippet)) for chunk in document_evidence),
        default=0,
    )
    if best_overlap >= min_shared_tokens:
        return True

    best_score = min(chunk.score for chunk in document_evidence)
    if best_score <= strong_score and len(document_evidence) >= min_corroborating_chunks:
        return True

    return False
