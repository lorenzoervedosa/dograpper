"""Saved HTTP error pages (`404 Not Found`) that a mirror stored as if they were documentation.

Same treatment as the bot-challenge pages (`utils/challenge.py`), different concept: no
Cloudflare involved, so it does not share that module.
"""

import re
from collections.abc import Iterable

# Linear by construction: bounded classes, no lazy scan to end of body.
_TITLE = re.compile(r"<title[^>]{0,100}>([^<]{0,200})</title>", re.IGNORECASE)
_TAG = re.compile(r"<[^<>]{0,2000}>")
# `<status code> <reason phrase>`, e.g. "404 Not Found", "503 Service Unavailable".
_STATUS_TITLE = re.compile(r"[45]\d\d [A-Za-z][A-Za-z' -]{0,40}")
_SCAN_BYTES = 16 * 1024
# A server error page is the status line plus a sentence; the Apache one measures 14 words.
_MAX_WORDS = 40


def _drop_blocks(text: str, tag: str) -> str:
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


def is_error_page(body: bytes) -> bool:
    """True when the <title> is a status line AND the whole document is near-empty."""
    if len(body) > _SCAN_BYTES:
        return False  # a real page, or too big to be a server's error stub
    text = body.decode("utf-8", errors="replace")
    m = _TITLE.search(text)
    if not m or not _STATUS_TITLE.fullmatch(m.group(1).strip()):
        return False
    visible = _TAG.sub(" ", _drop_blocks(_drop_blocks(text, "script"), "style"))
    return len(visible.split()) <= _MAX_WORDS


def find_error_page_files(paths: Iterable[str]) -> list[str]:
    """Paths of the .html/.htm files that are saved HTTP error pages."""
    found = []
    for path in paths:
        if not path.lower().endswith(('.html', '.htm')):
            continue
        try:
            with open(path, 'rb') as fh:
                head = fh.read(_SCAN_BYTES + 1)
        except OSError:
            continue  # unreadable files are reported by the stage that reads them
        if is_error_page(head):
            found.append(path)
    return found
