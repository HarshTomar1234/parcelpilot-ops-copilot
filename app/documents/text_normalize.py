"""Text normalization for retrieval and display.

data/source_manifest.json flags that SRC-03's bullets are encoded as
U+25CF (BLACK CIRCLE) immediately followed by U+200B (ZERO WIDTH SPACE),
e.g. '●​ DRAFT: May be cancelled...'. Left as-is, the zero-width
space can split a token mid-word under some tokenizers and the bullet glyph
is noise for search. normalize() fixes both without altering meaning.
"""

from __future__ import annotations

import re
import unicodedata

_ZERO_WIDTH_SPACE = "​"
_BULLET_CHARS = "●•▪"  # BLACK CIRCLE, BULLET, BLACK SMALL SQUARE
_BULLET_LINE = re.compile(rf"^[{_BULLET_CHARS}]\s*")
_WHITESPACE_RUN = re.compile(r"[ \t]+")


def normalize_line(line: str) -> str:
    line = line.replace(_ZERO_WIDTH_SPACE, "")
    line = _BULLET_LINE.sub("- ", line.strip())
    return _WHITESPACE_RUN.sub(" ", line).strip()


def normalize(text: str) -> str:
    """Normalize a full chunk body: strip zero-width spaces, turn bullet
    glyphs into a plain '- ' prefix, collapse whitespace, unicode-normalize.
    """
    lines = [normalize_line(line) for line in text.splitlines()]
    normalized = "\n".join(line for line in lines if line)
    return unicodedata.normalize("NFKC", normalized)
