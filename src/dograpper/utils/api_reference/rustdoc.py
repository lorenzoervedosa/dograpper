"""rustdoc adapter (ADR-0009): a rustdoc page as container and member records.

Reads the markup measured on rustdoc 1.96 pages (generator ``rustdoc``, ``data-rustdoc-version``
1.96.x): the page kind in ``body.rustdoc.<kind>``, and inside ``section#main-content`` the
module's qualified name in ``div.rustdoc-breadcrumbs``, the symbol's name in the ``h1`` span
and one ``h2.section-header`` per section. A struct, enum, union, trait or type alias page is a
container record with one member record per field (``span.structfield``), variant, member of
an inherent impl block and trait member (``section[id]``); a member's doc comment is the
``div.docblock`` that follows its header. Trait implementations, auto trait implementations
and implementors keep only their ``impl`` headers on the container record; blanket
implementations are dropped. A module page is a container record naming its symbols; a
function, constant, static or macro page is one member record. The descriptions in a module
page's lists (``dl.item-table``), permalink signs, notable-trait marks and ``Source`` links are
dropped. Any other markup raises NotSplit.
"""

import re
from typing import List, Optional

from ..generator import SCAN_CHARS
from . import ApiRecord, NotSplit, check_anchor, check_symbol, declared
from ._html import Regions, Text, line

GENERATOR = "rustdoc"
# Accepted data-rustdoc-version prefixes: the stable 1.96 line and the one measured nightly build.
MEASURED_VERSIONS = ("1.96.", "1.102.0-nightly (6905905bb ")
MEASURED_LABEL = "1.96.x, 1.102.0-nightly 6905905bb"  # for the NotSplit reason
# In <meta name="rustdoc-vars">, next to the generator meta; bounded, so linear.
_VERSION = re.compile(r'\bdata-rustdoc-version="([^"]{0,100})"')

# Page kind (second class of body.rustdoc) -> (record kind, symbol_kind).
_PAGES = {
    "mod": ("container", "module"),
    "struct": ("container", "struct"),
    "enum": ("container", "enum"),
    "union": ("container", "union"),
    "trait": ("container", "trait"),
    "type": ("container", "type_alias"),
    "fn": ("member", "function"),
    "constant": ("member", "constant"),
    "static": ("member", "static"),
    "macro": ("member", "macro"),
}
# Id prefix of a member header -> (symbol_kind, label on the container record).
_MEMBERS = {
    "structfield": ("field", "Fields"),
    "variant": ("variant", "Variants"),
    "associatedtype": ("associated_type", "Associated types"),
    "associatedconstant": ("associated_constant", "Associated constants"),
    "tymethod": ("method", "Required methods"),
    "method": ("method", "Methods"),
}
# How each section (id of its h2.section-header) is read.
_MEMBER_SECTION, _IMPLS, _NAMES, _TEXT, _DROPPED = "member", "impls", "names", "text", "dropped"
_SECTIONS = {
    **dict.fromkeys(("fields", "variants", "implementations", "required-associated-types",
                     "provided-associated-types", "required-associated-consts",
                     "provided-associated-consts", "required-methods", "provided-methods"),
                    _MEMBER_SECTION),
    **dict.fromkeys(("trait-implementations", "synthetic-implementations", "foreign-impls",
                     "implementors"), _IMPLS),
    **dict.fromkeys(("reexports", "modules", "macros", "structs", "enums", "unions", "constants",
                     "statics", "traits", "functions", "types"), _NAMES),
    **dict.fromkeys(("aliased-type", "dyn-compatibility"), _TEXT),
    "blanket-implementations": _DROPPED,
}
_NOT_SYMBOL_PAGES = ("sys", "src")  # all.html, help.html, settings.html; source pages


class _Member:
    def __init__(self, anchor: str, impl: Optional[Text]):
        self.anchor = anchor
        self.impl = impl  # the inherent impl block's header, if any
        self.parts: List[Text] = []


