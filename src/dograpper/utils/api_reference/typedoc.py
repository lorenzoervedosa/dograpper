"""TypeDoc adapter (ADR-0009): one page per TypeScript symbol as container and member records.

TypeDoc writes no generator meta, so a page is recognised by the markup measured on
TypeDoc 0.28.0 and 0.28.20 (default theme, English): inside ``div.col-content``, a
``div.tsd-page-title`` with the symbol's path in ``ul.tsd-breadcrumb`` (its last crumb
marked ``aria-current="page"``, which 0.25-0.27 do not write) and its kind and name in
the ``h1`` ("Class Box<T>"), then one ``details.tsd-member-group`` per group whose ``h2``
names it. A class, interface or enum page holds one ``section.tsd-member`` per member,
its anchor on the ``h3``; a module or namespace page lists its exports in
``dl.tsd-member-summaries``.

The page's symbol (TypeDoc's reflection) is its main record. Modules, namespaces,
classes, interfaces and enums, and any other page that holds members, get a container
record: the page text outside the members (title, comment, type parameters, hierarchy),
the declared member names by group and the inherited ones by base. Every other page (a
function, a variable, a type alias) is one member record. Each own member gets a member
record; the index, summaries, permalink signs and Copy buttons are dropped. Any other
markup raises NotSplit.
"""

from typing import Dict, List, Optional

from . import ApiRecord, NotSplit, check_symbol
from ._html import Regions, Text

GENERATOR = "typedoc"
# Start of every TypeDoc page title block; __init__ recognises a TypeDoc page by it.
TITLE = '<div class="tsd-page-title">'
NOT_API = "TypeDoc page, not an API page"

# First word(s) of the h1 -> (record kind, symbol_kind). A page that holds members is a container.
_PAGES = {
    "Module": ("container", "module"),
    "Namespace": ("container", "namespace"),
    "Class": ("container", "class"),
    "Interface": ("container", "interface"),
    "Enumeration": ("container", "enum"),
    "Function": ("member", "function"),
    "Variable": ("member", "variable"),
    "Type Alias": ("member", "type_alias"),
}
# Class of the first tsd-kind-* span in a member's signature -> symbol_kind.
_MEMBERS = {
    "tsd-kind-property": "property",
    "tsd-kind-call-signature": "method",
    "tsd-kind-constructor-signature": "constructor",
    "tsd-kind-get-signature": "accessor",
    "tsd-kind-set-signature": "accessor",
    "tsd-kind-enum-member": "enum_member",
}
_INHERITED = "Inherited from "


class _Group:
    def __init__(self):
        self.label: Optional[Text] = None
        self.names: List[Text] = []  # module and namespace pages: one dt per export


class _Member:
    def __init__(self, depth: int, group: Optional[_Group], classes: List[str]):
        self.depth = depth  # stack size with this member's section open: its own h3 sits one deeper
        self.group = group
        self.inherited = "tsd-is-inherited" in classes
        self.anchor: Optional[str] = None
        self.name: Optional[Text] = None
        self.tags: List[Text] = []
        self.body: Optional[Text] = None
        self.kind: Optional[str] = None  # the tsd-kind-* class, None until the first signature names it
        self.signed = False              # inside the first div.tsd-signature
        self.source: Optional[Text] = None  # first aside.tsd-sources: "Inherited from Error.cause"


