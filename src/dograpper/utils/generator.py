"""The generator a page declares in ``<meta name="generator" content="...">``.

Generator-specific adapters (ADR-0009) key on it: Javadoc writes
``javadoc/<Writer>``, MediaWiki ``MediaWiki <version>``.
"""

import html
import re
from typing import Optional

# Measured offsets: Javadoc ~500 chars, MediaWiki ~4,400 (after its inline config).
SCAN_CHARS = 64 * 1024
# Linear by construction: bounded classes, attributes in either order.
_META = re.compile(r"<meta\b([^>]{0,500})>", re.IGNORECASE)
_ATTR = re.compile(r"""\b(name|content)\s*=\s*(?:"([^"]{0,300})"|'([^']{0,300})')""", re.IGNORECASE)


def page_generator(head: str) -> Optional[str]:
    """Content of the first ``<meta name="generator">`` in the first SCAN_CHARS of ``head``."""
    for meta in _META.finditer(head[:SCAN_CHARS]):
        attrs = {m.group(1).lower(): m.group(2) if m.group(2) is not None else m.group(3)
                 for m in _ATTR.finditer(meta.group(1))}
        if (attrs.get("name") or "").lower() == "generator" and attrs.get("content") is not None:
            return html.unescape(attrs["content"]).strip()
    return None
