"""Javadoc adapter (ADR-0009): a javadoc 25 type page as one container record plus one record per member.

Reads the markup measured on javadoc 25 type pages (generator ``javadoc/ClassWriter``):
the kind and name in the ``h1.title`` title, the package link in the sub-navigation,
``div.inheritance``, ``section.class-description``, the summary's ``div.inherited-list``
blocks, and one ``section.detail[id]`` with a ``div.member-signature`` per member, inside
the section whose id names the member kind. Summary tables are dropped. A type page
with any other markup raises NotSplit.
"""

from html.parser import HTMLParser
from typing import List, Optional

from . import ApiRecord, NotSplit

GENERATOR = "javadoc"
TYPE_PAGE = "javadoc/ClassWriter"

# Start of the h1.title title -> symbol_kind; "Class " last, as it ends two longer prefixes.
_CONTAINER_KINDS = (("Annotation Interface ", "annotation"), ("Record Class ", "record"),
                    ("Enum Class ", "enum"), ("Interface ", "interface"), ("Class ", "class"))
# Id of the section holding one kind of member details -> (symbol_kind, label on the container record).
_MEMBER_SECTIONS = {
    "enum-constant-detail": ("enum_constant", "Enum constants"),
    "field-detail": ("field", "Fields"),
    "constructor-detail": ("constructor", "Constructors"),
    "method-detail": ("method", "Methods"),
    "annotation-interface-element-detail": ("element", "Elements"),
}
_VOID = frozenset(("area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta",
                   "source", "track", "wbr"))
# Elements that start and end a line. dt only starts one and dd only ends one, so a note
# reads "Returns: the number of items".
_BLOCK = frozenset(("address", "article", "aside", "blockquote", "caption", "details", "div",
                    "dl", "figcaption", "figure", "footer", "h1", "h2", "h3", "h4", "h5", "h6",
                    "header", "li", "main", "nav", "ol", "p", "pre", "section", "summary",
                    "table", "td", "th", "tr", "ul"))


class _Text:
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


class _Member:
    def __init__(self, anchor: Optional[str], group: Optional[tuple], text: _Text):
        self.anchor = anchor
        self.group = group
        self.text = text
        self.name: Optional[_Text] = None
        self.signature = False


