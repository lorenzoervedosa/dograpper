"""`pack --api-records` on TypeDoc pages (ADR-0009, #75 phase 4).

The fixture is TypeDoc 0.28.20 output, source links on, for the sources in
tests/fixtures/typedoc/src (regenerate with tests/fixtures/typedoc/regenerate.sh).
The Javadoc and Sphinx adapters are tested in tests/test_api_reference.py.
"""

import json
import os
import re
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.commands.serve import build_tools
from dograpper.lib.pack_reader import load_chunks
from dograpper.lib.retrieval import build_index
from dograpper.utils.api_reference import NotSplit, split_api_pages, split_page
from tests.linearity import assert_linear

TYPEDOC = Path(__file__).parent / "fixtures" / "typedoc" / "html"


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    # No stray .dograpper.json / manifest / .docsignore from the caller's directory.
    monkeypatch.chdir(tmp_path)


def _pages():
    return sorted(str(p) for p in TYPEDOC.rglob("*.html"))


def _page(rel):
    return (TYPEDOC / rel).read_text(encoding="utf-8")


def _records(rel):
    return {r.symbol: r for r in split_page(_page(rel))}


def test_typedoc_symbol_pages_are_split_and_project_pages_kept_whole():
    split = split_api_pages(_pages(), str(TYPEDOC))
    assert sorted(split.records) == [
        "classes/shapes.Box.html", "classes/shapes.BoxFullError.html", "classes/shapes.Crate.html",
        "classes/tools.Registry.html", "enums/shapes.Lid.html", "functions/shapes.Boxes.empty.html",
        "functions/shapes.apply.html", "functions/shapes.scale.html", "functions/tools.first.html",
        "interfaces/shapes.Shape.html", "modules/shapes.Boxes.html", "modules/shapes.html",
        "modules/tools.html", "types/shapes.Point.html", "variables/shapes.Boxes.made.html",
        "variables/shapes.DEFAULT_NAME.html",
    ]
    assert split.kept_whole == [
        ("hierarchy.html", "TypeDoc page, not an API page"),
        ("index.html", "TypeDoc page, not an API page"),
        ("modules.html", "TypeDoc page, not an API page"),
    ]


def test_typedoc_records_keep_page_order_with_the_page_symbol_first():
    assert [r.symbol for r in split_page(_page("classes/shapes.Box.html"))] == [
        "shapes.Box", "shapes.Box.constructor", "shapes.Box.name", "shapes.Box.sides",
        "shapes.Box.CAPACITY", "shapes.Box.size", "shapes.Box.add", "shapes.Box.area",
        "shapes.Box.map", "shapes.Box.put", "shapes.Box.shake", "shapes.Box.of",
    ]


# ---------------------------------------------------------------------------
# Container records
# ---------------------------------------------------------------------------

def test_typedoc_class_container_record():
    box = split_page(_page("classes/shapes.Box.html"))[0]
    assert (box.symbol, box.kind, box.symbol_kind) == ("shapes.Box", "container", "class")
    assert (box.anchor, box.container, box.generator, box.breadcrumb) == ("", "", "typedoc", ["shapes.Box"])
    assert box.text == "\n".join([
        "shapes.Box (class)",
        "Class Box<T>",
        "A generic box that stores items in insertion order.",
        "Type Parameters",
        "T",
        "the type of the stored items",
        "Hierarchy (View Summary)",
        "Box",
        "Crate",
        "Implements",
        "Shape",
        "Constructors: constructor",
        "Properties: name, sides, CAPACITY",
        "Accessors: size",
        "Methods: add, area, map, put, shake, of",
    ])
    # A member's doc comment lives on its member record only; the index is dropped.
    assert "Store one item." not in box.text and "Index" not in box.text


def test_typedoc_inherited_members_are_listed_by_base_on_the_container():
    crate = _records("classes/shapes.Crate.html")
    assert list(crate) == ["shapes.Crate", "shapes.Crate.constructor", "shapes.Crate.seal"]
    assert crate["shapes.Crate"].text.split("\n")[:3] == ["shapes.Crate (class)", "Abstract", "Class Crate<T>"]
    assert crate["shapes.Crate"].text.split("\n")[-3:] == [
        "Constructors: constructor",
        "Methods: seal",
        "Inherited from Box: name, sides, CAPACITY, size, add, area, map, put, shake, of",
    ]
    # The constructor is the subclass's own; its aside names the base it inherits from.
    assert crate["shapes.Crate.constructor"].text.split("\n")[-1] == "Inherited from Box.constructor"
    # "Defined in" source locations are dropped, from every record.
    assert not any("Defined in" in text for text in split_api_pages(_pages(), str(TYPEDOC)).texts.values())


