"""API reference pages split into container and member records (ADR-0009): detection and dispatch.

A page is split only when the generator it declares has an adapter here and its
markup is the measured one. Any other page keeps one record and is reported,
with the reason, by ``format_kept_whole``.
"""

import os
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from urllib.parse import quote

from ..generator import page_generator
from ..redact import neutralize_controls

NO_ADAPTER = "no supported generator"
# Shown before "... N more (use --verbose)"; same cap as lib/source_urls.py MAX_SHOWN_MISSING.
MAX_SHOWN_KEPT_WHOLE = 10


class NotSplit(Exception):
    """The page keeps one record; the message says why."""


@dataclass
class ApiRecord:
    text: str
    symbol: str          # qualified name
    kind: str            # "container" | "member"
    symbol_kind: str     # e.g. "class", "method"
    breadcrumb: List[str]
    generator: str
    anchor: str = ""     # "" for the page's main container
    container: str = ""  # qualified name of the container, member records only

    def url(self, page_url: str) -> str:
        """``page_url`` pointing at this record's anchor, percent-encoded as the generator links it."""
        if not self.anchor:
            return page_url
        return page_url.split("#", 1)[0] + "#" + quote(self.anchor, safe="!$&'()*+,;=:@/?")


@dataclass
class ApiSplit:
    records: Dict[str, List[ApiRecord]] = field(default_factory=dict)  # relative path -> records
    kept_whole: List[Tuple[str, str]] = field(default_factory=list)    # (relative path, reason), sorted

    @property
    def texts(self) -> Dict[str, str]:
        """Each split page's text: what its records hold, for word counts and query ranking."""
        return {rel: "\n\n".join(r.text for r in recs) for rel, recs in self.records.items()}


def split_page(html: str) -> List[ApiRecord]:
    """Records of one page, its main container first. Raises NotSplit when it is not split."""
    generator = page_generator(html)
    if generator and generator.startswith("javadoc/"):
        from . import javadoc
        return javadoc.records(html, generator)
    raise NotSplit(NO_ADAPTER)


def split_api_pages(paths, input_dir: str) -> ApiSplit:
    """Split every HTML page in ``paths``; other files are not pages and are left alone."""
    split = ApiSplit()
    for path in paths:
        if not path.lower().endswith(('.html', '.htm')):
            continue
        rel = os.path.relpath(path, input_dir).replace(os.sep, '/')
        with open(path, 'r', encoding='utf-8', errors='replace') as fh:
            html = fh.read()
        try:
            split.records[rel] = split_page(html)
        except NotSplit as e:
            split.kept_whole.append((rel, str(e)))
    split.kept_whole.sort()
    return split


def format_kept_whole(split: ApiSplit, verbose: bool) -> List[str]:
    """Warning lines for the pages that keep one record; [] when every page was split."""
    if not split.kept_whole:
        return []
    shown = split.kept_whole if verbose else split.kept_whole[:MAX_SHOWN_KEPT_WHOLE]
    lines = [f"Warning: {len(split.kept_whole)} page(s) kept as one record each, "
             f"not split into API records:"]
    lines.extend(neutralize_controls(f"  {rel}: {reason}") for rel, reason in shown)
    if len(shown) < len(split.kept_whole):
        lines.append(f"  ... {len(split.kept_whole) - len(shown)} more (use --verbose)")
    return lines


def format_summary(split: ApiSplit) -> str:
    """The pack summary line."""
    recs = [r for page in split.records.values() for r in page]
    containers = sum(r.kind == "container" for r in recs)
    return (f"API records:     {len(split.records)} pages split into {len(recs)} records "
            f"({containers} container, {len(recs) - containers} member), "
            f"{len(split.kept_whole)} pages kept whole")
