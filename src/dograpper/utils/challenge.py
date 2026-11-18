"""Cloudflare interstitial detection (spec 5.4): header or titled 200 page only.

Shared by the httrack fetcher (response time) and `pack` (files on disk).
"""

import re
from collections.abc import Iterable, Mapping

# Linear by construction: bounded classes, no lazy scan to end of body.
_TITLE = re.compile(r"<title[^>]{0,100}>([^<]{0,200})</title>", re.IGNORECASE)
_SCAN_BYTES = 64 * 1024


def is_challenge_page(body: bytes) -> bool:
    """True when the document's own <title> is the interstitial's."""
    # Never match on /cdn-cgi/challenge-platform/: real pages embed the jsd beacon.
    m = _TITLE.search(body[:_SCAN_BYTES].decode("utf-8", errors="replace"))
    return bool(m) and m.group(1).strip().lower() == "just a moment..."


def is_challenge(status: int, headers: Mapping[str, str], body: bytes) -> bool:
    if any(k.lower() == "cf-mitigated" for k in headers):
        return True
    return status == 200 and is_challenge_page(body)


def find_challenge_files(paths: Iterable[str]) -> list[str]:
    """Paths of the .html/.htm files that are saved challenge interstitials."""
    found = []
    for path in paths:
        if not path.lower().endswith(('.html', '.htm')):
            continue
        try:
            with open(path, 'rb') as fh:
                head = fh.read(_SCAN_BYTES)
        except OSError:
            continue  # unreadable files are reported by the stage that reads them
        if is_challenge_page(head):
            found.append(path)
    return found
