"""`pack --api-records` on Doxygen pages: container and member records (ADR-0009).

The fixture is Doxygen 1.9.8 output for the C++ and C sources in tests/fixtures/doxygen/src
(regenerate with tests/fixtures/doxygen/regenerate.sh).
"""

import json
import os
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

DOXYGEN = Path(__file__).parent / "fixtures" / "doxygen" / "html"


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    # No stray .dograpper.json / manifest / .docsignore from the caller's directory.
    monkeypatch.chdir(tmp_path)


def _page(name):
    return (DOXYGEN / name).read_text(encoding="utf-8")


def test_a_member_documented_in_the_summary_only_is_a_member_record():
    # A member with only a brief description has no detailed section: Doxygen puts its
    # anchor and its brief in the summary row, so the row is its record.
    point, distance, x, y = split_page(_page("cpp/structshapes_1_1Point.html"))
    assert (point.symbol, point.kind, point.symbol_kind, point.generator) == (
        "shapes::Point", "container", "struct", "doxygen")
    assert (point.anchor, point.container, point.breadcrumb) == ("", "", ["shapes::Point"])
    assert point.text == "\n".join([
        "shapes::Point (struct)",
        "A point on the plane.",
        "#include <shapes.hpp>",
        "A point on the plane.",  # the brief, repeated at the start of the detailed description
        "Public Member Functions: distance",
        "Public Attributes: x, y",
    ])
    assert (distance.symbol, distance.kind, distance.symbol_kind) == (
        "shapes::Point::distance", "member", "function")
    assert (distance.anchor, distance.container, distance.breadcrumb) == (
        "a738d69a557959c710783c290e0766ef3", "shapes::Point", ["shapes::Point", "distance"])
    assert distance.text == "\n".join([
        "shapes::Point::distance", "double distance (const Point &other) const", "The distance to another point."])
    assert (x.symbol, x.symbol_kind, x.text) == (
        "shapes::Point::x", "variable", "shapes::Point::x\ndouble x\nHorizontal position.")
    assert y.symbol == "shapes::Point::y"


BOX = "shapes::Box< T, N >"
CLASS_TEMPLATE = "template<typename T , std::size_t N = BOX_CAPACITY>"  # on every member's section


def _records(name):
    return {r.anchor: r for r in split_page(_page(name))}


def test_class_template_records_keep_page_order_with_the_container_first():
    # Members documented in their summary row come first, as the summary tables come first;
    # then the documentation sections, in Doxygen's order (typedefs, enums, functions, friends).
    assert [(r.symbol[len(BOX) + 2:], r.kind, r.symbol_kind) for r in split_page(_page("cpp/classshapes_1_1Box.html"))] == [
        ("", "container", "class"),
        ("value_type", "member", "typedef"), ("Box", "member", "function"), ("put_all", "member", "function"),
        ("size", "member", "function"),
        ("operator==", "member", "function"), ("limit", "member", "variable"),
        ("size_type", "member", "typedef"), ("Lid", "member", "enum"), ("count", "member", "function"),
        ("map", "member", "function"), ("put", "member", "function"), ("put", "member", "function"),
        ("operator!=", "member", "function"),
    ]


def test_class_template_container_record():
    box = split_page(_page("cpp/classshapes_1_1Box.html"))[0]
    assert (box.symbol, box.breadcrumb) == (BOX, [BOX])
    assert box.text == "\n".join([
        "shapes::Box< T, N > (class)",
        "A generic box that stores items in insertion order.",
        "#include <shapes.hpp>",
        "template<typename T, std::size_t N = BOX_CAPACITY>",
        "class shapes::Box< T, N >",
        "A generic box that stores items in insertion order.",
        "Items keep their order; see put().",
        "Template Parameters",
        "T",
        "the item type",
        "N",
        "the most items the box holds",
        # The summary tables keep the names only, by section; the nested class is a page of its own.
        "Classes: View",
        "Public Types: Lid, value_type, size_type",
        "Public Member Functions: Box, put, put_all, map, size, operator==, count",
        "Static Public Attributes: limit",
        "Friends: operator!=",
    ])
    # A member's documentation lives on its member record only.
    assert "Stores one item." not in box.text


