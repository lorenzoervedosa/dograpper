"""Doxygen adapter (ADR-0009): a Doxygen page of C or C++ as container and member records.

Reads the markup measured on Doxygen 1.9.8 (generator meta ``Doxygen 1.9.8``): the page's
kind and qualified name in ``div.headertitle > div.title`` ("shapes::Box< T, N > Class
Template Reference"), and inside ``div.contents`` the summary tables (``table.memberdecls``,
one ``h2.groupheader`` per section, one ``tr.memitem`` row per member), then the description
and one documentation section per member kind.

A class, struct, union or namespace page, a file page that documents members, or a topic
(group) page that documents members in sections, is a container record: the page text
outside the members and the summary tables, then the names of the summary tables by
section, inherited ones by base. Each member Doxygen documents on
the page gets a member record. A member with a detailed section (an anchor, ``h2.memtitle``,
then ``div.memitem``) is that section: template headers, signature, labels, documentation.
A member with only a brief description has no section: its anchor sits in its summary row
(a member template's, in its template header row), so the row and its brief are the record.
Summary rows that link to a section are dropped, like the inheritance diagrams, the
permalink signs, the "generated from" footer and the source browser's "Definition at line ..."
and "References ..." lines. A file page names its members alone and
leaves out the ones of the namespaces it lists, which have pages of their own; a topic page
names each member as its summary row does ("algo::count", a \\relates one bare). Overloads
that Doxygen gives one anchor are one member record holding each of them in page order. Index,
listing, source and the other topic pages keep one record; any other markup raises NotSplit.
"""

from typing import Dict, List, Optional, Tuple

from . import ApiRecord, NotSplit, check_symbol, declared
from ._html import Regions, Text, line

GENERATOR = "doxygen"
MEASURED_VERSION = "1.9.8"
NOT_API = "Doxygen index, listing, source or topic page"

# Title "<name> <kind> Reference" -> symbol_kind of the page's container record.
_PAGES = {
    "Class Template": "class", "Class": "class",
    "Struct Template": "struct", "Struct": "struct",
    "Union Template": "union", "Union": "union",
    "Namespace": "namespace",
    "File": "file",
}
_LISTING_PAGES = ("Directory",)
_REFERENCE = " Reference"
# How a section's members get their symbol_kind: _BY_TYPE_WORD, a type's declaration starts with
# typedef, using or enum; _BY_DECLARATION, a friend or related symbol can be anything (_declared_kind).
_BY_TYPE_WORD, _BY_DECLARATION = "by type word", "by declaration"
_TYPE_WORDS = {"typedef": "typedef", "using": "typedef", "enum": "enum"}
# Summary section -> symbol_kind of a member documented in its row.
_SUMMARY = {
    **dict.fromkeys(("Public Member Functions", "Protected Member Functions", "Private Member Functions",
                     "Static Public Member Functions", "Static Protected Member Functions",
                     "Static Private Member Functions", "Functions"), "function"),
    **dict.fromkeys(("Public Attributes", "Protected Attributes", "Private Attributes",
                     "Static Public Attributes", "Static Protected Attributes", "Static Private Attributes",
                     "Variables", "Data Fields"), "variable"),
    **dict.fromkeys(("Public Types", "Protected Types", "Private Types"), _BY_TYPE_WORD),
    **dict.fromkeys(("Friends", "Related Symbols"), _BY_DECLARATION),
    "Typedefs": "typedef", "Enumerations": "enum", "Macros": "define",
}
# Documentation section (h2.groupheader after the description) -> symbol_kind of its members.
_SECTIONS = {
    **dict.fromkeys(("Member Typedef Documentation", "Typedef Documentation"), "typedef"),
    **dict.fromkeys(("Member Enumeration Documentation", "Enumeration Type Documentation"), "enum"),
    **dict.fromkeys(("Member Function Documentation", "Function Documentation",
                     "Constructor & Destructor Documentation"), "function"),
    "Friends And Related Symbol Documentation": _BY_DECLARATION,
    **dict.fromkeys(("Member Data Documentation", "Field Documentation", "Variable Documentation"), "variable"),
    "Macro Definition Documentation": "define",
}
_DESCRIPTION = "Detailed Description"
_NAMESPACES = "Namespaces"  # the summary section listing a file's documented namespaces
_ANONYMOUS_ENUM = "anonymous enum"  # how Doxygen titles the section of an enum with no name


