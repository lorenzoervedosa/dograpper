"""Fenced code blocks, the form every ``<pre>`` takes in the extracted text.

The HTML stripper writes them; dedup, the chunker and the scorer must treat
one as a single unit even when it holds blank lines. A block follows
CommonMark: an opening line of three or more backticks plus an optional info
string, closed by a line of at least as many backticks. An unclosed block
runs to the end of the text.
"""

import re

_OPENER = re.compile(r"^ {0,3}(`{3,})[^`\n]*$", re.MULTILINE)


def fence(code: str, lang: str = "") -> str:
    """Wrap ``code`` in a backtick fence that no backtick run inside it can close."""
    longest = max((len(run) for run in re.findall(r"`+", code)), default=0)
    ticks = "`" * max(3, longest + 1)
    return f"{ticks}{lang}\n{code}\n{ticks}"


def _spans(text: str) -> list:
    """(start, end, closed) of every fenced block in ``text``."""
    spans = []
    pos = 0
    while (opener := _OPENER.search(text, pos)):
        closer = re.compile(rf"^ {{0,3}}{opener.group(1)}`*[ \t]*$", re.MULTILINE)
        close = closer.search(text, opener.end())
        pos = close.end() if close else len(text)
        spans.append((opener.start(), pos, close is not None))
    return spans


def split_blocks(text: str) -> list:
    """Split ``text`` on blank lines like ``text.split("\\n\\n")``, never inside a fenced block."""
    spans = _spans(text)
    blocks = []
    start = 0
    i = 0  # spans are sorted and disjoint: one pointer keeps this linear on untrusted pages
    for sep in re.finditer("\n\n", text):
        while i < len(spans) and spans[i][1] <= sep.start():
            i += 1
        if i < len(spans) and spans[i][0] < sep.start():
            continue  # inside a fenced block
        blocks.append(text[start:sep.start()])
        start = sep.end()
    blocks.append(text[start:])
    return blocks


def sub_closed_fences(text: str, repl) -> str:
    """Replace every closed fenced block of ``text`` with ``repl(block)``."""
    parts = []
    pos = 0
    for start, end, closed in _spans(text):
        if closed:
            parts += [text[pos:start], repl(text[start:end])]
            pos = end
    parts.append(text[pos:])
    return "".join(parts)


def unfence(text: str) -> str:
    """Drop the fence lines around each closed fenced block, keeping its code."""
    return sub_closed_fences(text, lambda block: "\n".join(block.split("\n")[1:-1]))
