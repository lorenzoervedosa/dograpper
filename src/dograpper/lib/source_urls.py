"""Source URL of each packed file, for --context-header.

A file's download-manifest entry wins, matched on its path in the mirror even
when a subdirectory of the download output is packed. Without one, an HTML
page's URL comes from the marker an offline copy left in its head: HTTrack's
footer comment or the "saved from url=" comment a browser's "Save page as"
writes. A marker is page content, so its value is validated before it reaches
any record.
"""

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlsplit

from ..utils.redact import neutralize_controls

# Both markers sit before <head>; HTTrack's lies within the first ~500 bytes of
# the pages measured, so the scan never has to read a whole page.
MARKER_SCAN_BYTES = 8192
MAX_URL_CHARS = 2048
MAX_SHOWN_MISSING = 10

NO_SOURCE = "no manifest entry or page marker"
INVALID = "invalid page marker"
CONFLICTING = "conflicting page markers"
AMBIGUOUS = "several manifest entries match"

_MARKER = re.compile(r"<!--\s*(Mirrored from |saved from url=)")
# HTTrack's default footer (htsglobal.h HTS_DEFAULT_FOOTER):
# "<!-- Mirrored from {url} by HTTrack Website Copier/<version> [XR&CO], {date} -->"
_HTTRACK_TAIL = " by HTTrack Website Copier/"
# Mark of the Web: "<!-- saved from url=(NNNN)<url> -->", NNNN being the URL length.
_SAVED_LENGTH = re.compile(r"\((\d{4})\)")
_COMMENT_END = re.compile(r"\s*-->")
_BODY_OPEN = re.compile(r"<body[\s>]", re.IGNORECASE)
# RFC 3986 characters only: no whitespace, control, quote, angle bracket or
# non-ASCII character, so a value can never close the comment it is written in.
_URL_CHARS = re.compile(r"[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://")
_HOST = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.?")


@dataclass
class UrlResolution:
    urls: dict[str, str] = field(default_factory=dict)  # relative path -> URL
    from_manifest: int = 0
    from_marker: int = 0
    missing: list[tuple[str, str]] = field(default_factory=list)  # (relative path, reason), sorted


def _valid_url(value: str, bare_host_ok: bool) -> Optional[str]:
    if len(value) > MAX_URL_CHARS or not _URL_CHARS.fullmatch(value):
        return None
    if not _SCHEME.match(value):
        if not bare_host_ok:
            return None
        # HTTrack <= 3.49 writes host and path without the scheme, and treats
        # a bare host as http.
        value = "http://" + value
    try:
        parts = urlsplit(value)
        parts.port  # raises ValueError on a non-numeric or out-of-range port
    except ValueError:
        return None
    if parts.scheme.lower() not in ("http", "https") or "@" in parts.netloc:
        return None
    if not parts.hostname or not _HOST.fullmatch(parts.hostname):
        return None
    return value


def _parse_marker(kind: str, rest: str) -> Optional[str]:
    """Validated URL, "" for a marker that names no URL, None if rejected."""
    if kind == "Mirrored from ":
        end = rest.find(_HTTRACK_TAIL)
        close = rest.find("-->")
        if end < 0 or 0 <= close < end:
            return None
        return _valid_url(rest[:end], bare_host_ok=True)
    m = _SAVED_LENGTH.match(rest)
    if not m:
        return None
    start, length = m.end(), int(m.group(1))
    value = rest[start:start + length]
    if len(value) != length or not _COMMENT_END.match(rest, start + length):
        return None
    if value.lower() == "about:internet":
        # IE/Windows zone marker, not a source URL; many sites ship it in their HTML
        return ""
    return _valid_url(value, bare_host_ok=False)


def marker_url(head: str) -> tuple[Optional[str], Optional[str]]:
    """URL from the markers in a page head, as ``(url, None)``.

    ``(None, INVALID)`` when a marker is malformed or its URL fails
    validation, ``(None, CONFLICTING)`` when markers disagree, and
    ``(None, None)`` when the page has no marker.
    """
    body = _BODY_OPEN.search(head)
    if body:
        head = head[:body.start()]
    urls = set()
    for m in _MARKER.finditer(head):
        url = _parse_marker(m.group(1), head[m.end():])
        if url is None:
            return None, INVALID
        if url:
            urls.add(url)
    if len(urls) > 1:
        return None, CONFLICTING
    return (urls.pop() if urls else None), None


def _dir_prefixes(input_dir: str) -> list[str]:
    """Path of ``input_dir`` relative to itself and to each of its ancestors.

    A manifest's local_path is relative to the download output directory,
    which is ``input_dir`` itself or, when a subdirectory of the mirror is
    packed, one of its ancestors.
    """
    parts = Path(os.path.abspath(input_dir)).parts[1:]
    return [""] + ["/".join(parts[i:]) + "/" for i in range(len(parts) - 1, -1, -1)]


def resolve_source_urls(paths, input_dir: str, manifest) -> UrlResolution:
    """Source URL of each file in ``paths`` (under ``input_dir``)."""
    res = UrlResolution()
    by_local = {(entry.local_path or key): entry.url
                for key, entry in (manifest.files.items() if manifest else ())
                if entry.url}
    prefixes = _dir_prefixes(input_dir)
    for path in paths:
        rel = os.path.relpath(path, input_dir).replace(os.sep, '/')
        hits = {by_local[p + rel] for p in prefixes if p + rel in by_local}
        if len(hits) == 1:
            res.urls[rel] = hits.pop()
            res.from_manifest += 1
            continue
        if hits:
            res.missing.append((rel, AMBIGUOUS))
            continue
        reason = NO_SOURCE
        if path.lower().endswith(('.html', '.htm')):
            with open(path, 'rb') as fh:
                head = fh.read(MARKER_SCAN_BYTES).decode('utf-8', errors='replace')
            url, problem = marker_url(head)
            if url:
                res.urls[rel] = url
                res.from_marker += 1
                continue
            reason = problem or NO_SOURCE
        res.missing.append((rel, reason))
    res.missing.sort()
    return res


def format_url_summary(res: UrlResolution, verbose: bool) -> list[str]:
    """Pack summary lines: counts, then the files left without a URL."""
    lines = [f"Source URLs:     {res.from_manifest} from manifest, "
             f"{res.from_marker} from page markers, {len(res.missing)} without"]
    reasons = [reason for _, reason in res.missing]
    if INVALID in reasons or CONFLICTING in reasons:
        lines.append(f"Rejected markers: {reasons.count(INVALID)} invalid, "
                     f"{reasons.count(CONFLICTING)} conflicting")
    shown = res.missing if verbose else res.missing[:MAX_SHOWN_MISSING]
    lines.extend(neutralize_controls(f"  {rel}: {reason}") for rel, reason in shown)
    if len(shown) < len(res.missing):
        lines.append(f"  ... {len(res.missing) - len(shown)} more (use --verbose)")
    return lines