class _Row:
    """One tr.memitem of a summary table."""

    def __init__(self, label: Optional[Text], inherited: bool, member: str):
        self.label = label  # the section's h2, or for an inherited row its "... inherited from" header
        self.inherited = inherited
        self.member = member  # the anchor in its "memitem:<anchor>" class: its member's, "" for a class
        self.text: Optional[Text] = None
        self.name: Optional[Text] = None    # copy of the first link or bold name of its right cell
        self.anchor: Optional[str] = None   # id of an anchor in the row: the member is documented here
        self.template = False               # a td.memTemplParams row: the next row's template header


class _Member:
    def __init__(self, anchor: str, section: Optional[Text], summary: bool):
        self.anchor = anchor
        self.section = section  # the summary section, or the h2 of its documentation section
        self.summary = summary  # documented in its summary row only
        self.signature: Optional[Text] = None  # its table.memname, or its summary row
        self.name: Optional[Text] = None
        self.parts: List[Tuple[Text, bool]] = []  # (region, read as one line), in page order


class _Page(Regions):
    """One pass over the page (linear, see _html.Regions)."""

    def __init__(self):
        super().__init__()
        self.title: Optional[Text] = None
        self.labels: Optional[Text] = None  # the page's labels, after its title
        self.contents: Optional[Text] = None
        self.members: List[_Member] = []
        self.sections: List[Text] = []  # h2 of the description and of each documentation section
        self.names: List[Tuple[Optional[Text], Text]] = []  # (section, name) of every summary row
        self.row_names: Dict[str, Text] = {}  # member anchor -> the name its summary row gives it
        self.problem: Optional[str] = None
        self._in_header = self._in_title = self._in_contents = self._right = False
        self._depth = 0          # stack size with div.contents open
        self._contents_closers: list = []
        self._footer = False
        self._section: Optional[Text] = None  # h2 of the current documentation section
        self._anchor: Optional[str] = None    # id of the anchor just before, at the top of div.contents
        self._titled: Optional[_Member] = None  # member whose h2.memtitle was read, waiting for its memitem
        self._member: Optional[_Member] = None  # member whose div.memitem is being read
        self._decls = False      # inside a summary table
        self._label: Optional[Text] = None    # h2 of the current summary table
        self._inherit: Optional[Text] = None  # header of the current inherited rows
        self._row: Optional[_Row] = None
        self._template: Optional[_Row] = None  # template header row waiting for its member's row
        self._last: Optional[_Member] = None   # summary member whose brief may follow

    def _fail(self, problem: str) -> None:
        self.problem = self.problem or problem  # the first one is reported

    def handle_starttag(self, tag, attrs):
        if tag == "hr" and self._in_contents and len(self._stack) == self._depth and not self._footer:
            self._footer = True  # "The documentation for this class was generated from ...": dropped
            self.skip(self._contents_closers)
        super().handle_starttag(tag, attrs)

    def start(self, tag, attr, classes, closers):
        if tag == "span" and "mlabel" in classes and self._sinks:
            sink = self._sinks[-1]
            closers.append(lambda: sink.add(" "))  # "inline" ends before the next label
            return
        if self.contents is None:
            if tag == "div" and "headertitle" in classes:
                self.set_until_end("_in_header", True, closers)
            elif tag == "div" and "title" in classes and self._in_header and self.title is None:
                self.title = self.region(closers)
                self.set_until_end("_in_title", True, closers)
            elif tag == "div" and "ingroups" in classes and self._in_title:
                self.skip(closers)  # the groups the symbol belongs to
            elif tag == "span" and "mlabels" in classes and self._in_title:
                self.labels = self.region(closers)  # "abstract", "final"
            elif tag == "div" and "contents" in classes:
                self.contents = self.region(closers)
                self.set_until_end("_in_contents", True, closers)
                self._depth = len(self._stack)
                self._contents_closers = closers
            return
        if not self._in_contents:
            return
        href = attr.get("href") or ""  # html.parser gives a valueless attribute None
        top = len(self._stack) == self._depth + 1  # a child of div.contents
        anchor = titled = None
        if top:
            anchor, self._anchor = self._anchor, None
            titled, self._titled = self._titled, None
            if titled is not None and not (tag == "div" and "memitem" in classes):
                self._fail("an h2.memtitle without its div.memitem")
        if ((tag == "span" and ("permalink" in classes or "overload" in classes))
                or (tag == "a" and href.endswith("#details"))
                # "Go to the source code of this file.", a link in a p of its own: the include
                # line's link to the same page sits one level deeper, in its code
                or (tag == "a" and href.endswith("_source.html")
                    and len(self._stack) == self._depth + 2)
                or (tag == "div" and ("dynheader" in classes or "dyncontent" in classes or "ttc" in classes))
                # SOURCE_BROWSER's "Definition at line N of file F." and "References ..." /
                # "Referenced by ...": line numbers that move with every release
                or (tag == "p" and ("definition" in classes or "reference" in classes))):
            self.skip(closers)  # permalink sign, "[1/2]" after an overloaded name, "More...", diagrams, code tooltips
        elif tag == "table" and "memberdecls" in classes:
            self.region(closers)  # summary text is dropped; rows, names and briefs are read below
            self.set_until_end("_decls", True, closers)
            self._label = self._inherit = self._template = self._last = None
        elif self._decls:
            self._decls_start(tag, attr, classes, closers)
        elif top:
            self._top_start(tag, attr, classes, closers, anchor, titled)
        elif self._member is not None:
            self._member_start(tag, classes, closers)

    def _top_start(self, tag, attr, classes, closers, anchor, titled):
        if tag == "a" and attr.get("id") and not attr.get("href"):
            self._anchor = attr["id"]
        elif tag == "h2" and "groupheader" in classes:
            self._section = self.region(closers)  # "Member Function Documentation": dropped from the text
            self.sections.append(self._section)
        elif tag == "h2" and "memtitle" in classes:
            if anchor is None:
                self._fail("an h2.memtitle without an anchor")
                return
            member = _Member(anchor, self._section, summary=False)
            member.name = self.region(closers)
            self.members.append(member)
            self._titled = member
        elif tag == "div" and "memitem" in classes:
            if titled is None:
                self._fail("a div.memitem without an h2.memtitle")
                return
            self.region(closers)  # the space between its parts
            self.set_until_end("_member", titled, closers)

    def _member_start(self, tag, classes, closers):
        parts = self._member.parts
        if (tag == "div" and "memtemplate" in classes) or (tag == "span" and "mlabels" in classes):
            parts.append((self.region(closers), True))  # a template header; the signature's labels
        elif tag == "table" and "memname" in classes:
            self._member.signature = self.region(closers)
            parts.append((self._member.signature, True))
        elif tag == "div" and "memdoc" in classes:
            parts.append((self.region(closers), False))

    def _decls_start(self, tag, attr, classes, closers):
        row = self._row
        row_class = classes[0] if classes else ""  # "memitem:<anchor>", "memdesc:<anchor>"
        if tag == "h2" and "groupheader" in classes:
            self._label = self.region(closers)
            self._inherit = None
        elif tag == "tr" and "inherit_header" in classes:
            self._inherit = self.region(closers)
        elif tag == "tr" and row_class.startswith("memitem:"):
            inherited = "inherit" in classes
            row = _Row(self._inherit if inherited else self._label, inherited, row_class[len("memitem:"):])
            row.text = self.region(closers)
            self.set_until_end("_row", row, closers)
            closers.append(lambda: self._end_row(row))
        elif tag == "tr" and row_class.startswith("memdesc:"):
            if self._last is not None and row_class[len("memdesc:"):] == self._last.anchor:
                self._last.parts.append((self.region(closers), False))
            self._last = None
        elif row is None:
            return
        elif tag == "td" and "memTemplParams" in classes:
            row.template = True
        elif tag == "td" and ("memItemRight" in classes or "memTemplItemRight" in classes):
            self.set_until_end("_right", True, closers)
        elif tag == "a" and attr.get("id") and row.anchor is None:
            row.anchor = attr["id"]
        elif tag in ("a", "b") and self._right and row.name is None:
            row.name = Text()
            self.copy_until_end(row.name, closers)

    def _end_row(self, row: _Row):
        self._last = None
        if row.template:
            self._template = row
            return
        template, self._template = self._template, None
        if template is not None and row.anchor is None:
            row.anchor = template.anchor  # a member template's anchor sits in its template header row
        if row.name is not None and _anonymous_enum(line(row.text), line(row.name)):
            row.name = Text()
            row.name.add(_ANONYMOUS_ENUM)  # the row names its first enumerator
        if row.name is not None:
            self.names.append((row.label, row.name))
            if row.member and not row.inherited:
                self.row_names.setdefault(row.member, row.name)
        if row.anchor is None or row.inherited:
            return
        if row.name is None:
            self._fail("a summary row without a name")
            return
        member = _Member(row.anchor, row.label, summary=True)
        member.name, member.signature = row.name, row.text
        member.parts = ([(template.text, True)] if template is not None else []) + [(row.text, True)]
        self.members.append(member)
        self._last = member


