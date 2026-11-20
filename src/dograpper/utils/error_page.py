"""Saved HTTP error pages (`404 Not Found`) that a mirror stored as if they were documentation.

Same treatment as the bot-challenge pages (`utils/challenge.py`), different concept: no
Cloudflare involved, so it does not share that module.
"""

import re
from collections.abc import Iterable

from .html_scan import find_html_files, visible_word_count

# Linear by construction: bounded classes, no lazy scan to end of body.
_TITLE = re.compile(r"<title[^>]{0,100}>([^<]{0,200})</title>", re.IGNORECASE)
# `<status code> <reason phrase>`, e.g. "404 Not Found", "503 Service Unavailable".
_STATUS_TITLE = re.compile(r"[45]\d\d [A-Za-z][A-Za-z' -]{0,40}")
_SCAN_BYTES = 16 * 1024
# A server error page is the status line plus a sentence; the Apache one measures 14 words.
_MAX_WORDS = 40


def is_error_page(body: bytes) -> bool:
    """True when the <title> is a status line AND the whole document is near-empty."""
    if len(body) > _SCAN_BYTES:
        return False  # a real page, or too big to be a server's error stub
    text = body.decode("utf-8", errors="replace")
    m = _TITLE.search(text)
    if not m or not _STATUS_TITLE.fullmatch(m.group(1).strip()):
        return False
    return visible_word_count(text) <= _MAX_WORDS


def find_error_page_files(paths: Iterable[str]) -> list[str]:
    """Paths of the .html/.htm files that are saved HTTP error pages."""
    return find_html_files(paths, is_error_page, _SCAN_BYTES + 1)