def test_typedoc_module_container_record():
    module = split_page(_page("modules/shapes.html"))
    assert len(module) == 1
    assert (module[0].symbol, module[0].kind, module[0].symbol_kind) == ("shapes", "container", "module")
    assert module[0].text == "\n".join([
        "shapes (module)",
        "Module shapes",
        "Shapes and the boxes that store them.",
        "Example",
        'const box = Box.of("apple");',
        'box.put("pear");',
        "Namespaces: Boxes",
        "Enumerations: Lid",
        "Classes: Box, BoxFullError, Crate",
        "Interfaces: Shape",
        "Type Aliases: Point",
        "Variables: DEFAULT_NAME",
        "Functions: apply, scale",
    ])


def test_typedoc_namespace_and_enum_containers():
    boxes = split_page(_page("modules/shapes.Boxes.html"))[0]
    assert (boxes.symbol, boxes.symbol_kind) == ("shapes.Boxes", "namespace")
    assert boxes.text == "\n".join([
        "shapes.Boxes (namespace)", "Namespace Boxes", "Helpers for boxes.",
        "Variables: made", "Functions: empty"])
    lid = _records("enums/shapes.Lid.html")
    assert lid["shapes.Lid"].symbol_kind == "enum"
    assert lid["shapes.Lid"].text.split("\n")[-1] == "Enumeration Members: Open, Snap"
    snap = lid["shapes.Lid.Snap"]
    assert (snap.kind, snap.symbol_kind, snap.anchor, snap.container) == (
        "member", "enum_member", "snap", "shapes.Lid")
    assert snap.text == "shapes.Lid.Snap\nSnap: 2\nA lid that snaps shut."


def test_typedoc_interface_members():
    shape = _records("interfaces/shapes.Shape.html")
    assert shape["shapes.Shape"].symbol_kind == "interface"
    assert shape["shapes.Shape.area"].text == "\n".join([
        "shapes.Shape.area", "area(): number", "Surface of the shape.", "Returns number",
        "the area in square units"])
    assert shape["shapes.Shape.sides"].text == "shapes.Shape.sides\nReadonly\nsides: number\nNumber of sides."


def test_typedoc_type_alias_with_members_is_a_container():
    point = _records("types/shapes.Point.html")
    assert list(point) == ["shapes.Point", "shapes.Point.x", "shapes.Point.y"]
    assert (point["shapes.Point"].kind, point["shapes.Point"].symbol_kind) == ("container", "type_alias")
    assert point["shapes.Point"].text == "\n".join([
        "shapes.Point (type_alias)", "Type Alias Point", "A point on the plane.",
        "type Point = {", "x: number;", "y?: number;", "}", "Properties: x, y"])
    assert point["shapes.Point.y"].text == "shapes.Point.y\nOptional\ny?: number"


# ---------------------------------------------------------------------------
# Member records
# ---------------------------------------------------------------------------

def test_typedoc_member_record_of_a_generic_method():
    map_ = _records("classes/shapes.Box.html")["shapes.Box.map"]
    assert (map_.kind, map_.symbol_kind, map_.anchor, map_.container) == (
        "member", "method", "map", "shapes.Box")
    assert map_.breadcrumb == ["shapes.Box", "map"]
    assert map_.text == "\n".join([
        "shapes.Box.map",
        "map<U extends object>(func: (item: T) => U): Box<U>",
        "A box of func applied to every item.",
        "Type Parameters",
        "U extends object",
        "the type of the mapped items",
        "Parameters",
        "func: (item: T) => U",
        "Returns Box<U>",
    ])