def test_a_member_template_keeps_both_template_headers():
    page = "cpp/classshapes_1_1Box.html"
    box_map = _records(page)["a8d3c008457f75735d700d3ed5e084290"]
    assert (box_map.symbol, box_map.container, box_map.breadcrumb) == (f"{BOX}::map", BOX, [BOX, "map"])
    assert box_map.text == "\n".join([
        f"{BOX}::map",
        CLASS_TEMPLATE,
        "template<typename F >",
        "auto shapes::Box< T, N >::map ( F f ) const -> Box< decltype(f(std::declval< T >())), N >",
        "Applies a function to every item.",
        "Template Parameters",
        "F",
        "the function type",
        "Parameters",
        "f",
        "the function",
        "Returns a box of the results, in the same order",
        # The example keeps its lines; the tooltips Doxygen writes for its links are dropped.
        "Box<int> ints;",
        "auto doubled = ints.map([](int i) { return i * 2; });",
    ])


def test_a_member_template_documented_in_the_summary_keeps_its_template_header():
    # Doxygen puts the anchor of such a member in its template header row, not in its own row.
    put_all = _records("cpp/classshapes_1_1Box.html")["a289998e3021313acbfa802df17bd0f1d"]
    assert (put_all.symbol, put_all.symbol_kind) == (f"{BOX}::put_all", "function")
    assert put_all.text == "\n".join([
        f"{BOX}::put_all", "template<typename It >", "void put_all (It first, It last)",
        "Stores every item of a range, in order."])


def test_a_link_without_a_value_is_read_as_any_link():
    # html.parser gives a valueless attribute None, not "".
    page = _page("cpp/structshapes_1_1Point.html").replace("<p><code>#include", "<p><a href>See also</a> <code>#include", 1)
    assert split_page(page)[0].text.split("\n")[2] == "See also #include <shapes.hpp>"


def test_overloads_are_one_record_each_under_their_own_anchor():
    recs = _records("cpp/classshapes_1_1Box.html")
    by_copy, by_move = recs["a9b2c9af7709c2bb0ffabf015a63b470a"], recs["ab1ff8e2bd6b1b6d72d3413e74051d165"]
    assert by_copy.symbol == by_move.symbol == f"{BOX}::put"  # "[1/2]" after the name is dropped
    assert by_copy.text.split("\n")[1:4] == [
        CLASS_TEMPLATE, "BoxError shapes::Box< T, N >::put ( const T & item )", "Stores one item."]
    assert by_move.text.split("\n")[1:4] == [
        CLASS_TEMPLATE, "BoxError shapes::Box< T, N >::put ( T && item )", "Stores one item, moving it in."]


def test_labels_enumerators_and_notes_stay_on_the_member_record():
    recs = _records("cpp/classshapes_1_1Box.html")
    assert recs["a01f18ac2971596678134b031230cf527"].text == "\n".join([
        f"{BOX}::Lid", CLASS_TEMPLATE, "enum class shapes::Box::Lid", "strong", "How the box was closed.",
        "Enumerator", "Open", "Items can still be put in.", "Closed", "No more items."])
    assert recs["a1859c1549bc929f88edf5e78c5803846"].text.split("\n")[2:] == [
        "std::size_t shapes::Box< T, N >::count ( ) const", "noexcept", "The number of items.",
        "Deprecated: Use size() instead."]
    friend = recs["ab2891378a0b4fbbe5df3843bcd81c3b8"]
    assert (friend.symbol, friend.symbol_kind) == (f"{BOX}::operator!=", "function")
    assert friend.text.split("\n")[2:5] == [
        "bool operator!= ( const Box< T, N > & a, const Box< T, N > & b )", "friend",
        "Two boxes differ when they are not equal."]


def test_the_page_labels_follow_the_container_line():
    shape = split_page(_page("cpp/classshapes_1_1Shape.html"))[0]
    assert shape.text.split("\n")[:3] == ["shapes::Shape (class)", "abstract", "Anything with an area."]


