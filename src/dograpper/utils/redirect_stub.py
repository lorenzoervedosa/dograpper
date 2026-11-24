"""Redirect stubs: tiny pages whose only job is to send the browser elsewhere (rustdoc writes one per re-export).

Same treatment as the saved error pages (`utils/error_page.py`) and challenge pages.
"""

import re
from collections.abc import Iterable
from html import unescape

from .html_scan import find_html_files, visible_word_count

# Linear by construction: bounded classes, no lazy scan to end of body.
_META = re.compile(r"<meta\b[^<>]{0,1000}>", re.IGNORECASE)
_HTTP_EQUIV_REFRESH = re.compile(r"""http-equiv\s*=\s*["']?\s*refresh\b""", re.IGNORECASE)
# `content="0;URL=target"`: a delay, then a url= part that is not empty; the target is group 1.
_REFRESH_URL = re.compile(r"""content\s*=\s*["']?[^"'>;,]{0,20}[;,]\s*url\s*=\s*["']?\s*([^\s"'>]+)""",
                          re.IGNORECASE)
SCAN_BYTES = 16 * 1024
# A stub is the redirect plus a line ("Redirecting to ..."); more text than this is a page with a refresh.
_MAX_WORDS = 40


def redirect_target(body: bytes) -> str | None:
    """The URL a redirect stub sends the browser to, or None when the document is not a stub:
    a meta refresh with a URL AND near-empty."""
    if len(body) > SCAN_BYTES:
        return None  # a real page, or too big to be a stub
    text = body.decode("utf-8", errors="replace")
    for meta in _META.findall(text):
        found = _HTTP_EQUIV_REFRESH.search(meta) and _REFRESH_URL.search(meta)
        if found:
            return unescape(found.group(1)) if visible_word_count(text) <= _MAX_WORDS else None
    return None


def is_redirect_stub(body: bytes) -> bool:
    """True when the document carries a meta refresh with a URL AND is near-empty."""
    return redirect_target(body) is not None


def find_redirect_stub_files(paths: Iterable[str]) -> list[str]:
    """Paths of the .html/.htm files that are redirect stubs."""
    return find_html_files(paths, is_redirect_stub, SCAN_BYTES + 1)
