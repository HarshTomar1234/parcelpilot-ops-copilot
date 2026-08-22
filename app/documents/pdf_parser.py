"""Page-aware PDF parsing.

Every source in the pack opens with a short "preamble" of Title lines
followed by 'Key: value' metadata lines (Status, Effective/Updated,
Supersedes/Superseded by, Account, Customer, Term, Plan), then either
numbered sections ("1. Scope and source precedence") or, for the deprecated
policy, a single unnumbered section. This module splits on that structure
without hardcoding per-file logic, so it keeps working if the pack's
wording shifts slightly.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from app.errors import DocumentParseError

_HEADING = re.compile(r"^(?P<num>\d+)\.\s+(?P<title>\S.*)$")
_KV_LINE = re.compile(r"^(?P<key>[A-Za-z][A-Za-z ]{1,30}):\s*(?P<value>.+)$")


@dataclass(frozen=True)
class ParsedSection:
    number: str | None
    title: str
    body: str


@dataclass(frozen=True)
class ParsedPage:
    page_number: int
    title: str
    preamble_fields: dict[str, str]
    sections: list[ParsedSection] = field(default_factory=list)


def parse_pdf(path: Path) -> list[ParsedPage]:
    doc = pymupdf.open(path)
    if doc.page_count == 0:
        raise DocumentParseError(path.name, "PDF has zero pages")
    pages = []
    for i in range(1, doc.page_count + 1):
        page = doc[i - 1]
        raw = str(page.get_text("text"))
        lines = [ln.strip() for ln in raw.splitlines()]
        lines = [ln for ln in lines if ln]
        if not lines:
            raise DocumentParseError(path.name, f"page {i} has no extractable text")
        pages.append(_parse_page(i, lines, path.name))
    return pages


def _parse_page(page_number: int, lines: list[str], filename: str) -> ParsedPage:
    title_lines: list[str] = []
    fields: dict[str, str] = {}
    idx = 0

    # Title: leading lines before the first 'Key: value' line.
    while idx < len(lines) and not _KV_LINE.match(lines[idx]):
        title_lines.append(lines[idx])
        idx += 1
    if idx >= len(lines):
        raise DocumentParseError(filename, f"page {page_number} has no metadata block")

    # Preamble: contiguous 'Key: value' lines.
    while idx < len(lines):
        match = _KV_LINE.match(lines[idx])
        if not match:
            break
        fields[match["key"].strip()] = match["value"].strip()
        idx += 1

    remainder = lines[idx:]
    sections = _split_sections(remainder)
    return ParsedPage(
        page_number=page_number,
        title=" ".join(title_lines),
        preamble_fields=fields,
        sections=sections,
    )


def _split_sections(lines: list[str]) -> list[ParsedSection]:
    if not lines:
        return []

    headings = [(i, m) for i, ln in enumerate(lines) if (m := _HEADING.match(ln))]
    if not headings:
        # No numbered sections (e.g. the deprecated policy): the first line
        # is the section title, everything after it is the body.
        return [ParsedSection(number=None, title=lines[0], body="\n".join(lines[1:]))]

    sections = []
    for pos, (start, match) in enumerate(headings):
        end = headings[pos + 1][0] if pos + 1 < len(headings) else len(lines)
        body_lines = lines[start + 1 : end]
        sections.append(
            ParsedSection(number=match["num"], title=match["title"], body="\n".join(body_lines))
        )
    return sections