class _Page(Regions):
    """One pass over the page (linear, see _html.Regions)."""

    def __init__(self):
        super().__init__()
        self.content: Optional[Text] = None
        self.title: Optional[Text] = None
        self.tags: List[Text] = []
        self.crumbs: List[Text] = []
        self.current = 0  # number of the crumb that links the page itself (aria-current), 0 for none
        self.groups: List[_Group] = []
        self.members: List[_Member] = []
        self.problem: Optional[str] = None
        self._in_content = self._in_crumbs = self._in_title = self._in_h3 = self._in_sources = False
        self._group: Optional[_Group] = None
        self._member: Optional[_Member] = None
        self._tap: Optional[Text] = None  # aside being read; it also feeds the member's body

    # _set and the _tap in handle_data: second copy of sphinx._Page's.
    def _set(self, name, value, closers) -> None:
        previous = getattr(self, name)
        setattr(self, name, value)
        closers.append(lambda: setattr(self, name, previous))

    def start(self, tag, attr, classes, closers):
        if not self._in_content:
            if tag == "div" and "col-content" in classes and self.content is None:
                self.content = self.region(closers)
                self._set("_in_content", True, closers)
            return
        member = self._member
        if (tag == "button" or (tag == "a" and "tsd-anchor-icon" in classes)
                or (tag == "section" and "tsd-index-group" in classes)
                or (tag == "dd" and "tsd-member-summary" in classes)):
            self.skip(closers)  # Copy button, permalink sign, index, summary text
        elif tag == "ul" and "tsd-breadcrumb" in classes:
            self._set("_in_crumbs", True, closers)
        elif tag == "li" and self._in_crumbs:
            self.crumbs.append(self.region(closers))
        elif tag == "a" and self._in_crumbs and attr.get("aria-current") == "page":
            self.current = len(self.crumbs)
        elif tag == "h1" and self.title is None and member is None:
            self.title = self.region(closers)
            self._set("_in_title", True, closers)
        elif tag == "code" and "tsd-tag" in classes:
            if self._in_title:
                self.tags.append(self.region(closers))
            elif self._in_h3:
                member.tags.append(self.region(closers))
            elif self._sinks:
                sink = self._sinks[-1]
                closers.append(lambda: sink.add(" "))  # "Readonly" ends before the name it qualifies
        elif tag == "details" and "tsd-member-group" in classes:
            group = _Group()
            self.groups.append(group)
            self._set("_group", group, closers)
        elif tag == "h2" and self._group is not None and self._group.label is None and member is None:
            self._group.label = self.region(closers)
        elif tag == "dt" and "tsd-member-summary" in classes and self._group is not None:
            self._group.names.append(self.region(closers))
        elif tag == "aside" and "tsd-sources" in classes:
            self._set("_in_sources", True, closers)
            if member is not None and member.source is None:
                member.source = Text()
                self._set("_tap", member.source, closers)
        elif tag == "ul" and self._in_sources:
            self.skip(closers)  # "Defined in" source locations, like Sphinx's [source] links
        elif tag == "section" and "tsd-member" in classes:
            if member is not None:
                self.problem = self.problem or "a member inside a member"
                return
            member = _Member(len(self._stack), self._group, classes)
            self.members.append(member)
            member.body = self.region(closers)
            self._set("_member", member, closers)
        elif member is None:
            return
        elif tag == "h3" and member.name is None and len(self._stack) == member.depth + 1:
            member.anchor = attr.get("id")
            member.name = self.region(closers)
            self._set("_in_h3", True, closers)
        elif tag == "div" and "tsd-signature" in classes and member.kind is None and not member.signed:
            member.signed = True
            closers.append(lambda: setattr(member, "signed", False))
        elif tag == "span" and member.signed and member.kind is None:
            kind_classes = [c for c in classes if c.startswith("tsd-kind-")]
            if kind_classes:
                member.kind = kind_classes[0]

    def handle_data(self, data):
        super().handle_data(data)
        if self._tap is not None and not self._raw:
            self._tap.add(data)


# _unsupported: same shape as javadoc's and sphinx's; _line: second copy of sphinx._line.
def _unsupported(problem: str) -> NotSplit:
    return NotSplit(f"unsupported TypeDoc markup: {problem}")


def _line(text: Optional[Text]) -> str:
    return " ".join(text.final()) if text else ""


def _tags(tags: List[Text]) -> List[str]:
    """The flags line ("Static Readonly"), or nothing."""
    line = " ".join(filter(None, (_line(t) for t in tags)))
    return [line] if line else []