def test_inherited_members_are_listed_by_base_on_the_container():
    square, ctor, area = split_page(_page("cpp/classshapes_1_1Square.html"))
    assert square.text.split("\n")[-2:] == [
        "Public Member Functions: Square, area", "Public Member Functions inherited from shapes::Shape: name"]
    assert "Inheritance diagram" not in square.text
    assert ctor.text == "shapes::Square::Square\nSquare (double side)\nA square of the given side."
    assert area.text == "\n".join([
        "shapes::Square::area", "double shapes::Square::area ( ) const", "override virtual",
        "The side times itself.", "Implements shapes::Shape."])


def test_namespace_page_is_a_container_of_its_members():
    recs = split_page(_page("cpp/namespaceshapes.html"))
    assert [(r.symbol, r.symbol_kind) for r in recs] == [
        ("shapes", "namespace"), ("shapes::IntBox", "typedef"), ("shapes::boxes_made", "variable"),
        ("shapes::BoxError", "enum"), ("shapes::make_box", "function")]
    assert recs[0].text == "\n".join([
        "shapes (namespace)", "Shapes that fit in a box.", "Shapes that fit in a box.",
        "Namespaces: detail", "Classes: Bits, Box, Point, Shape, Square", "Typedefs: IntBox",
        "Enumerations: BoxError", "Functions: make_box", "Variables: boxes_made"])
    make_box = recs[-1]
    assert (make_box.container, make_box.breadcrumb) == ("shapes", ["shapes", "make_box"])
    assert make_box.text.split("\n")[:4] == [
        "shapes::make_box", "template<typename T >", "Box< T > shapes::make_box ( T item )",
        "Makes a box that holds one item."]


def test_cpp_file_page_documents_its_macros_and_global_functions():
    recs = split_page(_page("cpp/shapes_8hpp.html"))
    # The namespace members a file page lists are documented on the namespace page, even those
    # Doxygen also anchors here (brief only): they are names on the file's record, not records.
    assert [(r.symbol, r.symbol_kind, r.container) for r in recs] == [
        ("shapes.hpp", "file", ""), ("BOX_CAPACITY", "define", "shapes.hpp"), ("MAKE_BOX", "define", "shapes.hpp"),
        ("reset_boxes", "function", "shapes.hpp")]
    assert recs[0].text == "\n".join([
        "shapes.hpp (file)",
        "Boxes, the shapes they hold and the errors they raise.",
        "#include <cstddef>",
        "#include <utility>",
        "#include <vector>",
        "Boxes, the shapes they hold and the errors they raise.",
        "Classes: shapes::Point, shapes::Bits, shapes::Shape, shapes::Square, shapes::Box< T, N >, "
        "shapes::Box< T, N >::View< U >",
        "Namespaces: shapes, shapes::detail",
        "Macros: BOX_CAPACITY, MAKE_BOX",
        "Typedefs: shapes::IntBox",
        "Enumerations: shapes::BoxError",
        "Functions: shapes::make_box, reset_boxes, shapes::detail::fits",
        "Variables: shapes::boxes_made",
    ])
    assert recs[1].text == "BOX_CAPACITY\n#define BOX_CAPACITY 16\nThe largest number of items a box holds by default."
    assert recs[2].text == "\n".join([
        "MAKE_BOX", "#define MAKE_BOX ( ... ) ::shapes::Box<int>{__VA_ARGS__}",
        "Makes a box of ints from a list of items.", "The items are copied into the box in order."])
    assert recs[3].breadcrumb == ["shapes.hpp", "reset_boxes"]


def test_a_file_page_documents_the_members_of_a_namespace_without_a_page():
    # An undocumented namespace has no page (libstdc++'s std): the file page lists no such
    # namespace, and the members it anchors are documented there only.
    page = _page("cpp/shapes_8hpp.html")
    start = page.index('<table class="memberdecls">\n<tr class="heading"><td colspan="2"><h2 class="groupheader"><a id="namespaces"')
    page = page[:start] + page[page.index("</table>", start) + len("</table>"):]
    recs = split_page(page)
    assert [r.symbol for r in recs] == [
        "shapes.hpp", "BOX_CAPACITY", "shapes::IntBox", "shapes::detail::fits", "shapes::boxes_made",
        "MAKE_BOX", "reset_boxes"]
    assert recs[2].text == "shapes::IntBox\nusing shapes::IntBox = Box< int >\nA box of ints."
    assert (recs[2].container, recs[2].breadcrumb) == ("shapes.hpp", ["shapes.hpp", "shapes::IntBox"])


