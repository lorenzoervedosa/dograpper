"""Linear one-pass HTML reading shared by the generator adapters (ADR-0009).

``Regions`` keeps the text of the regions an adapter opens, as lines. Each element
is pushed and popped once and a stray end tag is dropped in O(1), so hostile markup
(deep nesting, unclosed or stray tags) stays linear in the page size.
"""

from html.parser import HTMLParser
from typing import List, Optional

VOID = frozenset(("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                  "source", "track", "wbr"))
# Elements that start and end a line. dt only starts one and dd only ends one, so a note
# reads "Returns: the number of items".
BLOCK = frozenset(("address", "article", "aside", "blockquote", "caption", "details", "div",
                   "dl", "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
                   "header", "li", "main", "nav", "ol", "p", "pre", "section", "summary",
                   "table", "td", "th", "tr", "ul"))


class Text:
    """Lines of one region of the page: whitespace collapses, except inside <pre>."""

    def __init__(self):
        self.lines: List[str] = []
        self._buf: List[str] = []
        self.pre = 0

    def add(self, data: str) -> None:
        if self.pre:
            *done, data = data.split("\n")
            for part in done:
                self._buf.append(part)
                self.flush()
        self._buf.append(data)

    def flush(self) -> None:
        line = "".join(self._buf)
        self._buf = []
        line = line.rstrip() if self.pre else " ".join(line.split())
        if line.strip():
            self.lines.append(line)

    def end_pre(self) -> None:
        self.pre -= 1

    def final(self) -> List[str]:
        self.flush()
        return self.lines


def line(text: Optional[Text]) -> str:
    """The region's lines joined into one; "" for a region that never opened."""
    return " ".join(text.final()) if text else ""


class Regions(HTMLParser):
    """One pass over a page. Subclasses open regions and track state in ``start``."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._stack = []   # (tag, closers) of the open elements
        self._open = {}    # tag -> count on the stack: a stray end tag is dropped in O(1)
        self._sinks = []   # regions whose text is kept, innermost last
        self._raw = 0      # inside <script>, <style> or a skipped element
        self._copy: Optional[Text] = None  # also gets the text, see copy_until_end

    def start(self, tag: str, attr: dict, classes: List[str], closers: list) -> None:
        """Called for each non-void start tag outside <script>/<style>; ``closers`` run at its end tag."""

    def region(self, closers) -> Text:
        """A new region that collects the text until the element ends."""
        text = Text()
        self._sinks.append(text)
        closers.append(self._sinks.pop)
        return text

    def set_until_end(self, name: str, value, closers) -> None:
        """Set attribute ``name`` to ``value`` until the element ends, then restore the previous value."""
        previous = getattr(self, name)
        setattr(self, name, value)
        closers.append(lambda: setattr(self, name, previous))

    def copy_until_end(self, text: Text, closers) -> None:
        """Add the element's text to ``text`` too until the element ends; the region it is in
        keeps it as well, e.g. a name inside a signature line. sphinx.py and typedoc.py still
        carry their own copy of this (``_tap``)."""
        self.set_until_end("_copy", text, closers)

    def skip(self, closers) -> None:
        """Drop the element's text, e.g. a permalink sign."""
        self._raw += 1
        closers.append(self._end_raw)

    def _end_raw(self) -> None:
        self._raw -= 1

    def handle_starttag(self, tag, attrs):
        sink = self._sinks[-1] if self._sinks else None
        if tag in VOID:
            if tag in ("br", "hr") and sink is not None:
                sink.flush()
            return
        closers = []
        self._stack.append((tag, closers))
        self._open[tag] = self._open.get(tag, 0) + 1
        if tag in ("script", "style"):
            self.skip(closers)
            return
        if sink is not None:
            if tag in BLOCK or tag == "dt":
                sink.flush()
            if tag == "pre":
                sink.pre += 1
                closers.append(sink.end_pre)
            if tag in BLOCK or tag == "dd":
                closers.append(sink.flush)  # closers run last-in first-out: flush, then end_pre
            if tag == "dd":
                sink.add(" ")
        attr = dict(attrs)
        self.start(tag, attr, (attr.get("class") or "").split(), closers)

    def handle_endtag(self, tag):
        if not self._open.get(tag):
            return
        while True:
            open_tag, closers = self._stack.pop()
            self._open[open_tag] -= 1
            for close in reversed(closers):
                close()
            if open_tag == tag:
                return

    def handle_data(self, data):
        if self._raw:
            return
        if self._sinks:
            self._sinks[-1].add(data)
        if self._copy is not None:
            self._copy.add(data)
