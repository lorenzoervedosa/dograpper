"""Sphinx autodoc adapter (ADR-0009): a page of Python objects as container and member records.

Sphinx writes no generator meta, so a page is recognised by the markup measured on
Sphinx 9.1 and 9.2 pages (alabaster and furo themes): inside the ``role="main"`` region,
one ``dl.py.<type>`` per documented object, its signatures in ``dt.sig-object`` (the
first one carries the id; overloads add more), its name in ``span.sig-prename`` and
``span.sig-name``, and its docstring in the ``dd``, which also holds a class's members.

The page's module is its main container record: it holds the page text outside the
objects (title, module docstring, prose) and the names of the top-level objects.
Classes and exceptions get container records, every other object a member record.
Permalink signs and ``[source]`` links are dropped. Any other markup raises NotSplit.
"""

from typing import List, Optional

from . import ApiRecord, NotSplit
from ._html import Regions, Text

GENERATOR = "sphinx"
# Start of every object signature; __init__ recognises a Sphinx page by it.
SIGNATURE = '<dt class="sig sig-object py"'

# Second class of dl.py.<type> -> (record kind, label on the container record). symbol_kind is the type.
_TYPES = {
    "class": ("container", "Classes"),
    "exception": ("container", "Exceptions"),
    "function": ("member", "Functions"),
    "method": ("member", "Methods"),
    "property": ("member", "Properties"),
    "attribute": ("member", "Attributes"),
    "data": ("member", "Data"),
}
# Types that live in a module, so the first of them names the page's module.
_MODULE_LEVEL = ("class", "exception", "function", "data")
# A nested object's name repeats its ancestors', so a chain of nested objects would make the
# output quadratic in the page size; a longer qualified name than this is not a real one.
MAX_SYMBOL = 1000


class _Object:
    def __init__(self, objtype: str, depth: int, parent: Optional["_Object"]):
        self.objtype = objtype
        self.depth = depth  # stack size with this object's dl open: its own dt and dd sit one deeper
        self.parent = parent
        self.anchor: Optional[str] = None
        self.prename: Optional[Text] = None
        self.name: Optional[Text] = None
        self.signatures: List[Text] = []
        self.doc: Optional[Text] = None
        self.children: List["_Object"] = []
        self.symbol = ""


class _Page(Regions):
    """One pass over the page (linear, see _html.Regions)."""

    def __init__(self):
        super().__init__()
        self.main: Optional[Text] = None
        self._in_main = False
        self._objects: List[_Object] = []  # open dl.py, innermost last
        self._tap: Optional[Text] = None   # name span being read; it also feeds the signature line
        self.objects: List[_Object] = []   # every object, in page order
        self.unknown: Optional[str] = None

    def _set(self, name, value, closers) -> None:
        previous = getattr(self, name)
        setattr(self, name, value)
        closers.append(lambda: setattr(self, name, previous))

    def start(self, tag, attr, classes, closers):
        if attr.get("role") == "main" and self.main is None:
            self.main = self.region(closers)
            self._set("_in_main", True, closers)
            return
        if not self._in_main:
            return
        obj = self._objects[-1] if self._objects else None
        depth = len(self._stack)
        if (tag == "a" and "headerlink" in classes) or (tag == "span" and "viewcode-link" in classes):
            self.skip(closers)
        elif tag == "dl" and classes[:1] == ["py"]:
            objtype = classes[1] if len(classes) > 1 else ""
            if objtype not in _TYPES:
                self.unknown = self.unknown or objtype
            child = _Object(objtype, depth, obj)
            if obj is not None:
                obj.children.append(child)
            self.objects.append(child)
            self._objects.append(child)
            closers.append(self._objects.pop)
        elif obj is None:
            return
        elif tag == "dt" and depth == obj.depth + 1 and "sig-object" in classes:
            obj.signatures.append(self.region(closers))
            if obj.anchor is None and attr.get("id"):
                obj.anchor = attr["id"]
        elif tag == "dd" and depth == obj.depth + 1 and obj.doc is None:
            obj.doc = self.region(closers)
        elif (tag == "span" and len(obj.signatures) == 1 and depth > obj.depth + 1
              and self._tap is None and ("sig-prename" in classes or "sig-name" in classes)):
            field = "prename" if "sig-prename" in classes else "name"
            if getattr(obj, field) is None:
                setattr(obj, field, Text())
                self._set("_tap", getattr(obj, field), closers)

    def handle_data(self, data):
        super().handle_data(data)
        if self._tap is not None and not self._raw:
            self._tap.add(data)