def test_c_file_page_is_a_container_of_its_globals():
    recs = _records("c/ring_8h.html")
    ring_h = recs[""]
    assert (ring_h.symbol, ring_h.symbol_kind) == ("ring.h", "file")
    assert ring_h.text.split("\n")[-6:] == [
        "Data Structures: ring", "Macros: RING_SIZE, RING_MAX", "Typedefs: ring_status, ring_visitor",
        "Enumerations: ring_status", "Functions: ring_init, ring_push, ring_visit, ring_clear",
        "Variables: ring_count"]
    assert [(r.symbol, r.symbol_kind) for r in recs.values()][1:] == [
        ("RING_MAX", "define"), ("ring_status", "typedef"), ("ring_visitor", "typedef"), ("RING_SIZE", "define"),
        ("ring_status", "enum"), ("ring_clear", "function"), ("ring_init", "function"), ("ring_push", "function"),
        ("ring_visit", "function"), ("ring_count", "variable")]
    assert recs["ad619a5ad10868da4a4a4fc3499c4718f"].text == "\n".join([
        "ring_visitor", "typedef void(* ring_visitor) (unsigned char byte, void *ctx)",
        "Called once per byte by ring_visit()."])
    assert recs["ad65c0edeeb4d8558ed0702e20e8bb269"].text == "\n".join([
        "ring_push", "ring_status ring_push ( struct ring * r, unsigned char byte )",
        "Stores one byte at the tail.", "Parameters", "r", "the ring", "byte", "the byte to store",
        "Returns RING_FULL when the ring already holds RING_SIZE bytes, else RING_OK."])
    assert recs["ad58c19bce1efa5d66b97448915252c85"].text.split("\n")[1:3] == ["int ring_count", "extern"]


def test_c_struct_fields_are_member_records():
    ring, data, head, tail = split_page(_page("c/structring.html"))
    assert ring.text == "\n".join([
        "ring (struct)", "A ring buffer of bytes.", "#include <ring.h>", "A ring buffer of bytes.",
        "Data Fields: data, head, tail"])
    assert (data.symbol, data.symbol_kind, data.container) == ("ring::data", "variable", "ring")
    assert data.text == "ring::data\nunsigned char ring::data[RING_SIZE]\nThe bytes, in a circle."
    assert [head.symbol, tail.symbol] == ["ring::head", "ring::tail"]


SYMBOL_PAGES = {
    "cpp/classshapes_1_1Box.html", "cpp/classshapes_1_1Box_1_1View.html", "cpp/classshapes_1_1Shape.html",
    "cpp/classshapes_1_1Square.html", "cpp/structshapes_1_1Point.html", "cpp/unionshapes_1_1Bits.html",
    "cpp/namespaceshapes.html", "cpp/namespaceshapes_1_1detail.html", "cpp/shapes_8hpp.html",
    "c/ring_8h.html", "c/structring.html",
}


def test_symbol_pages_are_split_and_the_index_listing_and_source_pages_kept_whole():
    paths = sorted(str(p) for p in DOXYGEN.rglob("*.html"))
    split = split_api_pages(paths, str(DOXYGEN))
    assert set(split.records) == SYMBOL_PAGES
    kept = dict(split.kept_whole)
    assert len(kept) == len(paths) - len(SYMBOL_PAGES)
    # The member lists, sources, class and file lists, symbol indexes, main page and deprecated list.
    assert {"cpp/classshapes_1_1Box-members.html", "cpp/shapes_8hpp_source.html", "cpp/annotated.html",
            "cpp/functions_func.html", "cpp/index.html", "c/deprecated.html", "c/globals.html"} <= set(kept)
    assert set(kept.values()) == {"Doxygen index, listing, source or topic page"}


def test_a_file_page_that_documents_no_member_keeps_one_record():
    page = _page("cpp/shapes_8hpp.html")
    start = page.index('<h2 class="groupheader">Macro Definition Documentation</h2>')
    listing = page[:start] + page[page.index("</div><!-- contents -->"):]
    listing = listing.replace('<a id="a469756338401413c3ad48ecb8e801b67" name="a469756338401413c3ad48ecb8e801b67"></a>', "")
    with pytest.raises(NotSplit, match="^Doxygen file page that documents no member$"):
        split_page(listing)


