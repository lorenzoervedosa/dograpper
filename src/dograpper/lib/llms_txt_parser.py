"""Parser for the llms.txt convention (https://llmstxt.org).

Fetches `<base>/llms.txt` (falling back to `llms-full.txt`) and extracts
URLs from markdown link syntax `[text](url)` plus bare `http(s)://...` lines.

Stdlib-only: urllib, re, gzip.
"""

from __future__ import annotations

import gzip
import io
import logging
import re
from typing import Callable, List
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from ..utils.redact import redact_url
from .wget_mirror import BROWSER_HEADERS, BROWSER_UA

logger = logging.getLogger(__name__)

LLMS_TXT_CANDIDATES = ("llms.txt", "llms-full.txt")
TIMEOUT_SECONDS = 10
_MARKDOWN_LINK_RE = re.compile(r"\[[^\]]*\]\((?P<url>https?://[^\s)]+)\)")
_BARE_URL_RE = re.compile(r"^\s*(?P<url>https?://\S+)\s*$")


def _fetch_url(url: str, timeout: int = TIMEOUT_SECONDS) -> bytes | None:
    """GET `url` with browser UA. Returns body bytes, or None if not 200."""
    headers = {"User-Agent": BROWSER_UA, **BROWSER_HEADERS, "Accept": "text/plain, */*"}
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                logger.info(f"llms.txt: {redact_url(url)} returned HTTP {resp.status}")
                return None
            data = resp.read()
            if data[:2] == b"\x1f\x8b":
                data = gzip.decompress(data)
            return data
    except HTTPError as exc:
        logger.info(f"llms.txt: {redact_url(url)} HTTPError {exc.code}")
        return None
    except (URLError, TimeoutError, OSError) as exc:
        logger.info(f"llms.txt: {redact_url(url)} fetch failed: {exc}")
        return None


def _parse_llms_txt(body: str, base_url: str) -> List[str]:
    """Extract absolute http(s) URLs from llms.txt body."""
    urls: List[str] = []
    seen = set()
    for raw_line in body.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        for match in _MARKDOWN_LINK_RE.finditer(line):
            url = match.group("url")
            if url not in seen:
                seen.add(url)
                urls.append(url)
        bare = _BARE_URL_RE.match(line)
        if bare:
            url = bare.group("url")
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


def fetch_llms_txt(
    base_url: str, fetch: Callable[[str], bytes | None] | None = None
) -> List[str]:
    """Try <base>/llms.txt, then <base>/llms-full.txt. Return extracted URL list.

    Returns [] if no candidate responds 200 or if body yields no URLs.
    `fetch` replaces the built-in HTTP GET (returns the body, or None).
    """
    parsed = urlparse(base_url)
    if not parsed.scheme:
        logger.warning(f"llms.txt: base_url missing scheme: {redact_url(base_url)}")
        return []

    root = f"{parsed.scheme}://{parsed.netloc}/"

    for candidate in LLMS_TXT_CANDIDATES:
        candidate_url = urljoin(root, candidate)
        logger.debug(f"llms.txt: probing {redact_url(candidate_url)}")
        body = (fetch or _fetch_url)(candidate_url)
        if body is None:
            continue
        text = body.decode("utf-8", errors="replace")
        urls = _parse_llms_txt(text, base_url)
        if urls:
            logger.info(f"llms.txt: {redact_url(candidate_url)} yielded {len(urls)} URLs")
            return urls
        logger.info(f"llms.txt: {redact_url(candidate_url)} parsed 0 URLs (empty or malformed)")
    return []