def _unsupported(problem: str) -> NotSplit:
    return NotSplit(f"unsupported Sphinx markup: {problem}")


def _line(text: Optional[Text]) -> str:
    return " ".join(text.final()) if text else ""


def _declared(children: List[_Object], short) -> List[str]:
    """One "Label: a, b" line per object type, in order of first appearance."""
    declared = {}  # label -> {name: None}, an ordered set
    for child in children:
        declared.setdefault(_TYPES[child.objtype][1], {})[short(child)] = None
    return [f"{label}: {', '.join(names)}" for label, names in declared.items()]


def records(html: str) -> List[ApiRecord]:
    """The page's module record first, then one record per object in page order."""
    page = _Page()
    page.feed(html)
    page.close()

    if page.main is None:
        raise _unsupported('no role="main" element')
    if not page.objects:
        raise _unsupported("no Python object in the main region")
    if page.unknown is not None:
        raise _unsupported(f"unknown object type py {page.unknown}")
    anchors = set()
    for obj in page.objects:
        if not obj.signatures:
            raise _unsupported("a dl.py without a dt.sig-object")
        if not obj.anchor:
            raise _unsupported("an object without an id (:no-index:)")
        if obj.anchor in anchors:
            raise _unsupported("duplicate object id")
        anchors.add(obj.anchor)
        name = _line(obj.name)
        if not name:
            raise _unsupported("a signature without a sig-name")
        if obj.parent is not None:
            obj.symbol = f"{obj.parent.symbol}.{name}"
        else:
            obj.symbol = (_line(obj.prename) + name) if obj.prename else obj.anchor
        if len(obj.symbol) > MAX_SYMBOL:
            raise _unsupported(f"a qualified name over {MAX_SYMBOL} characters")

    top = [obj for obj in page.objects if obj.parent is None]
    module = next((obj.symbol.rpartition(".")[0] for obj in top if obj.objtype in _MODULE_LEVEL), "")
    if not module:
        raise _unsupported("no module-level object names the page's module")

    def relative(obj):
        return obj.symbol[len(module) + 1:] if obj.symbol.startswith(module + ".") else obj.symbol

    lines = [f"{module} (module)"] + page.main.final() + _declared(top, relative)
    result = [ApiRecord(text="\n".join(lines), symbol=module, kind="container", symbol_kind="module",
                        breadcrumb=[module], generator=GENERATOR)]
    for obj in page.objects:
        kind = _TYPES[obj.objtype][0]
        signatures = [_line(sig) for sig in obj.signatures]
        doc = obj.doc.final() if obj.doc else []
        if kind == "container":
            text = [f"{obj.symbol} ({obj.objtype})"] + signatures + doc + _declared(
                obj.children, lambda child: _line(child.name))
            result.append(ApiRecord(text="\n".join(text), symbol=obj.symbol, kind=kind,
                                    symbol_kind=obj.objtype, breadcrumb=[obj.symbol],
                                    generator=GENERATOR, anchor=obj.anchor))
        else:
            container = obj.parent.symbol if obj.parent else (obj.symbol.rpartition(".")[0] or module)
            member = obj.symbol[len(container) + 1:] if obj.symbol.startswith(container + ".") else obj.symbol
            result.append(ApiRecord(text="\n".join([obj.symbol] + signatures + doc), symbol=obj.symbol,
                                    kind=kind, symbol_kind=obj.objtype, breadcrumb=[container, member],
                                    generator=GENERATOR, anchor=obj.anchor, container=container))
    return result
