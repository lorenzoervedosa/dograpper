"""`pack --api-records` on rustdoc pages: container and member records (ADR-0009).

The fixture is rustdoc 1.96 output for the crate in tests/fixtures/rustdoc/src
(regenerate with tests/fixtures/rustdoc/regenerate.sh).
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

RUSTDOC = Path(__file__).parent / "fixtures" / "rustdoc" / "html"
NIGHTLY = Path(__file__).parent / "fixtures" / "rustdoc" / "nightly" / "html"


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    # No stray .dograpper.json / manifest / .docsignore from the caller's directory.
    monkeypatch.chdir(tmp_path)


def _page(name):
    return (RUSTDOC / "fixture" / name).read_text(encoding="utf-8")


def _records(name):
    return {r.symbol: r for r in split_page(_page(name))}


def test_a_function_page_is_one_member_record():
    [apply] = split_page(_page("fn.apply.html"))
    assert (apply.symbol, apply.kind, apply.symbol_kind, apply.generator) == (
        "fixture::apply", "member", "function", "rustdoc")
    assert (apply.anchor, apply.container, apply.breadcrumb) == ("", "fixture", ["fixture", "apply"])
    assert apply.text == "\n".join([
        "fixture::apply",
        "pub fn apply<T, U, F>(pair: Pair<T>, f: F) -> Pair<U>",
        "where",
        "    F: FnMut(T) -> U,",  # a declaration keeps its layout
        "Applies f to both values of a pair.",
    ])


def test_the_crate_page_is_a_container_naming_its_items():
    [crate] = split_page(_page("index.html"))
    assert (crate.symbol, crate.kind, crate.symbol_kind) == ("fixture", "container", "crate")
    assert (crate.anchor, crate.container, crate.breadcrumb) == ("", "", ["fixture"])
    assert crate.text == "\n".join([
        "fixture (crate)",
        "Boxes, the errors they raise and the storage trait they share.",
        "Usage",
        "let mut b = fixture::Boxed::new();",
        'b.put("apple").unwrap();',
        "assert_eq!(b.len(), 1);",
        # Item tables keep the names only: descriptions and the unsafe/deprecated badges are dropped.
        "Re-exports: pub use shapes::Point;",
        "Modules: shapes",
        "Macros: boxed",
        "Structs: Boxed",
        "Enums: BoxError",
        "Constants: CAPACITY",
        "Statics: SEALED",
        "Traits: Storage",
        "Functions: apply, apply_first, read_int",
        "Type Aliases: ByteBox, Pair",
        "Unions: Bits",
    ])


def test_a_module_page_is_named_by_its_path():
    [module] = split_page(_page("shapes/index.html"))
    assert (module.symbol, module.symbol_kind) == ("fixture::shapes", "module")
    assert module.text == "\n".join([
        "fixture::shapes (module)", "Shapes that fit in a box.",
        "Structs: Point, Square", "Traits: Shape"])


def test_records_keep_page_order_with_the_container_first():
    assert [r.symbol for r in split_page(_page("struct.Boxed.html"))] == [
        "fixture::Boxed", "fixture::Boxed::items", "fixture::Boxed::label", "fixture::Boxed::LIMIT",
        "fixture::Boxed::new", "fixture::Boxed::put", "fixture::Boxed::map", "fixture::Boxed::len",
        "fixture::Boxed::is_empty", "fixture::Boxed::size", "fixture::Boxed::sort",
    ]


def test_struct_container_record():
    box = split_page(_page("struct.Boxed.html"))[0]
    assert (box.kind, box.symbol_kind, box.anchor, box.container, box.breadcrumb) == (
        "container", "struct", "", "", ["fixture::Boxed"])
    assert box.text == "\n".join([
        "fixture::Boxed (struct)",
        "pub struct Boxed<T> {",
        "    pub items: Vec<T>,",
        "    pub label: Option<String>,",
        "    /* private fields */",
        "}",
        "A generic box that stores items in insertion order.",
        "Items keep their order; see Boxed::put.",
        "Fields: items, label",
        "Associated constants: LIMIT",
        "Methods: new, put, map, len, is_empty, size, sort",
        # Trait implementations keep their impl headers; their items and the blanket
        # implementations (Any, Borrow<T>, From<T>, ...) are dropped.
        "Trait Implementations",
        "impl<T: Clone> Clone for Boxed<T>",
        "impl<T: Debug> Debug for Boxed<T>",
        "impl<T: Default> Default for Boxed<T>",
        "impl<T: Display> Display for Boxed<T>",
        "impl<T: PartialEq> PartialEq for Boxed<T>",
        "impl<T> Storage<usize> for Boxed<T>",
        "impl<T> StructuralPartialEq for Boxed<T>",
        "Auto Trait Implementations",
        "impl<T> Freeze for Boxed<T>",
        "impl<T> RefUnwindSafe for Boxed<T>",
        "where T: RefUnwindSafe,",
        "impl<T> Send for Boxed<T>",
        "where T: Send,",
        "impl<T> Sync for Boxed<T>",
        "where T: Sync,",
        "impl<T> Unpin for Boxed<T>",
        "where T: Unpin,",
        "impl<T> UnsafeUnpin for Boxed<T>",
        "impl<T> UnwindSafe for Boxed<T>",
        "where T: UnwindSafe,",
    ])
    # A member's doc comment lives on its member record only.
    assert "Stores one item." not in box.text


def test_member_record_of_a_generic_method_carries_its_impl_header():
    recs = _records("struct.Boxed.html")
    put = recs["fixture::Boxed::put"]
    assert (put.kind, put.symbol_kind, put.anchor, put.container, put.breadcrumb) == (
        "member", "method", "method.put", "fixture::Boxed", ["fixture::Boxed", "put"])
    assert put.text == "\n".join([
        "fixture::Boxed::put",
        "impl<T> Boxed<T>",
        "pub fn put(&mut self, item: T) -> Result<(), BoxError>",
        "Stores one item.",
        "Errors",
        "Returns BoxError::Full when the box already holds Self::LIMIT items.",
    ])
    assert recs["fixture::Boxed::map"].text.split("\n")[1:4] == [
        "impl<T> Boxed<T>", "pub fn map<U, F>(self, f: F) -> Boxed<U>", "where F: FnMut(T) -> U,"]
    # The second impl block's bound reaches its member.
    assert recs["fixture::Boxed::sort"].text == "\n".join([
        "fixture::Boxed::sort", "impl<T: Ord> Boxed<T>", "pub fn sort(&mut self)", "Sorts the items in place."])


def test_undocumented_and_deprecated_members_keep_their_signature():
    recs = _records("struct.Boxed.html")
    assert recs["fixture::Boxed::len"].text == \
        "fixture::Boxed::len\nimpl<T> Boxed<T>\npub fn len(&self) -> usize"
    assert recs["fixture::Boxed::label"].text == "fixture::Boxed::label\nlabel: Option<String>"
    assert recs["fixture::Boxed::size"].text == "\n".join([
        "fixture::Boxed::size", "impl<T> Boxed<T>", "pub fn size(&self) -> usize",
        "Deprecated since 0.2.0:", "use len instead", "The number of items."])


def test_enum_variants_are_members_and_keep_their_fields():
    recs = split_page(_page("enum.BoxError.html"))
    assert [r.symbol for r in recs] == [
        "fixture::BoxError", "fixture::BoxError::Full", "fixture::BoxError::Sealed",
        "fixture::BoxError::Other"]
    error = recs[0]
    assert error.text.split("\n")[:4] == [
        "fixture::BoxError (enum)", "#[non_exhaustive]", "pub enum BoxError {", "    Full,"]
    # The non-exhaustive boilerplate is dropped: the declaration says it.
    assert "additional variants" not in error.text
    assert "Variants: Full, Sealed, Other" in error.text.split("\n")
    sealed = recs[2]
    assert (sealed.symbol_kind, sealed.anchor, sealed.container) == (
        "variant", "variant.Sealed", "fixture::BoxError")
    assert sealed.text == "\n".join([
        "fixture::BoxError::Sealed", "Sealed", "The box was sealed.",
        "Fields", "since: u64", "When it was sealed, in seconds since the epoch."])
    assert recs[3].text == "fixture::BoxError::Other\nOther(i32)"


@pytest.mark.parametrize("page, symbol, symbol_kind, anchor, signature", [
    ("union.Bits.html", "fixture::Bits::float", "field", "structfield.float", "float: f64"),
    ("shapes/struct.Square.html", "fixture::shapes::Square::0", "field", "structfield.0", "0: f64"),  # tuple field
    ("shapes/struct.Point.html", "fixture::shapes::Point::ORIGIN", "associated_constant",
     "associatedconstant.ORIGIN", "impl Point\npub const ORIGIN: Point"),
    ("trait.Storage.html", "fixture::Storage::Item", "associated_type", "associatedtype.Item", "type Item"),
    ("trait.Storage.html", "fixture::Storage::RETRIES", "associated_constant", "associatedconstant.RETRIES",
     "const RETRIES: u32 = 3"),
    ("trait.Storage.html", "fixture::Storage::get", "method", "tymethod.get",
     "fn get(&self, key: &K) -> Option<&Self::Item>"),
    ("trait.Storage.html", "fixture::Storage::contains", "method", "method.contains",
     "fn contains(&self, key: &K) -> bool"),
    ("shapes/trait.Shape.html", "fixture::shapes::Shape::area", "method", "tymethod.area", "fn area(&self) -> f64"),
])
def test_member_kinds_and_signatures(page, symbol, symbol_kind, anchor, signature):
    rec = _records(page)[symbol]
    container = symbol.rsplit("::", 1)[0]
    assert (rec.kind, rec.symbol_kind, rec.anchor, rec.container) == ("member", symbol_kind, anchor, container)
    assert rec.breadcrumb == [container, symbol.rsplit("::", 1)[1]]
    assert (rec.text + "\n").startswith(f"{symbol}\n{signature}\n")


def test_trait_container_lists_its_items_and_implementations():
    storage = split_page(_page("trait.Storage.html"))[0]
    assert storage.symbol_kind == "trait"
    assert storage.text.split("\n")[-12:] == [
        "A keyed store of items.",
        "Dyn Compatibility",
        "This trait is not dyn compatible.",
        'In older versions of Rust, dyn compatibility was called "object safety", '
        "so this trait is not object safe.",
        "Associated constants: RETRIES",  # page order: rustdoc puts the consts section first
        "Associated types: Item",
        "Required methods: get",
        "Methods: contains",
        "Implementations on Foreign Types",
        "impl<T> Storage<usize> for Vec<T>",
        "Implementors",
        "impl<T> Storage<usize> for Boxed<T>",
    ]


def test_type_alias_is_a_container_of_the_aliased_fields():
    recs = split_page(_page("type.ByteBox.html"))
    assert [r.symbol for r in recs] == ["fixture::ByteBox", "fixture::ByteBox::items", "fixture::ByteBox::label"]
    assert recs[0].symbol_kind == "type_alias"
    assert recs[0].text == "\n".join([
        "fixture::ByteBox (type_alias)", "pub type ByteBox = Boxed<u8>;", "A box of bytes.",
        "Aliased Type", "pub struct ByteBox {", "    pub items: Vec<u8>,", "    pub label: Option<String>,",
        "    /* private fields */", "}", "Fields: items, label"])


@pytest.mark.parametrize("page, symbol_kind, text", [
    ("constant.CAPACITY.html", "constant",
     ["fixture::CAPACITY", "pub const CAPACITY: usize = 16;", "The largest number of items a box holds."]),
    ("static.SEALED.html", "static",
     ["fixture::SEALED", "pub static SEALED: AtomicUsize", "The number of boxes sealed so far."]),
    ("macro.boxed.html", "macro",
     ["fixture::boxed", "macro_rules! boxed {", "    ($($item:expr),* $(,)?) => { ... };", "}",
      "Makes a box from a list of items."]),
    ("fn.apply_first.html", "function",
     ["fixture::apply_first", "pub fn apply_first<T, F: FnOnce(T) -> T>(pair: Pair<T>, f: F) -> Pair<T>",
      "Deprecated since 0.2.0:", "use apply instead", "Applies f to the first value of a pair only."]),
    ("fn.read_int.html", "function",
     ["fixture::read_int", "pub unsafe fn read_int(bits: &Bits) -> u64", "Reads the bits as an integer.",
      "Safety", "The bits must have been written as an integer."]),
])
def test_function_constant_static_and_macro_pages_are_one_member_record(page, symbol_kind, text):
    [rec] = split_page(_page(page))
    assert (rec.kind, rec.symbol_kind, rec.anchor, rec.container) == ("member", symbol_kind, "", "fixture")
    assert rec.text == "\n".join(text)


def test_symbol_pages_are_split_and_the_list_page_kept_whole():
    paths = sorted(str(p) for p in RUSTDOC.rglob("*.html"))
    split = split_api_pages(paths, str(RUSTDOC))
    assert len(split.records) == len(paths) - 1
    assert split.kept_whole == [("fixture/all.html", "rustdoc list, help or source page")]


def test_notable_trait_marks_are_dropped_from_signatures():
    page = _page("struct.Boxed.html")
    put = '<section id="method.put"'
    end = page.index("</h4>", page.index(put))
    # The mark rustdoc 1.96 writes after a return type that implements a notable trait (Iterator, ...).
    marked = page[:end] + ' <a href="#" class="tooltip" data-notable-ty="Result">ⓘ</a>' + page[end:]
    assert {r.symbol: r for r in split_page(marked)}["fixture::Boxed::put"].text == \
        _records("struct.Boxed.html")["fixture::Boxed::put"].text


def test_the_measured_nightly_is_split_and_its_notable_trait_mark_dropped():
    # rustdoc 1.102.0-nightly writes the mark as <span class="tooltip">, not the <a> of 1.96.
    page = (NIGHTLY / "nightly_fixture" / "struct.Bag.html").read_text(encoding="utf-8")
    assert "ⓘ" in page
    recs = {r.symbol: r for r in split_page(page)}
    assert set(recs) == {"nightly_fixture::Bag", "nightly_fixture::Bag::drain_all", "nightly_fixture::Bag::len"}
    assert recs["nightly_fixture::Bag::drain_all"].text == "\n".join([
        "nightly_fixture::Bag::drain_all",
        "impl<T> Bag<T>",
        "pub fn drain_all(self) -> IntoIter<T>",
        "Takes the items out, one by one.",
    ])


def test_record_url_carries_the_member_anchor():
    recs = _records("struct.Boxed.html")
    page = "https://example.com/fixture/struct.Boxed.html"
    assert recs["fixture::Boxed"].url(page) == page
    assert recs["fixture::Boxed::put"].url(page) == page + "#method.put"


@pytest.mark.parametrize("old, new, problem", [
    ('<body class="rustdoc struct">', '<body class="rustdoc primitive">', "page kind primitive"),
    ('<body class="rustdoc struct">', "<body>", "no body.rustdoc"),
    ('<section id="main-content"', '<section id="content"', "no section#main-content"),
    ('<div class="rustdoc-breadcrumbs">', '<div class="crumbs">', "no div.rustdoc-breadcrumbs"),
    ('<h1>Struct <span class="struct">Boxed</span>', "<h1>Struct Boxed", "no name in the h1"),
    ('id="trait-implementations"', 'id="deref-methods-T"', "unknown section deref-methods-T"),
    ('<section id="method.map"', '<section id="method.put"', "duplicate member id"),
    ('data-rustdoc-version="1.96.1', 'data-rustdoc-version="1.98.0-nightly',
     r"version 1.98.0-nightly \(.*\) \(measured: 1\.96\.x, 1\.102\.0-nightly 6905905bb\)"),
])
def test_a_page_with_other_markup_is_not_split(old, new, problem):
    page = _page("struct.Boxed.html")
    assert old in page
    with pytest.raises(NotSplit, match=f"unsupported rustdoc markup: {problem}"):
        split_page(page.replace(old, new, 1))


NEST, MEMBERS = 3000, 4000  # the sizes the Javadoc and Sphinx linearity tests use
HEAD = ('<meta name="generator" content="rustdoc"><meta name="rustdoc-vars" data-rustdoc-version="1.96.1">'
        '<body class="rustdoc struct"><section id="main-content">'
        '<div class="rustdoc-breadcrumbs">{crumbs}</div><h1>Struct <span>S</span></h1>')


def _fields(n):
    return '<h2 id="fields" class="section-header">Fields</h2>' + "".join(
        f'<span id="structfield.f{i}" class="structfield">f{i}: u8</span><div class="docblock">doc</div>'
        for i in range(n))


def test_parsing_stays_linear_on_hostile_markup():
    # Deep unclosed nesting with stray end tags, and (separately, so each stays cheap) many members.
    def hostile(deep, members):
        return (HEAD.format(crumbs="m") + "<p><b>" * deep + "</i>" * deep + "</p>" * deep
                + _fields(members))

    def run(page):
        assert len(split_page(page)) == page.count('class="structfield"') + 1
    assert_linear(lambda n: hostile(n, 0), run, n=NEST)
    assert_linear(lambda n: hostile(0, n), run, n=MEMBERS)
    with pytest.raises(NotSplit):
        split_page(HEAD.format(crumbs="m") + '<h2 id="implementations" class="section-header"></h2>'
                   + '<section id="method.f" class="method">' * 40000)
    # A module page's list heading is read once, not once per name it lists.
    def module(n):
        return (HEAD.replace("rustdoc struct", "rustdoc mod crate") + '<h2 id="structs" class="section-header">'
                + "A<br>" * n + '</h2><dl class="item-table">' + "<dt>x</dt>" * n)

    def run_module(page):
        assert split_page(page)[0].text.endswith(" x")
    assert_linear(module, run_module, n=MEMBERS)


def test_names_repeated_on_every_member_are_bounded():
    # Every member record repeats its container's name and its impl block's header, so a huge
    # one times many members would make the output quadratic in the page size.
    def long_crumbs(n):
        return HEAD.format(crumbs="X" * n) + _fields(n)

    def long_impl(n):
        return (HEAD.format(crumbs="m") + '<h2 id="implementations" class="section-header"></h2>'
                '<section class="impl"><h3 class="code-header">impl ' + "X" * n + "</h3></section>"
                + "".join(f'<section id="method.f{i}" class="method"><h4>fn f{i}()</h4></section>'
                          for i in range(n)))

    with pytest.raises(NotSplit, match="a qualified name over 1000 characters"):
        split_page(long_crumbs(2000))
    with pytest.raises(NotSplit, match="an impl header over 1000 characters"):
        split_page(long_impl(2000))

    def run(html):
        with pytest.raises(NotSplit):
            split_page(html)
    assert_linear(long_crumbs, run, 2000)
    assert_linear(long_impl, run, 2000)


def _pack(src, out):
    return CliRunner().invoke(cli, ["pack", str(src), "-o", str(out), "--format", "jsonl", "--api-records"],
                              catch_exceptions=False)


def _corpus(tmp_path):
    src = tmp_path / "doc"
    shutil.copytree(RUSTDOC, src)
    return src


def test_pack_writes_rustdoc_records(tmp_path):
    src, out = _corpus(tmp_path), tmp_path / "out"
    result = _pack(src, out)
    assert result.exit_code == 0, result.output
    by_id = {}
    for name in sorted(os.listdir(out)):
        if name.endswith(".jsonl"):
            with open(out / name, encoding="utf-8") as f:
                by_id.update((r["id"], r) for r in map(json.loads, f) if r)
    box = by_id["01_fixture/struct.Boxed.html"]
    assert {k: box[k] for k in ("symbol", "kind", "symbol_kind", "generator", "breadcrumb")} == {
        "symbol": "fixture::Boxed", "kind": "container", "symbol_kind": "struct",
        "generator": "rustdoc", "breadcrumb": ["fixture::Boxed"]}
    put = by_id["01_fixture/struct.Boxed.html#method.put"]
    assert (put["kind"], put["symbol_kind"], put["container"], put["breadcrumb"]) == (
        "member", "method", "fixture::Boxed", ["fixture::Boxed", "put"])
    assert put["words"] == len(put["content"].split())
    # A function page is one member record, under the page's own id.
    apply = by_id["01_fixture/fn.apply.html"]
    assert (apply["symbol"], apply["kind"], apply["container"]) == ("fixture::apply", "member", "fixture")
    assert "symbol" not in by_id["01_fixture/all.html"]
    assert "fixture/all.html: rustdoc list, help or source page" in result.stderr
    assert "API records:     17 pages split into 44 records (11 container, 33 member), 1 pages kept whole" \
        in result.output


def test_serve_finds_the_rustdoc_member_record(tmp_path):
    src, out = _corpus(tmp_path), tmp_path / "out"
    assert _pack(src, out).exit_code == 0
    chunks = load_chunks(str(out))
    tools = {t.name: t for t in build_tools(chunks, build_index(chunks), {}, {}, "docs_chunk_")}
    hits = tools["search_chunks"].handler({"query": "Boxed put item", "k": 3})["results"]
    assert hits[0]["id"] == "01_fixture/struct.Boxed.html#method.put"
