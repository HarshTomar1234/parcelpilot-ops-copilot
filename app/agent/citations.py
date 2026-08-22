"""Citation validation (Phase 3 s17). Every citation the generated answer
text contains is checked against the EvidencePack's actual citations - the
only source of truth for "was this evidence really retrieved/used." An
invalid citation (one the model wrote that does not correspond to
anything actually collected this request) is never silently dropped; it
is reported, and the caller decides whether to attempt one bounded
correction or fail the response.

The final answer's citation *list* shown to the user is always built from
EvidencePack.citations directly (see response_composer.py) - never solely
from what the model wrote in prose. This validator's job is narrower and
just as important: catch the case where the model's prose claims a source
that was not actually used.
"""

from __future__ import annotations

import re

from pydantic import BaseModel, ConfigDict

from app.agent.evidence_pack import EvidencePack
from app.domain.outcomes import EvidenceRef

_CITATION_MARKER = re.compile(r"\[([A-Za-z0-9_.:\-]+)\]")


def citation_key(ref: EvidenceRef) -> str:
    return f"{ref.source_id}:{ref.locator}" if ref.locator else ref.source_id


def extract_citation_markers(text: str) -> list[str]:
    return _CITATION_MARKER.findall(text)


class CitationValidationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    valid: bool
    cited_markers: list[str]
    invalid_markers: list[str]


def validate_citations(text: str, pack: EvidencePack) -> CitationValidationResult:
    known = {citation_key(ref) for ref in pack.citations}
    # Also accept a bare source_id (no locator) as valid, since a model may
    # reasonably cite just "[SRC-05]" - only reject a marker that names a
    # source_id not present in the evidence at all.
    known_source_ids = {ref.source_id for ref in pack.citations}

    markers = extract_citation_markers(text)
    invalid = [
        m for m in markers if m not in known and m.split(":")[0] not in known_source_ids
    ]
    return CitationValidationResult(
        valid=not invalid, cited_markers=markers, invalid_markers=invalid
    )