@pytest.mark.parametrize("symbol, symbol_kind, lines", [
    ("shapes.Box.constructor", "constructor", ["new Box<T>(items?: T[]): Box<T>"]),
    ("shapes.Box.name", "property", ["name: string = DEFAULT_NAME"]),
    ("shapes.Box.CAPACITY", "property", ["Static Readonly", "CAPACITY: 16"]),
    ("shapes.Box.size", "accessor", ["get size(): number"]),
    ("shapes.Box.of", "method", ["Static", "of<U>(...items: U[]): Box<U>"]),
])
def test_typedoc_member_kinds_flags_and_signatures(symbol, symbol_kind, lines):
    rec = _records("classes/shapes.Box.html")[symbol]
    assert (rec.kind, rec.symbol_kind, rec.container) == ("member", symbol_kind, "shapes.Box")
    assert rec.text.split("\n")[:1 + len(lines)] == [symbol] + lines


def test_typedoc_member_record_holds_the_doc_comment_and_notes():
    recs = _records("classes/shapes.Box.html")
    assert recs["shapes.Box.put"].text == "\n".join([
        "shapes.Box.put",
        "put(item: T): void",
        "Store one item.",
        "Parameters",
        "item: T",
        "the item to store",
        "Returns void",
        "Throws",
        "BoxFullError when the box already holds Box.CAPACITY items",
    ])
    assert recs["shapes.Box.add"].text.split("\n")[-2:] == ["Deprecated", "Use Box.put instead."]
    assert recs["shapes.Box.area"].text.split("\n")[-1] == "Implementation of Shape.area"
    # An undocumented member keeps its signature.
    assert recs["shapes.Box.shake"].text.split("\n")[:2] == ["shapes.Box.shake", "shake(times: number): void"]


def test_typedoc_function_page_is_one_member_record_with_every_overload():
    (scale,) = split_page(_page("functions/shapes.scale.html"))
    assert (scale.symbol, scale.kind, scale.symbol_kind) == ("shapes.scale", "member", "function")
    assert (scale.anchor, scale.container, scale.breadcrumb) == ("", "shapes", ["shapes", "scale"])
    assert scale.text == "\n".join([
        "shapes.scale",
        "scale(value: number, factor: number): number",
        "Multiply value by factor, keeping its type.",
        "Parameters", "value: number", "factor: number", "Returns number",
        "scale(value: bigint, factor: bigint): bigint",
        "Multiply two bigints.",
        "Parameters", "value: bigint", "factor: bigint", "Returns bigint",
    ])
    (empty,) = split_page(_page("functions/shapes.Boxes.empty.html"))
    assert (empty.symbol, empty.container, empty.breadcrumb) == (
        "shapes.Boxes.empty", "shapes.Boxes", ["shapes.Boxes", "empty"])
    assert empty.text.split("\n")[1] == "empty<T>(): Box<T>"


def test_typedoc_variable_page_is_one_member_record():
    (name,) = split_page(_page("variables/shapes.DEFAULT_NAME.html"))
    assert (name.kind, name.symbol_kind, name.container) == ("member", "variable", "shapes")
    assert name.text == 'shapes.DEFAULT_NAME\nConst\nDEFAULT_NAME: "shape"\nName given to a shape without one.'


def test_typedoc_single_entry_point_pages_have_no_module_in_the_path():
    # With one entry point the breadcrumb starts at the symbol (as in the query-core acceptance corpus).
    module = '<li><a href="../modules/shapes.html">shapes</a></li>'
    (scale,) = split_page(_page("functions/shapes.scale.html").replace(module, "", 1))
    assert (scale.symbol, scale.container, scale.breadcrumb) == ("scale", "", ["scale"])
    box = {r.symbol: r for r in split_page(_page("classes/shapes.Box.html").replace(module, "", 1))}
    assert box["Box"].text.split("\n")[0] == "Box (class)"
    assert (box["Box.put"].container, box["Box.put"].breadcrumb) == ("Box", ["Box", "put"])


def test_typedoc_generic_class_from_another_module():
    registry = _records("classes/tools.Registry.html")
    assert registry["tools.Registry"].text.split("\n")[1] == "Class Registry<K, V>"
    assert registry["tools.Registry.get"].text.split("\n")[1] == "get(key: K, fallback?: V): V | undefined"
    assert registry["tools.Registry.register"].text.split("\n")[1] == "register(key: K): (value: V) => V"