def _unsupported(problem: str) -> NotSplit:
    return NotSplit(f"unsupported Doxygen markup: {problem}")


def _kind(title: str, sections: bool):
    """(name, symbol_kind) of a title "<name> <kind> Reference", or of a topic (group) page's
    title "<name>" when the page has member ``sections``."""
    if not title.endswith(_REFERENCE):
        if sections:
            return title, "group"
        raise NotSplit(NOT_API)  # index, list, member list, source page, text page, or a topic page without sections
    for kind, symbol_kind in _PAGES.items():
        suffix = f" {kind}{_REFERENCE}"
        if title.endswith(suffix) and len(title) > len(suffix):
            return title[:-len(suffix)], symbol_kind
    kind = title[:-len(_REFERENCE)].rpartition(" ")[2]
    if kind in _LISTING_PAGES:
        raise NotSplit(NOT_API)
    raise _unsupported(f"page kind {kind}")


def _anonymous_enum(signature: str, name: str) -> bool:
    """Whether a summary row declares an enum with no name: "enum { First, Second }"."""
    head = signature.split("{", 1)[0]
    return signature.startswith("enum") and "{" in signature and name not in head.split()


def _declared_kind(signature: str) -> Optional[str]:
    """symbol_kind of a friend or related symbol by its declaration; None for a friend class,
    a relation rather than a member, documented on the class's own page."""
    words = signature.split()
    if words[:1] == ["friend"]:
        words = words[1:]
    first = words[0] if words else ""
    if first in _TYPE_WORDS:
        return _TYPE_WORDS[first]
    if first == "#define":
        return "define"
    if "(" in signature:
        return "function"
    if len(words) == 2 and first in ("class", "struct", "union"):
        return None
    return "variable"


