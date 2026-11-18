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
- without a banner, the first hidden ``Version X`` category gives ``version``;
- a redirect alias (saved through a redirect: "Redirected from") holds its
  target's content under another file name. ``find_redirect_aliases`` names
  the ones whose target is in the run too, for ``pack`` to skip.

- a red link (``a.new``, or a ``redlink=1`` / ``action=edit`` target) becomes
  its plain text: the anchor tags are cut, the link text stays;
- a heading whose section a cut left without content is dropped with it (the
  "Navigation" heading of a navbox-only section), up to the next heading of
  the same or a higher level.

The cleanup cuts the dropped elements out of the page source, so the markup
around them reaches the extractor unchanged.
"""

import re
from html.parser import HTMLParser

from .generator import SCAN_CHARS, page_generator

_DROPPED_CLASSES = frozenset({"navbox", "mw-editsection"})
_MAINTENANCE_TOGGLE = "mw-customtoggle-mbox-"
_VERSION_TOGGLE = _MAINTENANCE_TOGGLE + "version"
_VERSION = r"(\d[\w.+-]{0,39})"
# The three wordings of the version banner, in order: current, outdated, older-build.
_BANNER = re.compile(r"This page (?:(has been revised for the current stable version)"
                     r"|was last updated for an older version( of the current build)?) "
                     rf"\(\s*{_VERSION}\s*\)")
_VERSION_CATEGORY = re.compile(rf"Category:Version {_VERSION}")
# The page's JS config: a redirect is served with its target's page name and the alias it came from.
_CONFIG = re.compile(r'"(wgPageName|wgRedirectedFrom)"\s*:\s*"((?:[^"\\]|\\.){1,500})"')
# Only these carry the classes above, so a void element never opens a region.
_REGION_TAGS = frozenset({"div", "span", "table"})
_RED_HREF = re.compile(r"[?&](?:redlink=1|action=edit)(?:&|$)")
_HEADINGS = {f"h{n}": n for n in range(1, 7)}
_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                   "source", "track", "wbr"})
# Left where a span was cut, so the heading pass knows which sections lost something.
_CUT = "dograpper-cut"


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


def page_config(head: str) -> dict:
    """``wgPageName`` / ``wgRedirectedFrom`` from a MediaWiki page head; ``{}`` for any other page."""
    return dict(_CONFIG.findall(head)) if is_mediawiki(head) else {}


def find_redirect_aliases(paths) -> list:
    """The redirect aliases among ``paths`` whose content another of ``paths`` already holds.

    That is every alias whose target page is in ``paths``; when the target is
    missing, the alias is its only copy and the first one (sorted) stays.
    """
    targets, aliases = set(), {}
    for path in sorted(paths):
        if not path.lower().endswith(('.html', '.htm')):
            continue
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as fh:
                head = fh.read(SCAN_CHARS)
        except OSError:
            continue  # unreadable files are reported by the stage that reads them
        config = page_config(head)
        name = config.get("wgPageName")
        if name and "wgRedirectedFrom" in config:
            aliases.setdefault(name, []).append(path)
        elif name:
            targets.add(name)
    return sorted(p for name, group in aliases.items()
                  for p in (group if name in targets else group[1:]))


def clean(html: str) -> str:
    """``html`` without its MediaWiki chrome; any other page is returned as is."""
    if not is_mediawiki(html):
        return html
    kept, pos = [], 0
    for start, end in sorted(_Scan(html).dropped):
        if start < pos:
            continue  # inside a span already cut
        kept.append(html[pos:start])
        kept.append(f"<!--{_CUT}-->")
        pos = end
    kept.append(html[pos:])
    return _drop_empty_headings("".join(kept)).replace(f"<!--{_CUT}-->", "")


class _Heading:
    """A heading under watch: its element (with the ``mw-heading`` wrapper, if any) and its section."""

    def __init__(self, start: int, depth: int):
        self.start, self.end = start, None   # source span of the element to drop; end is set at its end tag
        self.depth = depth      # open elements around it: the section ends when one of them closes
        self.level = None
        self.cut = self.content = False


class _EmptyHeadings(HTMLParser):
    """``spans`` holds the headings whose section holds a cut and nothing else but blanks."""

    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self._html = html
        self._line_starts = [0] + [m.end() for m in re.finditer("\n", html)]
        self._stack = []        # (tag, _Heading or None)
        self._open = []         # headings whose section is still open
        self.spans = []
        self.feed(html)
        self.close()
        self._finish(0)

    def _offset(self) -> int:
        line, col = self.getpos()
        return self._line_starts[line - 1] + col

    def _finish(self, level: int):
        """Close the open headings of ``level`` or deeper (0: all of them)."""
        for h in [h for h in self._open if h.level >= level]:
            self._end_section(h)

    def handle_starttag(self, tag, attrs):
        classes = (dict(attrs).get("class") or "").split()
        own = None
        if tag in _HEADINGS:
            top = self._stack[-1][1] if self._stack else None
            if top is not None and top.level is None:   # inside its mw-heading wrapper
                top.level = _HEADINGS[tag]
            else:
                own = _Heading(self._offset(), len(self._stack))
                own.level = _HEADINGS[tag]
            if own is not None or top is not None:
                self._finish(_HEADINGS[tag])    # same or higher level: the sections before it end
                self._open.append(own or top)
        elif tag == "div" and "mw-heading" in classes:
            own = _Heading(self._offset(), len(self._stack))
        if tag not in _VOID:
            self._stack.append((tag, own))
        if tag == "img":
            self._mark_content()

    def handle_startendtag(self, tag, attrs):
        if tag == "img":
            self._mark_content()

    def handle_comment(self, data):
        if data == _CUT:    # a cut inside the heading's own element (its edit link) is not the section's
            for h in self._open:
                h.cut = h.cut or h.end is not None

    def handle_data(self, data):
        if data.strip():
            self._mark_content()

    def _mark_content(self):
        # Text inside a heading's own element is the heading, not its section.
        for h in self._open:
            if h.end is not None:
                h.content = True

    def handle_endtag(self, tag):
        open_tags = [t for t, _ in self._stack]
        if tag not in open_tags:
            return
        at = len(open_tags) - 1 - open_tags[::-1].index(tag)
        end = self._html.index(">", self._offset()) + 1
        for _, h in self._stack[at:]:
            if h is not None and h.end is None:
                h.end = end
        del self._stack[at:]
        self._finish_sections()

    def _finish_sections(self):
        for h in [h for h in self._open if h.end is not None and len(self._stack) < h.depth]:
            self._end_section(h)

    def _end_section(self, h: _Heading):
        self._open.remove(h)
        if h.cut and not h.content and h.end is not None:
            self.spans.append((h.start, h.end))


def _drop_empty_headings(html: str) -> str:
    spans = _EmptyHeadings(html).spans
    if not spans:
        return html
    kept, pos = [], 0
    for start, end in sorted(spans):
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
        if tag == "a" and not self._dropping and ("new" in classes
                                                  or _RED_HREF.search(attrs.get("href") or "")):
            start = self._offset()
            region = _Region(start, "redlink")
            region.tag_end = start + len(self.get_starttag_text())
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
            if region.kind == "redlink":    # only the tags go; an unclosed anchor has no end tag to cut
                if not self._dropping:
                    self.dropped.append((region.start, region.tag_end))
                    if i == at:
                        self.dropped.append((start, end))
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