def test_typedoc_record_url_carries_the_member_anchor():
    recs = _records("classes/shapes.Box.html")
    page = "https://example.com/docs/classes/shapes.Box.html"
    assert recs["shapes.Box"].url(page) == page
    assert recs["shapes.Box.CAPACITY"].url(page) == page + "#capacity"


# ---------------------------------------------------------------------------
# Other markup
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("rel, old, new, problem", [
    ("classes/shapes.Box.html", '<div class="col-content">', '<div class="col-main">', "no div.col-content"),
    ("classes/shapes.Box.html", "<h1>Class Box", "<h1>Klasse Box", "unknown page kind in 'Klasse Box<T>'"),
    ("classes/shapes.Box.html", 'class="tsd-anchor-link" id="shake"', 'class="tsd-anchor-link" id="put"',
     "duplicate member anchor"),
    ("classes/shapes.Box.html", 'class="tsd-anchor-link" id="shake"', 'class="tsd-anchor-link"',
     "a section.tsd-member without an h3 id"),
    ("classes/shapes.Box.html", 'class="tsd-kind-property">CAPACITY', 'class="tsd-kind-widget">CAPACITY',
     "unknown member kind tsd-kind-widget"),
    ("classes/shapes.Box.html", '<details class="tsd-panel-group tsd-member-group tsd-accordion" open>',
     '<details class="tsd-panel-group tsd-accordion" open>', "a member outside a member group"),
    ("classes/shapes.Box.html", '<section class="tsd-panel tsd-member">\n<h3 class="tsd-anchor-link" id="shake">',
     '<section class="tsd-panel tsd-member"><section class="tsd-panel tsd-member">'
     '<h3 class="tsd-anchor-link" id="shake">', "a member inside a member"),
    ("functions/shapes.scale.html", "<h1>Function scale</h1></div>", "<h1>Function scale</h1></div>"
     '<details class="tsd-member-group"><summary><h2>Variables</h2></summary>'
     '<dl><dt class="tsd-member-summary">x</dt></dl></details>', "a function page that lists members"),
    ("functions/shapes.scale.html", "<h1>Function scale</h1></div>", "<h1>Function scale</h1></div>"
     '<details class="tsd-member-group"><summary><h2>Properties</h2></summary>'
     '<section class="tsd-panel tsd-member"><h3 id="x">x</h3><div class="tsd-signature">'
     '<span class="tsd-kind-property">x</span></div></section></details>', "a function page that lists members"),
    ("classes/shapes.Box.html", "<h1>Class Box", "<h1>Class Boxer", "unknown page kind in 'Class Boxer<T>'"),
    # TypeDoc 0.25-0.27: the breadcrumb starts at the project and marks no current page.
    ("functions/shapes.scale.html", '<a href="" aria-current="page">scale</a>', '<a href="shapes.scale.html">scale</a>',
     "a breadcrumb without the current page"),
])
def test_a_typedoc_page_with_other_markup_is_not_split(rel, old, new, problem):
    page = _page(rel)
    assert old in page
    with pytest.raises(NotSplit, match=f"unsupported TypeDoc markup: {re.escape(problem)}"):
        split_page(page.replace(old, new, 1))


def test_a_typedoc_inherited_member_without_its_base_is_not_split():
    page = _page("classes/shapes.Crate.html")
    with pytest.raises(NotSplit, match="unsupported TypeDoc markup: an inherited member without its base"):
        split_page(page.replace("Inherited from ", "Copied from "))


NEST, MEMBERS = 3000, 4000  # sized so a stack copy / a list scan per member trips the 7x bound


def test_typedoc_parsing_stays_linear_on_hostile_markup():
    head = ('<div class="col-content"><div class="tsd-page-title"><ul class="tsd-breadcrumb">'
            '<li>m</li><li><a aria-current="page">C</a></li></ul><h1>Class C</h1></div>')

    def member(i):
        return (f'<section class="tsd-panel tsd-member"><h3 id="f{i}"><span>f{i}</span></h3>'
                f'<div class="tsd-signature"><span class="tsd-kind-property">f{i}</span>: int</div></section>')
    # Deep unclosed nesting with stray end tags, and (separately, so each stays cheap) many members.
    def hostile(deep, members):
        return (head + "<p><b>" * deep + "</i>" * deep + "</p>" * deep
                + '<details class="tsd-member-group"><summary><h2>Properties</h2></summary>'
                + "".join(member(i) for i in range(members)))

    def run(page):
        assert len(split_page(page)) == page.count('class="tsd-panel tsd-member"') + 1
    assert_linear(lambda n: hostile(n, 0), run, n=NEST)
    assert_linear(lambda n: hostile(0, n), run, n=MEMBERS)
    with pytest.raises(NotSplit):
        split_page(head + '<details class="tsd-member-group"><summary><h2>P</h2></summary>'
                   + '<section class="tsd-panel tsd-member"><h3 id="x">' * 40000)


