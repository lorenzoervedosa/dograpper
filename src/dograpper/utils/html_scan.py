"""Mold of the pack-time page detectors (challenge, error page, redirect stub): visible words and the file scan."""

import re
from collections.abc import Callable, Iterable

# Linear by construction: bounded classes, no lazy scan to end of body.
_TAG = re.compile(r"<[^<>]{0,2000}>")


def drop_blocks(text: str, tag: str) -> str:
    """Remove <tag>...</tag> blocks (an unclosed one runs to the end); one pass, linear."""
    low = text.lower()
    out, pos = [], 0
    while (start := low.find("<" + tag, pos)) != -1:
        out.append(text[pos:start])
        end = low.find("</" + tag, start)
        if end == -1:
            return "".join(out)
        end = low.find(">", end)
        pos = len(text) if end == -1 else end + 1
    out.append(text[pos:])
    return "".join(out)


def visible_word_count(text: str) -> int:
    """Words left once script and style blocks and every tag are removed."""
    return len(_TAG.sub(" ", drop_blocks(drop_blocks(text, "script"), "style")).split())


def find_html_files(paths: Iterable[str], detect: Callable[[bytes], bool], read_bytes: int) -> list[str]:
    """Paths of the .html/.htm files whose first `read_bytes` bytes `detect` accepts."""
    found = []
    for path in paths:
        if not path.lower().endswith(('.html', '.htm')):
            continue
        try:
            with open(path, 'rb') as fh:
                head = fh.read(read_bytes)
        except OSError:
            continue  # unreadable files are reported by the stage that reads them
        if detect(head):
            found.append(path)
    return found