@pytest.mark.parametrize("old, new, problem", [
    ("Class Template Reference</div>", "Concept Reference</div>", "page kind Concept"),
    ('<div class="contents">', '<div class="content">', "no div.contents"),
    ("Member Function Documentation", "Property Documentation", "unknown section Property Documentation"),
    ("Static Public Attributes</h2>", "Public Slots</h2>", "a member of unknown kind in section Public Slots"),
    ('<h2 class="groupheader">Detailed Description', '<h2 class="groupheader">Concept Definition',
     "unknown section Concept Definition"),
    ('<a id="a8d3c008457f75735d700d3ed5e084290" name="a8d3c008457f75735d700d3ed5e084290"></a>\n<h2', "<h2",
     "an h2.memtitle without an anchor"),
    ('</h2>\n\n<div class="memitem">', '</h2>\n\n<div class="memitem-x">', "an h2.memtitle without its div.memitem"),
    ('id="ab1ff8e2bd6b1b6d72d3413e74051d165"', 'id="a9b2c9af7709c2bb0ffabf015a63b470a"', "duplicate member anchor"),
    ("&#160;</a></span>map()</h2>", "&#160;</a></span></h2>", "a member without a name"),
])
def test_a_page_with_other_markup_is_not_split(old, new, problem):
    page = _page("cpp/classshapes_1_1Box.html")
    assert old in page
    with pytest.raises(NotSplit, match=f"^unsupported Doxygen markup: {problem}$"):
        split_page(page.replace(old, new, 1))


def test_another_doxygen_version_keeps_the_page_whole():
    page = _page("cpp/classshapes_1_1Box.html")
    old = '<meta name="generator" content="Doxygen 1.9.8"/>'
    assert old in page
    with pytest.raises(NotSplit, match=r"unsupported Doxygen markup: version 1\.10\.0 \(measured: 1\.9\.8\)"):
        split_page(page.replace(old, '<meta name="generator" content="Doxygen 1.10.0"/>', 1))


NEST, MEMBERS = 3000, 4000  # the sizes the Javadoc and Sphinx linearity tests use
HEAD = ('<meta name="generator" content="Doxygen 1.9.8"/><div class="headertitle">'
        '<div class="title">{name} Class Reference</div></div><div class="contents">')


def _summary(n, label="Public Attributes"):
    """n members documented in their summary rows."""
    return (f'<table class="memberdecls"><tr class="heading"><td><h2 class="groupheader">{label}</h2></td></tr>'
            + "".join(f'<tr class="memitem:a{i}"><td class="memItemLeft"><a id="a{i}"></a>int</td>'
                      f'<td class="memItemRight"><b>f{i}</b></td></tr>'
                      f'<tr class="memdesc:a{i}"><td class="mdescRight">doc</td></tr>' for i in range(n))
            + "</table>")


def _sections(n):
    """n members with a documentation section."""
    return '<h2 class="groupheader">Member Function Documentation</h2>' + "".join(
        f'<a id="d{i}"></a><h2 class="memtitle">g{i}()</h2><div class="memitem"><div class="memproto">'
        f'<table class="memname"><tr><td class="memname">void g{i}</td><td>(</td><td>)</td></tr></table></div>'
        f'<div class="memdoc"><p>doc</p></div></div>' for i in range(n))


