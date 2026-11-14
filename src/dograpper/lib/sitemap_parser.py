"""Parser for sitemap.xml and sitemapindex (recursive).

Implements the sitemap protocol (https://www.sitemaps.org/protocol.html):
  - <urlset> with <url><loc>...</loc></url> entries
  - <sitemapindex> with <sitemap><loc>...</loc></sitemap> entries (recursive)

Gzip-encoded sitemaps are detected via magic bytes and decompressed.
Cross-host recursion is rejected (same-netloc guard at depth > 0).

Stdlib-only: urllib, xml.etree.ElementTree, gzip.
"""

from __future__ import annotations

import gzip
import logging
import xml.etree.ElementTree as ET
from typing import Callable, List, Sequence, Set
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

from .wget_mirror import BROWSER_HEADERS, BROWSER_UA

logger = logging.getLogger(__name__)

SITEMAP_NS = "{http://www.sitemaps.org/schemas/sitemap/0.9}"
TIMEOUT_SECONDS = 15
MAX_RECURSION_DEPTH = 3

CANDIDATE_PATHS = ("sitemap.xml", "sitemap_index.xml", "sitemap-index.xml")


def _fetch_url(url: str, timeout: int = TIMEOUT_SECONDS) -> bytes | None:
    headers = {
        "User-Agent": BROWSER_UA,
        **BROWSER_HEADERS,
        "Accept": "application/xml, text/xml, */*",
    }
    req = Request(url, headers=headers)
    try:
        with urlopen(req, timeout=timeout) as resp:
            if resp.status != 200:
                logger.info(f"sitemap: {url} returned HTTP {resp.status}")
                return None
            data = resp.read()
    except HTTPError as exc:
        logger.info(f"sitemap: {url} HTTPError {exc.code}")
        return None
    except (URLError, TimeoutError, OSError) as exc:
        logger.info(f"sitemap: {url} fetch failed: {exc}")
        return None

    return _gunzip(url, data)


def _gunzip(url: str, data: bytes) -> bytes | None:
    if data[:2] == b"\x1f\x8b" or url.endswith(".gz"):
        try:
            data = gzip.decompress(data)
        except OSError as exc:
            logger.warning(f"sitemap: gzip decompress failed for {url}: {exc}")
            return None
    return data


def _parse_urlset(root: ET.Element) -> List[str]:
    """Extract <loc> entries from a <urlset> element."""
    urls: List[str] = []
    for url_el in root.findall(f"{SITEMAP_NS}url"):
        loc_el = url_el.find(f"{SITEMAP_NS}loc")
        if loc_el is not None and loc_el.text:
            urls.append(loc_el.text.strip())
    return urls


def _parse_sitemapindex(root: ET.Element) -> List[str]:
    """Extract <loc> entries from a <sitemapindex> element."""
    sub_sitemaps: List[str] = []
    for sitemap_el in root.findall(f"{SITEMAP_NS}sitemap"):
        loc_el = sitemap_el.find(f"{SITEMAP_NS}loc")
        if loc_el is not None and loc_el.text:
            sub_sitemaps.append(loc_el.text.strip())
    return sub_sitemaps


def _canonical_prefix(path: str) -> str:
    """Slash-terminated prefix for safe startswith() matching. '/docs' vs '/docsextra'."""
    if not path:
        return "/"
    return path.rstrip("/") + "/"


def _sub_sitemap_in_scope(sub_url: str, base_netloc: str, base_prefix: str) -> bool:
    """Accept a sub-sitemap if it's same-netloc OR its path starts with the base path prefix.

    Mintlify-class hosting stores the canonical ``sitemapindex`` on the public
    host (``mintlify.wiki``) but each per-project sub-sitemap on a CDN host
    (``www.mintlify.com/<project>/sitemap.xml``). The sub-sitemap path still
    identifies the user's project, so path-prefix alone is enough to keep
    recursion scoped without leaking into unrelated projects.
    """
    sub_parsed = urlparse(sub_url)
    if not sub_parsed.netloc or sub_parsed.netloc == base_netloc:
        return True
    sub_prefix = _canonical_prefix(sub_parsed.path.rsplit("/", 1)[0])
    return sub_prefix.startswith(base_prefix)


