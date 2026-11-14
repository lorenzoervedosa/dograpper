"""Cloudflare interstitial detection (spec 5.4): header or titled 200 page only."""

import re
from collections.abc import Mapping

# Linear by construction: bounded classes, no lazy scan to end of body.
_TITLE = re.compile(r"<title[^>]{0,100}>([^<]{0,200})</title>", re.IGNORECASE)
_SCAN_BYTES = 64 * 1024


def is_challenge(status: int, headers: Mapping[str, str], body: bytes) -> bool:
    # Never match on /cdn-cgi/challenge-platform/: real pages embed the jsd beacon.
    if any(k.lower() == "cf-mitigated" for k in headers):
        return True
    if status != 200:
        return False
    m = _TITLE.search(body[:_SCAN_BYTES].decode("utf-8", errors="replace"))
    return bool(m) and m.group(1).strip().lower() == "just a moment..."