def _member_kind(member: _Member, section: str) -> Optional[str]:
    """symbol_kind of a member; None for one that gets no record."""
    kind = _SUMMARY.get(section) if member.summary else _SECTIONS.get(section)
    signature = line(member.signature)
    if kind == _BY_DECLARATION:
        return _declared_kind(signature)
    if kind == _BY_TYPE_WORD:
        kind = _TYPE_WORDS.get(signature.split(" ", 1)[0])
    if kind is None:
        raise _unsupported(f"a member of unknown kind in section {section or 'without a heading'}")
    return kind


def records(html: str, generator: str) -> List[ApiRecord]:
    """The page's container record first, then one member record per member in page order.

    ``generator`` is the page's generator meta, "Doxygen <version>"."""
    version = generator[len("Doxygen "):]
    if version != MEASURED_VERSION:
        raise _unsupported(f"version {version} (measured: {MEASURED_VERSION})")
    page = _Page()
    page.feed(html)
    page.close()

    if page.title is None:
        raise NotSplit(NOT_API)  # the member and symbol indexes have no title block
    symbol, symbol_kind = _kind(line(page.title), any(not m.summary for m in page.members))
    if page.contents is None:
        raise _unsupported("no div.contents")
    if page.problem is not None:
        raise _unsupported(page.problem)
    check_symbol(symbol, _unsupported)
    if symbol_kind == "group" and any(not m.anchor.startswith("g") for m in page.members):
        raise _unsupported("a topic page member anchor without the g prefix")
    for section in page.sections:
        if line(section) not in _SECTIONS and line(section) != _DESCRIPTION:
            raise _unsupported(f"unknown section {line(section)}")

    lines: Dict[int, str] = {}  # id(Text) -> its line: a section heading is read once, not once per member

    def cached_line(text: Optional[Text]) -> str:
        if text is None:
            return ""
        if id(text) not in lines:
            lines[id(text)] = line(text)
        return lines[id(text)]

    # Namespaces a file page lists have pages of their own, which document their members.
    namespaces = {line(name) for label, name in page.names if cached_line(label) == _NAMESPACES}
    by_anchor: Dict[str, Optional[ApiRecord]] = {}  # None: a member that gets no record
    texts: Dict[str, List[str]] = {}  # anchor -> its record's lines
    members: List[ApiRecord] = []
    for member in page.members:
        if symbol_kind == "group" and not member.summary:
            # The section's title drops the namespace ("count()"); its summary row names the
            # member as the signature does: "algo::count", or a \relates one bare.
            if member.anchor not in page.row_names:
                raise _unsupported("a topic page member without a summary row")
            name = cached_line(page.row_names[member.anchor])
        else:
            name = line(member.name)
            if not member.summary and name.endswith("()"):
                name = name[:-2]  # "put()" names a function; "operator()()" keeps its own
        if not name:
            raise _unsupported("a member without a name")
        body = [ln for text, one_line in member.parts
                for ln in ([line(text)] if one_line else text.final()) if ln]
        kind = _member_kind(member, cached_line(member.section))  # None for a friend class
        if symbol_kind == "file" and member.summary and name.rpartition("::")[0] in namespaces:
            kind = None  # a namespace member Doxygen also anchors here: documented on the namespace page
        member_symbol = name if symbol_kind in ("file", "group") else f"{symbol}::{name}"
        if member.anchor in by_anchor:
            # Doxygen 1.9.8 gives overloads that differ only in a template constraint one anchor
            # (libstdc++'s std::optional): their one record holds them all, in page order.
            earlier = by_anchor[member.anchor]
            if kind is None or earlier is None or (earlier.symbol, earlier.symbol_kind) != (member_symbol, kind):
                raise _unsupported("duplicate member anchor")
            texts[member.anchor].extend(body)
            continue
        if kind is None:
            by_anchor[member.anchor] = None  # its name stays on the container
            continue
        check_symbol(member_symbol, _unsupported)
        record = ApiRecord(
            text="", symbol=member_symbol, kind="member", symbol_kind=kind, breadcrumb=[symbol, name],
            generator=GENERATOR, anchor=member.anchor, container=symbol)
        by_anchor[member.anchor] = record
        texts[member.anchor] = [member_symbol] + body
        members.append(record)
    for record in members:
        record.text = "\n".join(texts[record.anchor])

    if symbol_kind == "file" and not members:
        raise NotSplit("Doxygen file page that documents no member")
    names = declared((cached_line(label), line(name)) for label, name in page.names)
    labels = [line(page.labels)] if page.labels is not None else []
    container = ApiRecord(text="\n".join([f"{symbol} ({symbol_kind})"] + labels + page.contents.final() + names),
                          symbol=symbol, kind="container", symbol_kind=symbol_kind, breadcrumb=[symbol],
                          generator=GENERATOR)
    return [container] + members