def _kind(title: str, name: str):
    """(record kind, symbol_kind) of an h1 such as "Class Box<T>" naming ``name``, or None."""
    for prefix, kinds in _PAGES.items():
        rest = title[len(prefix) + 1:]
        if title.startswith(prefix + " ") and (rest == name or rest.startswith(name + "<")):
            return kinds
    return None


def records(html: str) -> List[ApiRecord]:
    """The page's main record first, then one record per own member in page order."""
    page = _Page()
    page.feed(html)
    page.close()

    if page.content is None:
        raise _unsupported("no div.col-content")
    if page.problem is not None:
        raise _unsupported(page.problem)
    crumbs = [_line(c) for c in page.crumbs]
    title = _line(page.title)
    if not crumbs or not all(crumbs):
        raise NotSplit(NOT_API)  # readme, hierarchy, the project's own index
    if page.current != len(crumbs):  # TypeDoc 0.25-0.27: the path starts at the project, no current page
        raise _unsupported("a breadcrumb without the current page")
    symbol = ".".join(crumbs)
    check_symbol(symbol, _unsupported)
    page_kind = _kind(title, crumbs[-1])
    if page_kind is None:
        raise _unsupported(f"unknown page kind in {title[:40]!r}")
    kind, symbol_kind = page_kind

    anchors = set()
    own: List[_Member] = []
    inherited: Dict[str, List[str]] = {}  # base -> member names, in page order
    for member in page.members:
        name = _line(member.name)
        if not name or not member.anchor:
            raise _unsupported("a section.tsd-member without an h3 id")
        if member.anchor in anchors:
            raise _unsupported("duplicate member anchor")
        anchors.add(member.anchor)
        if member.inherited:
            source = _line(member.source)
            if not source.startswith(_INHERITED) or "." not in source:
                raise _unsupported("an inherited member without its base")
            inherited.setdefault(source[len(_INHERITED):].rpartition(".")[0], []).append(name)
            continue
        if member.group is None or not _line(member.group.label):
            raise _unsupported("a member outside a member group")
        if member.kind not in _MEMBERS:
            raise _unsupported(f"unknown member kind {member.kind or 'without a signature'}")
        check_symbol(f"{symbol}.{name}", _unsupported)
        own.append(member)
    if own and kind == "member":
        if symbol_kind != "type_alias":
            raise _unsupported(f"a {symbol_kind} page that lists members")
        kind = "container"  # a type alias of an object type: its properties are its members
    if kind == "member" and (inherited or any(g.names for g in page.groups)):
        raise _unsupported(f"a {symbol_kind} page that lists members")

    main = page.content.final()
    if kind == "member":
        container = ".".join(crumbs[:-1])
        return [ApiRecord(text="\n".join([symbol] + _tags(page.tags) + main), symbol=symbol,
                          kind="member", symbol_kind=symbol_kind,
                          breadcrumb=[container, crumbs[-1]] if container else [symbol],
                          generator=GENERATOR, container=container)]

    declared: Dict[str, Dict[str, None]] = {}  # group label -> ordered set of names (as javadoc, sphinx)
    for group in page.groups:
        for name in group.names:
            declared.setdefault(_line(group.label), {})[_line(name)] = None
    for member in own:
        declared.setdefault(_line(member.group.label), {})[_line(member.name)] = None
    lines = ([f"{symbol} ({symbol_kind})"] + _tags(page.tags) + [title] + main
             + [f"{label}: {', '.join(names)}" for label, names in declared.items()]
             + [f"{_INHERITED}{base}: {', '.join(names)}" for base, names in inherited.items()])
    result = [ApiRecord(text="\n".join(lines), symbol=symbol, kind="container",
                        symbol_kind=symbol_kind, breadcrumb=[symbol], generator=GENERATOR)]
    for member in own:
        name = _line(member.name)
        result.append(ApiRecord(
            text="\n".join([f"{symbol}.{name}"] + _tags(member.tags) + member.body.final()),
            symbol=f"{symbol}.{name}", kind="member", symbol_kind=_MEMBERS[member.kind],
            breadcrumb=[symbol, name], generator=GENERATOR, anchor=member.anchor, container=symbol))
    return result
