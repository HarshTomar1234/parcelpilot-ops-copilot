"""Turns parsed PDF sections into citable DocumentChunk rows."""

from __future__ import annotations

from app.documents.pdf_parser import ParsedPage
from app.documents.text_normalize import normalize
from app.models.source import DocumentChunk, SourceDocument


def build_chunks(source: SourceDocument, pages: list[ParsedPage]) -> list[DocumentChunk]:
    chunks: list[DocumentChunk] = []
    for page in pages:
        for index, section in enumerate(page.sections):
            # A numbered heading keeps its real number; an unnumbered page
            # (the deprecated policy has one section) gets a 1-based
            # position, matching the "SRC-02:p1:1" citation convention
            # already used in tests/evaluation/golden_cases.json.
            section_id = section.number if section.number is not None else str(index + 1)
            chunk_id = f"{source.source_id}:p{page.page_number}:{section_id}"
            raw_text = f"{section.title}\n{section.body}".strip()
            chunks.append(
                DocumentChunk(
                    chunk_id=chunk_id,
                    source_id=source.source_id,
                    filename=source.filename,
                    page=page.page_number,
                    section=section_id,
                    text=raw_text,
                    normalized_text=normalize(raw_text),
                    status=source.status,
                    source_type=source.source_type,
                    account_scope=source.scope.account_id,
                    effective_date=source.effective_date,
                    authority_class=source.authority_class,
                )
            )
    return chunks
