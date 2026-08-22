import pytest

from app.documents.pdf_parser import _parse_page
from app.errors import DocumentParseError


def test_numbered_sections_split_correctly():
    lines = [
        "Some Title",
        "Status: CURRENT",
        "Effective: 1 May 2026",
        "1. First section",
        "body line one",
        "body line two",
        "2. Second section",
        "another body line",
    ]
    page = _parse_page(1, lines, "test.pdf")
    assert page.title == "Some Title"
    assert page.preamble_fields == {"Status": "CURRENT", "Effective": "1 May 2026"}
    assert [s.number for s in page.sections] == ["1", "2"]
    assert page.sections[0].title == "First section"
    assert page.sections[0].body == "body line one\nbody line two"
    assert page.sections[1].body == "another body line"


def test_unnumbered_single_section():
    lines = ["Title", "Status: DEPRECATED", "Some Heading", "body text", "more body"]
    page = _parse_page(1, lines, "test.pdf")
    assert len(page.sections) == 1
    assert page.sections[0].number is None
    assert page.sections[0].title == "Some Heading"
    assert page.sections[0].body == "body text\nmore body"


def test_multi_line_title_before_first_kv_line():
    lines = ["Line one of title", "Line two of title", "Status: ACTIVE", "1. Section", "body"]
    page = _parse_page(1, lines, "test.pdf")
    assert page.title == "Line one of title Line two of title"


def test_missing_metadata_block_raises():
    with pytest.raises(DocumentParseError):
        _parse_page(1, ["just a title", "no colon lines at all"], "test.pdf")


def test_page_with_no_sections_returns_empty_list():
    lines = ["Title", "Status: CURRENT"]
    page = _parse_page(1, lines, "test.pdf")
    assert page.sections == []