def test_typedoc_qualified_names_are_bounded():
    # Every member symbol repeats the page's name, so a huge name times many members would make
    # the output quadratic in the page size.
    def page(n):
        return ('<div class="col-content"><div class="tsd-page-title"><ul class="tsd-breadcrumb">'
                + "".join(f"<li>m{i}</li>" for i in range(n))
                + '<li><a aria-current="page">m</a></li></ul><h1>Class m</h1></div>')

    with pytest.raises(NotSplit, match="unsupported TypeDoc markup: a qualified name over 1000 characters"):
        split_page(page(2000))
    # A member's name counts too.
    put = 'class="tsd-anchor-link" id="put"><span>put</span>'
    with pytest.raises(NotSplit, match="a qualified name over 1000 characters"):
        split_page(_page("classes/shapes.Box.html").replace(put, put.replace(">put<", ">" + "p" * 1000 + "<"), 1))

    def run(html):
        with pytest.raises(NotSplit):
            split_page(html)
    assert_linear(page, run, 2000)


# ---------------------------------------------------------------------------
# pack --api-records
# ---------------------------------------------------------------------------

# Second copy of _pack/_jsonl in tests/test_api_reference.py.
def _pack(*args):
    return CliRunner().invoke(cli, ["pack", *args], catch_exceptions=False)


def _jsonl(out):
    records = []
    for name in sorted(os.listdir(out)):
        if name.endswith(".jsonl"):
            with open(os.path.join(out, name), encoding="utf-8") as f:
                records.extend(json.loads(line) for line in f if line.strip())
    return records


def _typedoc_pack(tmp_path):
    src, out = tmp_path / "docs", tmp_path / "out"
    shutil.copytree(TYPEDOC, src)
    result = _pack(str(src), "-o", str(out), "--format", "jsonl", "--api-records")
    assert result.exit_code == 0, result.output
    return result, out


def test_pack_writes_typedoc_records(tmp_path):
    result, out = _typedoc_pack(tmp_path)
    by_id = {r["id"]: r for r in _jsonl(out)}
    box = by_id["01_classes/shapes.Box.html"]
    assert {k: box[k] for k in ("symbol", "kind", "symbol_kind", "generator", "breadcrumb")} == {
        "symbol": "shapes.Box", "kind": "container", "symbol_kind": "class",
        "generator": "typedoc", "breadcrumb": ["shapes.Box"]}
    put = by_id["01_classes/shapes.Box.html#put"]
    assert (put["kind"], put["symbol_kind"], put["container"], put["breadcrumb"]) == (
        "member", "method", "shapes.Box", ["shapes.Box", "put"])
    assert put["words"] == len(put["content"].split())
    # A function page is one member record under the page's own id.
    scale = by_id["01_functions/shapes.scale.html"]
    assert (scale["kind"], scale["symbol"], scale["container"]) == ("member", "shapes.scale", "shapes")
    assert "symbol" not in by_id["01_index.html"]
    assert "index.html: TypeDoc page, not an API page" in result.stderr
    assert "API records:     16 pages split into 41 records (10 container, 31 member), 3 pages kept whole" \
        in result.output


def test_serve_finds_the_typedoc_member_record(tmp_path):
    _, out = _typedoc_pack(tmp_path)
    chunks = load_chunks(str(out))
    tools = {t.name: t for t in build_tools(chunks, build_index(chunks), {}, {}, "docs_chunk_")}
    hits = tools["search_chunks"].handler({"query": "Box put item", "k": 3})["results"]
    assert hits[0]["id"] == "01_classes/shapes.Box.html#put"