def _fetch_and_parse(
    url: str,
    base_netloc: str,
    base_prefix: str,
    depth: int,
    visited: Set[str],
    fetch: Callable[[str], bytes | None] | None = None,
) -> List[str]:
    """Fetch `url`, parse it, recurse into sub-sitemaps. Returns aggregated URLs."""
    if url in visited:
        return []
    visited.add(url)

    if depth > MAX_RECURSION_DEPTH:
        logger.warning(f"sitemap: max recursion depth exceeded at {url}")
        return []

    if fetch is None:
        data = _fetch_url(url)
    else:
        data = fetch(url)
        if data is not None:
            data = _gunzip(url, data)
    if data is None:
        return []

    try:
        root = ET.fromstring(data)
    except ET.ParseError as exc:
        logger.warning(f"sitemap: XML parse error for {url}: {exc}")
        return []

    tag = root.tag
    if tag == f"{SITEMAP_NS}urlset":
        urls = _parse_urlset(root)
        if not urls:
            logger.info(f"sitemap: {url} is an empty urlset (0 <url> entries)")
        else:
            logger.info(f"sitemap: {url} urlset yielded {len(urls)} URLs")
        return urls

    if tag == f"{SITEMAP_NS}sitemapindex":
        sub_sitemaps = _parse_sitemapindex(root)
        logger.info(f"sitemap: {url} sitemapindex has {len(sub_sitemaps)} sub-sitemaps")
        aggregated: List[str] = []
        for sub_url in sub_sitemaps:
            if not _sub_sitemap_in_scope(sub_url, base_netloc, base_prefix):
                logger.debug(
                    f"sitemap: skipping out-of-scope sub-sitemap {sub_url} "
                    f"(base_netloc={base_netloc}, base_prefix={base_prefix})"
                )
                continue
            aggregated.extend(
                _fetch_and_parse(sub_url, base_netloc, base_prefix, depth + 1, visited, fetch)
            )
        return aggregated

    logger.warning(f"sitemap: {url} root tag {tag!r} not recognized (expected urlset/sitemapindex)")
    return []


def fetch_sitemap(
    base_url: str,
    fetch: Callable[[str], bytes | None] | None = None,
    extra_candidates: Sequence[str] = (),
) -> List[str]:
    """Discover and parse the site's sitemap(s). Returns deduplicated URL list.

    Tries sitemap.xml, then sitemap_index.xml, then sitemap-index.xml.
    Recurses into <sitemapindex> children with same-netloc guard.
    Returns [] if no candidate responds 200 or parses successfully.
    `fetch` replaces the built-in HTTP GET for every request (body or None);
    `extra_candidates` (e.g. robots.txt Sitemap: hints) are tried first and
    must be on the base host.
    """
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        logger.warning(f"sitemap: base_url missing scheme/netloc: {base_url}")
        return []

    root = f"{parsed.scheme}://{parsed.netloc}/"
    base_netloc = parsed.netloc
    base_prefix = _canonical_prefix(parsed.path)

    visited: Set[str] = set()

    for candidate in (*extra_candidates, *CANDIDATE_PATHS):
        candidate_url = urljoin(root, candidate)
        if urlparse(candidate_url).netloc != base_netloc:
            logger.info(f"sitemap: rejecting cross-host candidate {candidate_url}")
            continue
        logger.debug(f"sitemap: probing {candidate_url}")
        urls = _fetch_and_parse(
            candidate_url, base_netloc, base_prefix, depth=0, visited=visited, fetch=fetch
        )
        if urls:
            deduped: List[str] = []
            seen: Set[str] = set()
            for u in urls:
                if u not in seen:
                    seen.add(u)
                    deduped.append(u)
            logger.info(f"sitemap: final unique URL count {len(deduped)} from {candidate_url}")
            return deduped
    return []