class _TypePage(HTMLParser):
    """One pass over the page. Each element is pushed and popped once, so it stays linear."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._stack = []   # (tag, closers) of the open elements
        self._open = {}    # tag -> count on the stack: a stray end tag is dropped in O(1)
        self._sinks = []   # regions whose text is kept, innermost last
        self._members = []  # open section.detail
        self._group = None  # _MEMBER_SECTIONS value of the enclosing member section
        self._raw = 0       # inside <script> or <style>
        self._subnav = 0
        self.title: Optional[str] = None
        self.package: Optional[_Text] = None
        self.inheritance: List[_Text] = []
        self.descriptions: List[_Text] = []
        self.inherited: List[_Text] = []
        self.members: List[_Member] = []

    def _region(self, closers) -> _Text:
        text = _Text()
        self._sinks.append(text)
        closers.append(self._sinks.pop)
        return text

    def _set_group(self, group, closers) -> None:
        previous = self._group
        self._group = group
        closers.append(lambda: setattr(self, "_group", previous))

    def _end_raw(self) -> None:
        self._raw -= 1

    def _end_subnav(self) -> None:
        self._subnav -= 1

    def handle_starttag(self, tag, attrs):
        sink = self._sinks[-1] if self._sinks else None
        if tag in _VOID:
            if tag in ("br", "hr") and sink is not None:
                sink.flush()
            return
        closers = []
        self._stack.append((tag, closers))
        self._open[tag] = self._open.get(tag, 0) + 1
        if tag in ("script", "style"):
            self._raw += 1
            closers.append(self._end_raw)
            return
        if sink is not None:
            if tag in _BLOCK or tag == "dt":
                sink.flush()
            if tag == "pre":
                sink.pre += 1
                closers.append(sink.end_pre)
            if tag in _BLOCK or tag == "dd":
                closers.append(sink.flush)  # closers run last-in first-out: flush, then end_pre
            if tag == "dd":
                sink.add(" ")

        attr = dict(attrs)
        classes = (attr.get("class") or "").split()
        member = self._members[-1] if self._members else None
        if tag == "section":
            section_id = attr.get("id") or ""
            if "class-description" in classes:
                self.descriptions.append(self._region(closers))
            elif "detail" in classes:
                member = _Member(attr.get("id"), self._group, self._region(closers))
                self.members.append(member)
                self._members.append(member)
                closers.append(self._members.pop)
            elif section_id.endswith("-detail"):
                self._set_group(_MEMBER_SECTIONS.get(section_id), closers)
        elif tag == "div" and ("inheritance" in classes or "inherited-list" in classes):
            target = self.inheritance if "inheritance" in classes else self.inherited
            target.append(self._region(closers))
        elif tag == "div" and "member-signature" in classes and member is not None:
            member.signature = True
        elif tag == "h3" and member is not None and member.name is None:
            member.name = self._region(closers)
        elif tag == "h1" and "title" in classes and self.title is None:
            self.title = attr.get("title") or ""
        elif tag == "ol" and "sub-nav-list" in classes:
            self._subnav += 1
            closers.append(self._end_subnav)
        elif (tag == "a" and self._subnav and self.package is None
              and (attr.get("href") or "").endswith("package-summary.html")):
            self.package = self._region(closers)

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
        if self._sinks and not self._raw:
            self._sinks[-1].add(data)


def _unsupported(problem: str) -> NotSplit:
    return NotSplit(f"unsupported Javadoc markup: {problem}")


def records(html: str, generator: str) -> List[ApiRecord]:
    """Container record first, then one member record per member in page order."""
    if generator != TYPE_PAGE:
        raise NotSplit("Javadoc page, not a type page")
    page = _TypePage()
    page.feed(html)
    page.close()

    if len(page.descriptions) != 1:
        raise _unsupported(f"{len(page.descriptions) or 'no'} section.class-description")
    kind = name = None
    for prefix, symbol_kind in _CONTAINER_KINDS:
        if (page.title or "").startswith(prefix):
            kind, name = symbol_kind, page.title[len(prefix):].strip()
            break
    if not kind or not name:
        raise _unsupported("unknown type kind in the h1 title")
    package = " ".join(page.package.final()) if page.package else ""
    qualified = f"{package}.{name}" if package else name

    members: List[ApiRecord] = []
    declared = {}  # label -> {member name: None}, an ordered set in page order
    anchors = set()
    for m in page.members:
        if not m.anchor:
            raise _unsupported("a section.detail without an id")
        if m.anchor in anchors:
            raise _unsupported("duplicate member anchor")
        anchors.add(m.anchor)
        if m.group is None:
            raise _unsupported("a section.detail outside the known member sections")
        if not m.signature:
            raise _unsupported("a section.detail without a div.member-signature")
        short = " ".join(m.name.final()) if m.name else ""
        if not short:
            raise _unsupported("a section.detail without an h3")
        symbol_kind, label = m.group
        declared.setdefault(label, {})[short] = None
        member_name = short + (m.anchor[m.anchor.index("("):] if "(" in m.anchor else "")
        symbol = f"{qualified}#{member_name}"
        members.append(ApiRecord(
            text="\n".join([symbol] + m.text.final()), symbol=symbol, kind="member",
            symbol_kind=symbol_kind, breadcrumb=[qualified, member_name], generator=GENERATOR,
            anchor=m.anchor, container=qualified))

    lines = [f"{qualified} ({kind})"]
    chain = [" ".join(t.final()) for t in page.inheritance]
    if chain:
        lines.append("Inheritance: " + " > ".join(chain))
    lines.extend(page.descriptions[0].final())
    lines.extend(f"{label}: {', '.join(names)}" for label, names in declared.items())
    for inherited in page.inherited:
        heading, *listed = inherited.final() or [""]
        lines.append(f"{heading}: {' '.join(listed)}" if listed else heading)
    container = ApiRecord(text="\n".join(line for line in lines if line), symbol=qualified,
                          kind="container", symbol_kind=kind, breadcrumb=[qualified],
                          generator=GENERATOR)
    return [container] + members