def test_parsing_stays_linear_on_hostile_markup():
    # Deep unclosed nesting with stray end tags, and (separately, so each stays cheap) many members.
    def hostile(deep, members):
        return (HEAD.format(name="S") + "<p><b>" * deep + "</i>" * deep + "</p>" * deep
                + _summary(members) + _sections(members))

    def run(page):
        assert len(split_page(page)) == page.count('class="memdesc:') + page.count('class="memtitle"') + 1
    assert_linear(lambda n: hostile(n, 0) + _sections(1), run, n=NEST)
    assert_linear(lambda n: hostile(0, n), run, n=MEMBERS // 2)  # two members per n: one of each form

    # A heading is read once, not once per name listed under it.
    def inherited(n):
        return (HEAD.format(name="S") + _sections(1) + '<table class="memberdecls"><tr class="inherit_header x">'
                + "<td>A<br>" * n + "</td></tr>" + "".join(
                    f'<tr class="memitem:b{i} inherit x"><td class="memItemRight"><a class="el">h{i}</a></td></tr>'
                    for i in range(n)) + "</table>")

    def run_inherited(page):
        assert split_page(page)[0].text.split("\n")[-1].startswith("A A A")
    assert_linear(inherited, run_inherited, n=MEMBERS)


def test_names_repeated_on_every_member_are_bounded():
    # Every member record repeats its container's name, so a huge one times many members
    # would make the output quadratic in the page size.
    def long_name(n):
        return HEAD.format(name="X" * n) + _summary(n)

    with pytest.raises(NotSplit, match="a qualified name over 1000 characters"):
        split_page(long_name(2000))

    def run(html):
        with pytest.raises(NotSplit):
            split_page(html)
    assert_linear(long_name, run, 2000)


def _pack(src, out, *flags):
    return CliRunner().invoke(cli, ["pack", str(src), "-o", str(out), "--format", "jsonl", *flags],
                              catch_exceptions=False)


def _corpus(tmp_path):
    src = tmp_path / "doc"
    shutil.copytree(DOXYGEN, src)
    return src


def _jsonl(out):
    by_id = {}
    for name in sorted(os.listdir(out)):
        if name.endswith(".jsonl"):
            with open(out / name, encoding="utf-8") as f:
                by_id.update((r["id"], r) for r in map(json.loads, f) if r)
    return by_id


def test_pack_writes_doxygen_records(tmp_path):
    src, out = _corpus(tmp_path), tmp_path / "out"
    result = _pack(src, out, "--api-records")
    assert result.exit_code == 0, result.output
    by_id = _jsonl(out)
    box = by_id["01_cpp/classshapes_1_1Box.html"]
    assert {k: box[k] for k in ("symbol", "kind", "symbol_kind", "generator", "breadcrumb")} == {
        "symbol": BOX, "kind": "container", "symbol_kind": "class", "generator": "doxygen",
        "breadcrumb": [BOX]}
    put = by_id["01_cpp/classshapes_1_1Box.html#a9b2c9af7709c2bb0ffabf015a63b470a"]
    assert (put["symbol"], put["kind"], put["symbol_kind"], put["container"], put["breadcrumb"]) == (
        f"{BOX}::put", "member", "function", BOX, [BOX, "put"])
    assert put["words"] == len(put["content"].split())
    ring_push = by_id["01_c/ring_8h.html#ad65c0edeeb4d8558ed0702e20e8bb269"]
    assert (ring_push["symbol"], ring_push["container"]) == ("ring_push", "ring.h")
    assert "symbol" not in by_id["01_cpp/classshapes_1_1Box-members.html"]
    assert "c/annotated.html: Doxygen index, listing, source or topic page" in result.stderr
    assert "API records:     11 pages split into 55 records (11 container, 44 member), 45 pages kept whole" \
        in result.output


def test_dedup_never_touches_a_doxygen_page(tmp_path):
    src, out = _corpus(tmp_path), tmp_path / "out"
    result = _pack(src, out, "--dedup", "both")
    assert result.exit_code == 0, result.output
    assert "Pages exempted:    11 (API reference)" in result.output


@pytest.mark.parametrize("query, expected", [
    ("ring push byte", "01_c/ring_8h.html#ad65c0edeeb4d8558ed0702e20e8bb269"),
    ("Box map function every item", "01_cpp/classshapes_1_1Box.html#a8d3c008457f75735d700d3ed5e084290"),
])
def test_serve_finds_the_doxygen_member_record(tmp_path, query, expected):
    src, out = _corpus(tmp_path), tmp_path / "out"
    assert _pack(src, out, "--api-records").exit_code == 0
    chunks = load_chunks(str(out))
    tools = {t.name: t for t in build_tools(chunks, build_index(chunks), {}, {}, "docs_chunk_")}
    hits = tools["search_chunks"].handler({"query": query, "k": 3})["results"]
    assert hits[0]["id"] == expected