class _Page(Regions):
    """One pass over the page (linear, see _html.Regions)."""

    def __init__(self):
        super().__init__()
        self.body_classes: Optional[List[str]] = None  # classes of body.rustdoc after "rustdoc"
        self.main: Optional[Text] = None
        self.crumbs: Optional[Text] = None
        self.name: Optional[Text] = None
        self.members: List[_Member] = []
        self.names = []                     # (label, Text) of the symbols a module page lists
        self.impls: List[Text] = []         # impl headers kept on the container, with their labels
        self.unknown: Optional[str] = None  # first unknown section id
        self._in_main = False
        self._in_h1 = False
        self._section: Optional[str] = None  # how the current section is read
        self._label: Optional[Text] = None   # h2 of the module page's current list
        self._impl: Optional[Text] = None    # current inherent impl block's header
        self._member: Optional[_Member] = None  # member whose doc may follow

    def start(self, tag, attr, classes, closers):
        if tag == "body" and classes[:1] == ["rustdoc"] and self.body_classes is None:
            self.body_classes = classes[1:]
            return
        if tag == "section" and attr.get("id") == "main-content" and self.main is None:
            self.main = self.region(closers)
            self.set_until_end("_in_main", True, closers)
            return
        if not self._in_main:
            return
        if tag == "h2" and "section-header" in classes:
            self._section_start(attr.get("id") or "", closers)
        elif (self._section == _DROPPED
              or (tag == "a" and ("src" in classes or "anchor" in classes or "doc-anchor" in classes))
              or (tag in ("a", "span") and "tooltip" in classes)  # notable-trait mark: <a> in 1.96, <span> in the nightly
              or tag == "button" or (tag == "span" and "emoji" in classes)
              or (tag == "summary" and "hideme" in classes)
              or (tag == "details" and "non-exhaustive" in classes)):
            self.skip(closers)
        elif tag == "div" and "rustdoc-breadcrumbs" in classes and self.crumbs is None:
            self.crumbs = self.region(closers)
        elif tag == "h1" and self.name is None:
            self.region(closers)  # the page kind ("Struct"): dropped
            self.set_until_end("_in_h1", True, closers)
        elif tag == "span" and self._in_h1 and self.name is None:
            self.name = self.region(closers)
        elif self._section == _IMPLS:
            if tag == "section" and "impl" in classes:
                self.impls.append(self.region(closers))
            elif (tag == "div" and ("impl-items" in classes or "docblock" in classes)) or (
                    tag == "span" and "item-info" in classes):
                self.skip(closers)
        elif self._section == _NAMES:
            if tag == "dt":
                self.names.append((self._label, self.region(closers)))
            elif tag in ("dd", "sup") or (tag == "span" and "stab" in classes):
                self.skip(closers)  # a description; the unsafe and deprecation badges
        elif self._section == _MEMBER_SECTION:
            self._member_start(tag, attr.get("id") or "", classes, closers)

    def _section_start(self, section_id, closers):
        self._member = self._impl = self._label = None
        self._section = _SECTIONS.get(section_id)
        if self._section is None:
            self.unknown = self.unknown if self.unknown is not None else section_id
        elif self._section == _IMPLS:
            self.impls.append(self.region(closers))  # its label, e.g. "Trait Implementations"
        elif self._section == _NAMES:
            self._label = self.region(closers)
        elif self._section != _TEXT:
            self.skip(closers)

    def _member_start(self, tag, anchor, classes, closers):
        prefix = anchor.split(".", 1)[0]
        if tag == "section" and "impl" in classes:
            self._member = None
            self._impl = self.region(closers)  # an inherent impl block's header
        elif ("." in anchor and prefix in _MEMBERS
              and ((tag == "span" and "structfield" in classes)
                   or (tag == "section" and prefix != "structfield"))):
            self._member = _Member(anchor, self._impl)
            self.members.append(self._member)
            self._member.parts.append(self.region(closers))
        elif (self._member is not None and self._sinks[-1] is self.main
              and ((tag == "div" and ("docblock" in classes or "sub-variant" in classes))
                   or (tag == "span" and "item-info" in classes))):
            self._member.parts.append(self.region(closers))  # its doc comment, notes, variant fields


def _unsupported(problem: str) -> NotSplit:
    return NotSplit(f"unsupported rustdoc markup: {problem}")


def records(html: str) -> List[ApiRecord]:
    """The page's container record first, then one member record per member in page order;
    a function, constant, static or macro page is one member record."""
    version = _VERSION.search(html, 0, SCAN_CHARS)
    if not version or not version.group(1).startswith(MEASURED_VERSIONS):
        raise _unsupported(f"version {version.group(1) if version else 'missing'} "
                           f"(measured: {MEASURED_LABEL})")
    page = _Page()
    page.feed(html)
    page.close()

    if page.body_classes is None:
        raise _unsupported("no body.rustdoc")
    if any(kind in _NOT_SYMBOL_PAGES for kind in page.body_classes):
        raise NotSplit("rustdoc list, help or source page")
    page_kind = page.body_classes[0] if page.body_classes else ""
    if page_kind not in _PAGES:
        raise _unsupported(f"page kind {page_kind or 'missing'}")
    if page.main is None:
        raise _unsupported("no section#main-content")
    if page.unknown is not None:
        raise _unsupported(f"unknown section {page.unknown or 'without an id'}")
    name = line(page.name)
    if not name:
        raise _unsupported("no name in the h1")
    crate = page_kind == "mod" and "crate" in page.body_classes
    module = line(page.crumbs)
    if not module and not crate:
        raise _unsupported("no div.rustdoc-breadcrumbs")
    qualified = f"{module}::{name}" if module else name
    check_symbol(qualified, _unsupported)
    kind, symbol_kind = _PAGES[page_kind]
    if crate:
        symbol_kind = "crate"

    if kind == "member":
        return [ApiRecord(text="\n".join([qualified] + page.main.final()), symbol=qualified, kind=kind,
                          symbol_kind=symbol_kind, breadcrumb=[module, name], generator=GENERATOR,
                          container=module)]

    members: List[ApiRecord] = []
    labels = {}  # id(h2) -> its line, once per list rather than once per name
    names = []
    for label, item in page.names:
        if id(label) not in labels:
            labels[id(label)] = line(label)
        names.append((labels[id(label)], line(item)))
    anchors = set()
    for m in page.members:
        check_anchor(m.anchor, anchors, _unsupported, "duplicate member id")
        prefix, _, member_name = m.anchor.partition(".")
        member_name = member_name.rsplit("-", 1)[0]  # rustdoc numbers a repeated id: method.get-1
        member_kind, label = _MEMBERS[prefix]
        names.append((label, member_name))
        symbol = f"{qualified}::{member_name}"
        check_symbol(symbol, _unsupported)
        impl = line(m.impl)
        check_symbol(impl, _unsupported, "an impl header")  # repeated on each of its members
        text = [symbol] + ([impl] if impl else []) + [ln for part in m.parts for ln in part.final()]
        members.append(ApiRecord(
            text="\n".join(text), symbol=symbol, kind="member", symbol_kind=member_kind,
            breadcrumb=[qualified, member_name], generator=GENERATOR, anchor=m.anchor,
            container=qualified))

    lines = [f"{qualified} ({symbol_kind})"] + page.main.final() + declared(names) + [
        ln for impl in page.impls for ln in impl.final()]
    container = ApiRecord(text="\n".join(lines), symbol=qualified, kind="container",
                          symbol_kind=symbol_kind, breadcrumb=[qualified], generator=GENERATOR)
    return [container] + members
