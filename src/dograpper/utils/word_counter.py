"""Word counting utilities."""

import os
import re
from .code_fence import sub_closed_fences
from .html_stripper import strip_html
from .content_extractor import extract_content

# A heading or list marker opening a line of strip_html(..., markdown=True),
# and the delimiter row under a table's header.
_LINE_MARKER = re.compile(r"[ \t]*(?:#{1,6}|-|\d+\.)(?=[ \t]|$)")
_DELIMITER_ROW = re.compile(r"\|(?: *:?-+:? *\|)+")


def count_words(text: str, markdown: bool = False) -> int:
    """Word count (ADR-0003). ``markdown`` leaves out the markup that
    ``strip_html(..., markdown=True)`` writes outside code blocks: heading and
    list markers, table pipes and the table delimiter row (#87)."""
    words = len(text.split())
    if markdown:
        for line in sub_closed_fences(text, lambda block: "").split("\n"):
            if _DELIMITER_ROW.fullmatch(line):
                words -= len(line.split())
            elif line.startswith("|"):
                words -= line.split().count("|")
            elif _LINE_MARKER.match(line):
                words -= 1
    return words

def count_words_file(filepath: str, no_extract: bool = False) -> int:
    """Read a file from disk and return its word count, tolerating encoding errors."""
    if not os.path.isfile(filepath):
        return 0
    try:
        with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
            content = f.read()
        if filepath.lower().endswith(('.html', '.htm')):
            if not no_extract:
                content = extract_content(content)
            content = strip_html(content)
        return count_words(content)
    except Exception:
        # Fallback for unexpected I/O errors
        return 0
