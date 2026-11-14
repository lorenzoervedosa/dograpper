"""Cloudflare interstitial detection (spec 5.4): header or titled 200 page only."""

import re
from collections.abc import Mapping

_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)


def is_challenge(status: int, headers: Mapping[str, str], body: bytes) -> bool:
    # Never match on /cdn-cgi/challenge-platform/: real pages embed the jsd beacon.
    if any(k.lower() == "cf-mitigated" for k in headers):
        return True
    if status != 200:
        return False
    m = _TITLE.search(body.decode("utf-8", errors="replace"))
    return bool(m) and m.group(1).strip().lower() == "just a moment..."
