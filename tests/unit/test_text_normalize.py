from app.documents.text_normalize import normalize, normalize_line


def test_strips_zero_width_space_and_bullet_glyph():
    raw = "●​ DRAFT: May be cancelled with no fee."
    assert normalize_line(raw) == "- DRAFT: May be cancelled with no fee."


def test_collapses_internal_whitespace_runs():
    assert normalize_line("a   b\tc") == "a b c"


def test_normalize_drops_blank_lines_and_joins():
    text = "line one\n\n\nline two"
    assert normalize(text) == "line one\nline two"


def test_normalize_is_idempotent():
    raw = "●​ P1: 15 minutes, 24x7 "
    once = normalize(raw)
    twice = normalize(once)
    assert once == twice
