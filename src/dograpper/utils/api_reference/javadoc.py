"""Javadoc adapter (ADR-0009): a javadoc 25 type page as one container record plus one record per member.

Reads the markup measured on javadoc 25 type pages (generator ``javadoc/ClassWriter``):
the kind and name in the ``h1.title`` title, the package link in the sub-navigation,
``div.inheritance``, ``section.class-description``, the summary's ``div.inherited-list``
blocks, and one ``section.detail[id]`` with a ``div.member-signature`` per member, inside
the section whose id names the member kind. Summary tables are dropped. A type page
with any other markup raises NotSplit.
"""

from typing import List, Optional

from . import ApiRecord, NotSplit, check_anchor, check_symbol, declared
from ._html import Regions, Text, line

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


class _Member:
    def __init__(self, anchor: Optional[str], group: Optional[tuple], text: Text):
        self.anchor = anchor
        self.group = group
        self.text = text
        self.name: Optional[Text] = None
        self.signature = False


class _TypePage(Regions):
    """One pass over the page (linear, see _html.Regions)."""

    def __init__(self):
        super().__init__()
        self._members = []  # open section.detail
        self._group = None  # _MEMBER_SECTIONS value of the enclosing member section
        self._subnav = 0
        self.title: Optional[str] = None
        self.package: Optional[Text] = None
        self.inheritance: List[Text] = []
        self.descriptions: List[Text] = []
        self.inherited: List[Text] = []
        self.members: List[_Member] = []

    def _end_subnav(self) -> None:
        self._subnav -= 1

    def start(self, tag, attr, classes, closers):
        member = self._members[-1] if self._members else None
        if tag == "section":
            section_id = attr.get("id") or ""
            if "class-description" in classes:
                self.descriptions.append(self.region(closers))
            elif "detail" in classes:
                member = _Member(attr.get("id"), self._group, self.region(closers))
                self.members.append(member)
                self._members.append(member)
                closers.append(self._members.pop)
            elif section_id.endswith("-detail"):
                self.set_until_end("_group", _MEMBER_SECTIONS.get(section_id), closers)
        elif tag == "div" and ("inheritance" in classes or "inherited-list" in classes):
            target = self.inheritance if "inheritance" in classes else self.inherited
            target.append(self.region(closers))
        elif tag == "div" and "member-signature" in classes and member is not None:
            member.signature = True
        elif tag == "h3" and member is not None and member.name is None:
            member.name = self.region(closers)
        elif tag == "h1" and "title" in classes and self.title is None:
            self.title = attr.get("title") or ""
        elif tag == "ol" and "sub-nav-list" in classes:
            self._subnav += 1
            closers.append(self._end_subnav)
        elif (tag == "a" and self._subnav and self.package is None
              and (attr.get("href") or "").endswith("package-summary.html")):
            self.package = self.region(closers)


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
    package = line(page.package)
    qualified = f"{package}.{name}" if package else name
    check_symbol(qualified, _unsupported)

    members: List[ApiRecord] = []
    names = []  # (label, member name) in page order
    anchors = set()
    for m in page.members:
        if not m.anchor:
            raise _unsupported("a section.detail without an id")
        check_anchor(m.anchor, anchors, _unsupported, "duplicate member anchor")
        if m.group is None:
            raise _unsupported("a section.detail outside the known member sections")
        if not m.signature:
            raise _unsupported("a section.detail without a div.member-signature")
        short = line(m.name)
        if not short:
            raise _unsupported("a section.detail without an h3")
        symbol_kind, label = m.group
        names.append((label, short))
        member_name = short + (m.anchor[m.anchor.index("("):] if "(" in m.anchor else "")
        symbol = f"{qualified}#{member_name}"
        check_symbol(symbol, _unsupported)
        members.append(ApiRecord(
            text="\n".join([symbol] + m.text.final()), symbol=symbol, kind="member",
            symbol_kind=symbol_kind, breadcrumb=[qualified, member_name], generator=GENERATOR,
            anchor=m.anchor, container=qualified))

    lines = [f"{qualified} ({kind})"]
    chain = [" ".join(t.final()) for t in page.inheritance]
    if chain:
        lines.append("Inheritance: " + " > ".join(chain))
    lines.extend(page.descriptions[0].final())
    lines.extend(declared(names))
    for inherited in page.inherited:
        heading, *listed = inherited.final() or [""]
        lines.append(f"{heading}: {' '.join(listed)}" if listed else heading)
    container = ApiRecord(text="\n".join(ln for ln in lines if ln), symbol=qualified,
                          kind="container", symbol_kind=kind, breadcrumb=[qualified],
                          generator=GENERATOR)
    return [container] + members
