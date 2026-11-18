"""Heading extraction from HTML documents with position tracking.

Extracts headings (h1-h6) from HTML while simultaneously producing
clean text output, tracking heading positions in the stripped text
for hierarchical context injection into chunks.
"""

import re
import html as html_mod
from html.parser import HTMLParser
from dataclasses import dataclass
from typing import List, Dict

from .html_stripper import BLOCK_TAGS


@dataclass
class Heading:
    """A heading extracted from an HTML document."""
    level: int          # 1-6 (h1=1, h6=6)
    text: str           # Heading text content
    char_offset: int    # Approximate char offset in stripped text


@dataclass
class ExtractedDocument:
    """Result of extraction: clean text + headings."""
    text: str
    headings: List[Heading]
    source_path: str = ""


HEADING_TAGS = frozenset({"h1", "h2", "h3", "h4", "h5", "h6"})
SKIP_TAGS = frozenset({"script", "style", "noscript", "iframe", "svg"})


class _HeadingExtractorParser(HTMLParser):
    """Parser that simultaneously extracts clean text and heading positions."""

    def __init__(self):
        super().__init__()
        self.convert_charrefs = True
        self._output: list = []
        self._headings: list = []
        self._skip_depth: int = 0
        self._in_heading: bool = False
        self._heading_level: int = 0
        self._heading_parts: list = []
        self._current_offset: int = 0

    def handle_starttag(self, tag, attrs):
        if tag in SKIP_TAGS:
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return
        if tag in HEADING_TAGS:
            self._in_heading = True
            self._heading_level = int(tag[1])
            self._heading_parts = []

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth > 0:
            return
        if tag in HEADING_TAGS and self._in_heading:
            heading_text = " ".join("".join(self._heading_parts).split()).strip()
            if heading_text:
                self._headings.append(Heading(
                    level=self._heading_level,
                    text=heading_text,
                    char_offset=self._current_offset,
                ))
            self._in_heading = False
        if tag in BLOCK_TAGS:
            self._output.append("\n\n")
            self._current_offset += 2

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        if self._in_heading:
            self._heading_parts.append(data)
        self._output.append(data)
        self._current_offset += len(data)

    def get_result(self):
        text = "".join(self._output)
        text = html_mod.unescape(text)
        text = re.sub(r'\n{3,}', '\n\n', text)
        blocks = text.split('\n\n')
        blocks = [re.sub(r'\s+', ' ', b).strip() for b in blocks]
        text = '\n\n'.join(b for b in blocks if b)
        return text.strip(), self._headings


def extract_with_headings(html: str, source_path: str = "") -> ExtractedDocument:
    """Extract clean text and headings from an HTML document.

    Args:
        html: Raw HTML (may be pre-filtered by content_extractor).
        source_path: Relative path of the source file.

    Returns:
        ExtractedDocument with text, headings, and source_path.
    """
    parser = _HeadingExtractorParser()
    parser.feed(html)
    text, headings = parser.get_result()
    return ExtractedDocument(text=text, headings=headings, source_path=source_path)


def get_active_headings(headings: List[Heading], char_offset: int) -> List[Heading]:
    """Return the heading hierarchy active at a given text position.

    "Active" means the most recent heading of each level that appears
    before the offset, respecting hierarchy (a new h2 invalidates
    any existing h3, h4, etc.).

    Args:
        headings: List of headings sorted by char_offset.
        char_offset: Position in text for which we want context.

    Returns:
        List of active headings, ordered by level (h1 first).
    """
    active: Dict[int, Heading] = {}

    for h in headings:
        if h.char_offset > char_offset:
            break
        active[h.level] = h
        for level in list(active.keys()):
            if level > h.level:
                del active[level]

    return [active[level] for level in sorted(active.keys())]


def format_context_header(
    active_headings: List[Heading],
    source_path: str = "",
    chunk_index: int = 0,
    total_chunks: int = 0,
    word_count: int = 0,
    url: str = "",
    readiness: dict = None,
) -> str:
    """Format a dograpper-context-v1 header for injection into chunks.

    Returns formatted header string ending with \\n\\n, or empty string
    if no context is available.
    """
    import json

    payload = {}

    if source_path:
        payload["source"] = source_path
    if url:
        payload["url"] = url
    if total_chunks > 1:
        payload["chunk_index"] = chunk_index
        payload["total_chunks"] = total_chunks
    if word_count > 0:
        payload["word_count"] = word_count
    if active_headings:
        payload["context_breadcrumb"] = [h.text for h in active_headings]
    if readiness:
        payload["llm_readiness"] = readiness

    payload["schema_version"] = "v1"

    if not payload or payload == {"schema_version": "v1"}:
        return ""

    # json.dumps leaves ">" alone, so a value holding "-->" would close the comment;
    # ">" only ever occurs inside JSON strings here, where > decodes back to it.
    json_str = json.dumps(payload, indent=2, ensure_ascii=False).replace(">", "\\u003e")
    return f"<!-- dograpper-context-v1\n{json_str}\n-->\n\n"
