"""MediaWiki page cleanup (#88): wiki chrome leaves the text before the generic extractor runs.

Page-level only: it writes no records. The record adapters of ADR-0009 split
API reference pages, and a wiki page is not one. A page is MediaWiki when its
generator meta says so (``utils/generator.py``). Measured on MediaWiki 1.43
(pzwiki.net, Citizen skin):

- ``navbox`` and ``mw-editsection`` elements are dropped;
- a maintenance box is an ``mbox`` holding a ``mw-customtoggle-mbox-*`` toggle
  (stub, outdated, improve: the "help update" boxes). It is dropped. A note box
  has no toggle and stays;
- the version box (``mw-customtoggle-mbox-version``) becomes page metadata,
  ``version`` and ``version_status`` (``page_metadata``), for the context
  header. A version box whose wording is not recognised stays in the text,
  so the version is never lost;
- without a banner, the first hidden ``Version X`` category gives ``version``.

The cleanup cuts the dropped elements out of the page source, so the markup
around them reaches the extractor unchanged.
"""

import re
from html.parser import HTMLParser

from .generator import page_generator

_DROPPED_CLASSES = frozenset({"navbox", "mw-editsection"})
_MAINTENANCE_TOGGLE = "mw-customtoggle-mbox-"
_VERSION_TOGGLE = _MAINTENANCE_TOGGLE + "version"
_VERSION = r"(\d[\w.+-]{0,39})"
# The three wordings of the version banner, in order: current, outdated, older-build.
_BANNER = re.compile(r"This page (?:(has been revised for the current stable version)"
                     r"|was last updated for an older version( of the current build)?) "
                     rf"\(\s*{_VERSION}\s*\)")
_VERSION_CATEGORY = re.compile(rf"Category:Version {_VERSION}")
# Only these carry the classes above, so a void element never opens a region.
_REGION_TAGS = frozenset({"div", "span", "table"})


def is_mediawiki(html: str) -> bool:
    return (page_generator(html) or "").startswith("MediaWiki")


def page_metadata(html: str) -> dict:
    """``version`` and ``version_status`` of a MediaWiki page, when it states them; else {}."""
    if not is_mediawiki(html):
        return {}
    scan = _Scan(html)
    if scan.banner:
        return dict(zip(("version", "version_status"), scan.banner))
    return {"version": scan.category_versions[0]} if scan.category_versions else {}


def clean(html: str) -> str:
    """``html`` without its MediaWiki chrome; any other page is returned as is."""
    if not is_mediawiki(html):
        return html
    kept, pos = [], 0
    for start, end in sorted(_Scan(html).dropped):
        if start < pos:
            continue  # inside a span already cut
        kept.append(html[pos:start])
        pos = end
    kept.append(html[pos:])
    return "".join(kept)


class _Region:
    """An element being scanned: where it starts and what it turned out to be."""

    def __init__(self, start: int, kind: str):
        self.start = start
        self.kind = kind        # "chrome", "box" (an mbox) or "categories" (hidden ones)
        self.drop = kind == "chrome"    # a box: once a maintenance toggle shows up inside
        self.version = False    # a box holding the version toggle
        self.text = []


class _Scan(HTMLParser):
    """One pass over a page: ``dropped`` holds the source span of each element to cut.

    An element still open at the end of the document is kept: without its end
    tag, dropping it would take the rest of the page with it.
    """

    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self._html = html
        self._line_starts = [0] + [m.end() for m in re.finditer("\n", html)]
        self._stack = []        # (tag, _Region or None) of every open element
        self._dropping = 0      # open regions known to be dropped
        self.dropped = []
        self.banner = None      # (version, status) of the first version banner read
        self.category_versions = []
        self.feed(html)
        self.close()

    def _offset(self) -> int:
        line, col = self.getpos()
        return self._line_starts[line - 1] + col

    def _open(self, kind: str):
        return next((r for _, r in reversed(self._stack) if r is not None and r.kind == kind), None)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = (attrs.get("class") or "").split()
        # Inside a dropped region every box is cut anyway; outside one, no open box is dropped yet.
        toggles = [c for c in classes if c.startswith(_MAINTENANCE_TOGGLE)]
        box = self._open("box") if toggles and not self._dropping else None
        if box is not None and _VERSION_TOGGLE in toggles:
            box.version = True
        elif box is not None:
            box.drop = True
            self._dropping += 1
        if tag == "a" and self._open("categories"):
            m = _VERSION_CATEGORY.match(attrs.get("title") or "")
            if m:
                self.category_versions.append(m.group(1))
        region = None
        if not self._dropping and tag in _REGION_TAGS:
            if _DROPPED_CLASSES.intersection(classes):
                region = _Region(self._offset(), "chrome")
                self._dropping += 1
            elif "mbox" in classes:
                region = _Region(self._offset(), "box")
            elif "mw-hidden-catlinks" in classes:
                region = _Region(self._offset(), "categories")
        self._stack.append((tag, region))

    def handle_data(self, data):
        box = self._open("box")
        if box is not None:
            box.text.append(data)

    def handle_startendtag(self, tag, attrs):
        start = self._offset()
        self.handle_starttag(tag, attrs)
        self._close(len(self._stack) - 1, start, start + len(self.get_starttag_text()))

    def handle_endtag(self, tag):
        open_tags = [t for t, _ in self._stack]
        if tag in open_tags:
            start = self._offset()
            self._close(len(open_tags) - 1 - open_tags[::-1].index(tag),
                        start, self._html.index(">", start) + 1)

    def _close(self, at: int, start: int, end: int):
        """Close the element at stack index ``at``, whose end tag spans [start, end).

        Elements opened after it never got their own end tag: they end where it does.
        """
        for i in range(len(self._stack) - 1, at - 1, -1):
            region = self._stack[i][1]
            if region is None:
                continue
            if region.drop:
                self._dropping -= 1
            if region.version:
                if not self._read_banner(region):
                    continue    # unknown wording: the version stays in the text
            elif not region.drop:
                continue
            if not self._dropping:
                self.dropped.append((region.start, end if i == at else start))
        del self._stack[at:]

    def _read_banner(self, box: _Region) -> bool:
        m = _BANNER.search(" ".join("".join(box.text).split()))
        if m and self.banner is None:
            self.banner = (m.group(3), "current" if m.group(1) else
                           "outdated" if m.group(2) else "older-build")
        return m is not None
