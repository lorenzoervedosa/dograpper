"""`pack --api-records`: API reference pages split into container and member records (ADR-0009).

The fixtures are javadoc 25 output for the sources in tests/fixtures/javadoc/src
(regenerate with tests/fixtures/javadoc/regenerate.sh) and Sphinx 9.2 autodoc output
for tests/fixtures/sphinx/src (tests/fixtures/sphinx/regenerate.sh).
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

FIXTURE = Path(__file__).parent / "fixtures" / "javadoc" / "html"
TYPE_PAGES = ["Box.Lid.html", "Box.html", "Color.html", "Marker.html", "Point.html",
              "Shelf.html", "Storage.html"]


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    # No stray .dograpper.json / manifest / .docsignore from the caller's directory.
    monkeypatch.chdir(tmp_path)


def _page(name):
    return (FIXTURE / "fixture" / "api" / name).read_text(encoding="utf-8")


def _records(name):
    return {r.symbol: r for r in split_page(_page(name))}


# ---------------------------------------------------------------------------
# Detection and dispatch
# ---------------------------------------------------------------------------

def test_type_pages_are_split_and_other_pages_kept_whole():
    paths = sorted(str(p) for p in (FIXTURE / "fixture" / "api").iterdir())
    split = split_api_pages(paths, str(FIXTURE))
    assert sorted(split.records) == [f"fixture/api/{n}" for n in TYPE_PAGES]
    assert split.kept_whole == [
        ("fixture/api/package-summary.html", "Javadoc page, not a type page"),
        ("fixture/api/package-tree.html", "Javadoc page, not a type page"),
    ]


def test_a_page_without_a_supported_generator_is_not_split():
    with pytest.raises(NotSplit, match="no supported generator"):
        split_page("<html><head><title>Guide</title></head><body><p>prose</p></body></html>")
    with pytest.raises(NotSplit, match="no supported generator"):
        split_page('<meta name="generator" content="Sphinx 7.2">' + _page("Box.html"))


@pytest.mark.parametrize("old, new, problem", [
    ('class="class-description"', 'class="description"', "no section.class-description"),
    ('<h1 title="Class Box"', '<h1 title="Thing Box"', "unknown type kind"),
    ('<div class="member-signature">', '<div class="signature">', "without a div.member-signature"),
    ('id="method-detail"', 'id="operation-detail"', "outside the known member sections"),
    ('id="shake(int)"', 'id="clear()"', "duplicate member anchor"),
])
def test_a_type_page_with_other_markup_is_not_split(old, new, problem):
    page = _page("Box.html")
    assert old in page
    with pytest.raises(NotSplit, match=f"unsupported Javadoc markup: .*{problem}"):
        split_page(page.replace(old, new, 1))


NEST, MEMBERS = 3000, 4000  # sized so a stack copy / a list scan per member trips the 7x bound


def test_parsing_stays_linear_on_hostile_markup():
    head = '<meta name="generator" content="javadoc/ClassWriter"><h1 class="title" title="Class X">'
    # Deep unclosed nesting with stray end tags, and (separately, so each stays cheap) many members.
    def hostile(deep, members):
        return (head + '<section class="class-description">' + "<p><b>" * deep
                + "</i>" * deep + "</p>" * deep + '</section><section id="field-detail">'
                + "".join(f'<section class="detail" id="f{i}"><h3>f{i}</h3>'
                          f'<div class="member-signature">int f{i}</div></section>' for i in range(members)))

    def run(page):
        assert len(split_page(page)) == page.count('class="detail"') + 1
    assert_linear(lambda n: hostile(n, 0), run, n=NEST)
    assert_linear(lambda n: hostile(0, n), run, n=MEMBERS)
    n = 40000
    with pytest.raises(NotSplit):
        split_page(head + '<section class="detail" id="x">' * n)


def test_javadoc_qualified_names_are_bounded():
    # Every member symbol repeats the type's name, so a huge name times many members would make
    # the output quadratic in the page size.
    def page(n):
        return ('<meta name="generator" content="javadoc/ClassWriter">'
                f'<h1 class="title" title="Class {"X" * n}"><section class="class-description">'
                '</section><section id="field-detail">'
                + "".join(f'<section class="detail" id="f{i}"><h3>f{i}</h3>'
                          f'<div class="member-signature">int f{i}</div></section>' for i in range(n)))

    with pytest.raises(NotSplit, match="unsupported Javadoc markup: a qualified name over 1000 characters"):
        split_page(page(2000))

    def run(html):
        with pytest.raises(NotSplit):
            split_page(html)
    assert_linear(page, run, 2000)


# ---------------------------------------------------------------------------
# Container records
# ---------------------------------------------------------------------------

def test_container_record_of_a_generic_class():
    box = _records("Box.html")["fixture.api.Box"]
    assert (box.kind, box.symbol_kind, box.anchor, box.container) == ("container", "class", "", "")
    assert box.breadcrumb == ["fixture.api.Box"]
    assert box.generator == "javadoc"
    lines = box.text.split("\n")
    assert lines[:6] == [
        "fixture.api.Box (class)",
        "Inheritance: java.lang.Object > fixture.api.Storage > fixture.api.Box<T>",
        "Type Parameters: T - the type of the stored items",
        "All Implemented Interfaces: Shelf<T>",
        "public class Box<T extends Comparable<T>> extends Storage implements Shelf<T>",
        "A generic box that stores comparable items.",
    ]
    # <pre> keeps its lines
    assert 'Box<String> box = Box.of("apple");\nbox.put("pear");' in box.text
    assert "Fields: CAPACITY, items" in lines
    assert "Constructors: Box" in lines
    assert "Methods: of, put, size, entries, load, toString, clear, shake" in lines
    assert "Fields inherited from class Storage: name" in lines
    assert "Methods inherited from class Storage: label" in lines
    assert "Methods inherited from interface Shelf: isEmpty" in lines


def test_summary_tables_are_dropped():
    box = _records("Box.html")["fixture.api.Box"]
    assert "Modifier and Type" not in box.text
    assert "Method Summary" not in box.text
    # A member's doc comment lives on its member record only.
    assert "Wraps one value in a new box." not in box.text


@pytest.mark.parametrize("page, symbol, kind, signature", [
    ("Shelf.html", "fixture.api.Shelf", "interface", "public interface Shelf<T>"),
    ("Color.html", "fixture.api.Color", "enum", "public enum Color extends Enum<Color>"),
    ("Point.html", "fixture.api.Point", "record",
     "public record Point(int x, int y) extends Record implements Comparable<Point>"),
    ("Marker.html", "fixture.api.Marker", "annotation",
     "@Documented @Retention(RUNTIME) @Target(TYPE) public @interface Marker"),
    ("Box.Lid.html", "fixture.api.Box.Lid", "class", "public static class Box.Lid extends Object"),
])
def test_container_kinds(page, symbol, kind, signature):
    rec = _records(page)[symbol]
    assert rec.symbol_kind == kind
    assert rec.text.startswith(f"{symbol} ({kind})\n")
    assert signature in rec.text.split("\n")


def test_nested_container_gets_its_own_record():
    lid = _records("Box.Lid.html")
    assert "Enclosing class: Box<T extends Comparable<T>>" in lid["fixture.api.Box.Lid"].text
    assert lid["fixture.api.Box.Lid#isClosed()"].container == "fixture.api.Box.Lid"
    assert "fixture.api.Box.Lid" not in _records("Box.html")


# ---------------------------------------------------------------------------
# Member records
# ---------------------------------------------------------------------------

def test_member_record_of_a_generic_method():
    of = _records("Box.html")["fixture.api.Box#of(U)"]
    assert (of.kind, of.symbol_kind, of.anchor, of.container) == ("member", "method", "of(U)", "fixture.api.Box")
    assert of.breadcrumb == ["fixture.api.Box", "of(U)"]
    assert of.text == "\n".join([
        "fixture.api.Box#of(U)",
        "public static <U extends Comparable<U>> Box<U> of(U value)",
        "Wraps one value in a new box.",
        "Type Parameters: U - the type of the value",
        "Parameters: value - the value to wrap",
        "Returns: a box holding value",
    ])


def test_member_notes_overrides_and_throws():
    load = _records("Box.html")["fixture.api.Box#load(java.io.InputStream,int)"]
    assert load.text == "\n".join([
        "fixture.api.Box#load(java.io.InputStream,int)",
        "public void load(InputStream input, int version) throws IOException",
        "Loads the box and its items.",
        "Overrides: load in class Storage",
        "Parameters: input - the stream to read",
        "version - the save format version",
        "Throws: IOException - when the stream cannot be read",
        "IllegalArgumentException - when version is negative",
    ])


def test_member_notes_specified_by_and_nested_generics():
    recs = _records("Box.html")
    assert "Specified by: put in interface Shelf<T extends Comparable<T>>" in recs["fixture.api.Box#put(T)"].text
    assert recs["fixture.api.Box#entries()"].text.split("\n")[1] == "public List<Map<String,T>> entries()"
    assert recs["fixture.api.Box#items"].text.split("\n")[1] == "private List<T extends Comparable<T>> items"


def test_member_without_a_doc_comment_keeps_its_signature():
    shake = _records("Box.html")["fixture.api.Box#shake(int)"]
    assert shake.text == "fixture.api.Box#shake(int)\npublic void shake(int times)"


def test_deprecated_member():
    clear = _records("Box.html")["fixture.api.Box#clear()"]
    assert clear.text.split("\n")[1:4] == [
        "@Deprecated public void clear()",
        "Deprecated.",
        "use put(Comparable) with a new box instead",
    ]


def test_member_kinds_and_names():
    kinds = {s: r.symbol_kind for page in TYPE_PAGES for s, r in _records(page).items()}
    assert kinds["fixture.api.Box#Box(java.lang.String)"] == "constructor"
    assert kinds["fixture.api.Box#CAPACITY"] == "field"
    assert kinds["fixture.api.Color#RED"] == "enum_constant"
    assert kinds["fixture.api.Color#GREEN"] == "enum_constant"
    assert kinds["fixture.api.Marker#value()"] == "element"
    assert kinds["fixture.api.Shelf#isEmpty()"] == "method"
    ctor = _records("Box.html")["fixture.api.Box#Box(java.lang.String)"]
    assert ctor.anchor == "<init>(java.lang.String)"
    assert ctor.breadcrumb == ["fixture.api.Box", "Box(java.lang.String)"]
    assert "Default: 1" in _records("Marker.html")["fixture.api.Marker#since()"].text


def test_records_keep_page_order_with_the_container_first():
    recs = split_page(_page("Color.html"))
    assert [r.symbol for r in recs] == [
        "fixture.api.Color", "fixture.api.Color#RED", "fixture.api.Color#GREEN",
        "fixture.api.Color#BLUE", "fixture.api.Color#Color()", "fixture.api.Color#values()",
        "fixture.api.Color#valueOf(java.lang.String)", "fixture.api.Color#mix(fixture.api.Color)",
    ]


def test_record_url_carries_the_encoded_anchor():
    recs = _records("Box.html")
    page = "https://example.com/api/fixture/api/Box.html"
    assert recs["fixture.api.Box"].url(page) == page
    assert recs["fixture.api.Box#of(U)"].url(page) == page + "#of(U)"
    assert recs["fixture.api.Box#Box(java.lang.String)"].url(page) == page + "#%3Cinit%3E(java.lang.String)"


# ---------------------------------------------------------------------------
# pack --api-records
# ---------------------------------------------------------------------------

def _corpus(tmp_path):
    src = tmp_path / "docs"
    shutil.copytree(FIXTURE, src)
    return src


def _pack(*args):
    return CliRunner().invoke(cli, ["pack", *args], catch_exceptions=False)


def _jsonl(out):
    records = []
    for name in sorted(os.listdir(out)):
        if name.endswith(".jsonl"):
            with open(os.path.join(out, name), encoding="utf-8") as f:
                records.extend(json.loads(line) for line in f if line.strip())
    return records


def test_pack_writes_container_and_member_records(tmp_path):
    src, out = _corpus(tmp_path), tmp_path / "out"
    result = _pack(str(src), "-o", str(out), "--format", "jsonl", "--api-records")
    assert result.exit_code == 0, result.output
    by_id = {r["id"]: r for r in _jsonl(out)}
    box = by_id["01_fixture/api/Box.html"]
    assert {k: box[k] for k in ("source", "symbol", "kind", "symbol_kind", "generator", "breadcrumb")} == {
        "source": "fixture/api/Box.html", "symbol": "fixture.api.Box", "kind": "container",
        "symbol_kind": "class", "generator": "javadoc", "breadcrumb": ["fixture.api.Box"]}
    assert "container" not in box
    of = by_id["01_fixture/api/Box.html#of(U)"]
    assert (of["kind"], of["container"], of["breadcrumb"]) == ("member", "fixture.api.Box",
                                                              ["fixture.api.Box", "of(U)"])
    assert of["words"] == len(of["content"].split())
    assert of["content"].startswith("fixture.api.Box#of(U)\npublic static <U extends Comparable<U>>")
    # Pages that are not split keep one record, with no API fields.
    summary = by_id["01_fixture/api/package-summary.html"]
    assert "symbol" not in summary and "Types used by dograpper" in summary["content"]
    assert "Warning: 2 page(s) kept as one record each, not split into API records:" in result.stderr
    assert "fixture/api/package-summary.html: Javadoc page, not a type page" in result.stderr
    assert "API records:     7 pages split into" in result.output
    assert "2 pages kept whole" in result.output


def test_pack_without_the_flag_keeps_one_record_per_page(tmp_path):
    src, out = _corpus(tmp_path), tmp_path / "out"
    assert _pack(str(src), "-o", str(out), "--format", "jsonl").exit_code == 0
    records = _jsonl(out)
    assert len(records) == 9
    assert not any("symbol" in r for r in records)


def test_api_record_urls_carry_the_member_anchor(tmp_path):
    src, out = _corpus(tmp_path), tmp_path / "out"
    box = src / "fixture" / "api" / "Box.html"
    box.write_text(box.read_text(encoding="utf-8").replace(
        "<html lang=\"en\">",
        "<html lang=\"en\">\n<!-- Mirrored from https://example.com/api/fixture/api/Box.html "
        "by HTTrack Website Copier/3.x [XR&CO'2014], Mon, 01 Jan 2024 00:00:00 GMT -->", 1),
        encoding="utf-8")
    result = _pack(str(src), "-o", str(out), "--format", "jsonl", "--api-records", "--context-header")
    assert result.exit_code == 0, result.output
    urls = {r["id"]: r.get("url") for r in _jsonl(out)}
    assert urls["01_fixture/api/Box.html"] == "https://example.com/api/fixture/api/Box.html"
    assert urls["01_fixture/api/Box.html#<init>(java.lang.String)"] == (
        "https://example.com/api/fixture/api/Box.html#%3Cinit%3E(java.lang.String)")
    assert urls["01_fixture/api/Color.html#RED"] is None


def test_api_pages_bypass_dedup(tmp_path):
    src, out = _corpus(tmp_path), tmp_path / "out"
    # A second copy of a type page: dedup would keep its repeated blocks on one page only.
    shutil.copytree(src / "fixture", src / "copy")
    result = _pack(str(src), "-o", str(out), "--format", "jsonl", "--api-records", "--dedup", "both")
    assert result.exit_code == 0, result.output
    by_id = {r["id"]: r for r in _jsonl(out)}
    assert by_id["01_copy/api/Box.html#load(java.io.InputStream,int)"]["content"].replace("copy", "fixture") == \
        by_id["01_fixture/api/Box.html#load(java.io.InputStream,int)"]["content"]


def test_records_inherit_their_page_chunk(tmp_path):
    src, out = _corpus(tmp_path), tmp_path / "out"
    queries = tmp_path / "queries.txt"
    queries.write_text("mixes this color with another one\n")
    result = _pack(str(src), "-o", str(out), "--format", "jsonl", "--api-records",
                   "--max-words-per-chunk", "200", "--for-queries", str(queries))
    assert result.exit_code == 0, result.output
    chunk_of = {}
    for name in sorted(os.listdir(out)):
        if name.endswith(".jsonl"):
            for line in open(out / name, encoding="utf-8"):
                rec = json.loads(line)
                chunk_of.setdefault(rec["source"], set()).add((name, rec["id"].split("_", 1)[0]))
    assert all(len(v) == 1 for v in chunk_of.values()), chunk_of
    # The query's page is ordered first, so it lands in the first chunk.
    assert chunk_of["fixture/api/Color.html"] == {("docs_chunk_01.jsonl", "01")}


def test_delta_gate_still_works_per_page(tmp_path):
    src, out = _corpus(tmp_path), tmp_path / "out"
    args = [str(src), "-o", str(out), "--format", "jsonl", "--api-records", "--delta"]
    assert _pack(*args).exit_code == 0
    again = _pack(*args)
    assert again.exit_code == 0
    assert "Nothing to do" in again.output


def test_cross_refs_and_score_annotate_each_record(tmp_path):
    src, out = _corpus(tmp_path), tmp_path / "out"
    result = _pack(str(src), "-o", str(out), "--format", "jsonl", "--api-records",
                   "--cross-refs", "--score")
    assert result.exit_code == 0, result.output
    box = {r["id"]: r for r in _jsonl(out)}["01_fixture/api/Box.html"]
    assert "Storage [-> docs_chunk_01]" in box["content"]
    assert box["readiness_grade"] in ("A", "B", "C")
    assert (out / "cross_refs.json").exists() and (out / "llm-readiness.json").exists()


def test_serve_finds_the_member_record(tmp_path):
    src, out = _corpus(tmp_path), tmp_path / "out"
    assert _pack(str(src), "-o", str(out), "--format", "jsonl", "--api-records").exit_code == 0
    chunks = load_chunks(str(out))
    tools = {t.name: t for t in build_tools(chunks, build_index(chunks), {}, {}, "docs_chunk_")}
    hits = tools["search_chunks"].handler({"query": "Box load InputStream", "k": 3})["results"]
    assert hits[0]["id"] == "01_fixture/api/Box.html#load(java.io.InputStream,int)"


@pytest.mark.parametrize("args, message", [
    ([], "--api-records writes JSONL records; it needs --format jsonl, not --format md"),
    (["--format", "txt"], "it needs --format jsonl, not --format txt"),
    (["--format", "jsonl", "--bundle", "notebooklm"], "--api-records cannot be combined with --bundle notebooklm"),
    (["--layout", "page"], "--api-records writes JSONL records; it needs --layout chunk"),
    (["--layout", "page", "--format", "jsonl"], "--api-records writes JSONL records; it needs --layout chunk"),
])
def test_usage_errors(tmp_path, args, message):
    src = _corpus(tmp_path)
    result = CliRunner().invoke(cli, ["pack", str(src), "-o", str(tmp_path / "out"), "--api-records", *args])
    assert result.exit_code == 2, result.output
    assert message in result.output
    assert not (tmp_path / "out").exists()


def test_config_key_api_records(tmp_path):
    src, out = _corpus(tmp_path), tmp_path / "out"
    (tmp_path / ".dograpper.json").write_text(json.dumps({"pack": {"api_records": True}}))
    rejected = CliRunner().invoke(cli, ["pack", str(src), "-o", str(out)])
    assert rejected.exit_code == 2
    assert "--format jsonl" in rejected.output
    assert _pack(str(src), "-o", str(out), "--format", "jsonl").exit_code == 0
    assert any(r.get("symbol") == "fixture.api.Box" for r in _jsonl(out))


# ---------------------------------------------------------------------------
# --dedup never touches an API reference page, with or without --api-records (#68)
# ---------------------------------------------------------------------------

def _prose_corpus(tmp_path):
    src = tmp_path / "prose"
    src.mkdir()
    shared = " ".join(f"word{i}" for i in range(30))
    for name in ("a", "b"):
        (src / f"{name}.html").write_text(
            f"<html><body><h1>Page {name}</h1><p>unique {name} text here</p><p>{shared}</p></body></html>",
            encoding="utf-8")
    return src


def test_dedup_keeps_a_shared_member_on_every_javadoc_page(tmp_path):
    src, out = _corpus(tmp_path), tmp_path / "out"
    shutil.copytree(src / "fixture", src / "copy")
    result = _pack(str(src), "-o", str(out), "--format", "jsonl", "--dedup", "both")
    assert result.exit_code == 0, result.output
    by_id = {r["id"]: r for r in _jsonl(out)}
    assert by_id["01_copy/api/Box.html"]["content"].replace("copy", "fixture") == \
        by_id["01_fixture/api/Box.html"]["content"]
    assert "Words removed:     0 (~0%)" in result.output
    assert "Pages exempted:    14 (API reference)" in result.output


def test_dedup_leaves_a_non_api_corpus_unchanged(tmp_path):
    src, out = _prose_corpus(tmp_path), tmp_path / "out"
    result = _pack(str(src), "-o", str(out), "--format", "jsonl", "--dedup", "both")
    assert result.exit_code == 0, result.output
    assert "Blocks removed:    1 (1 exact + 0 fuzzy)" in result.output
    assert "Pages exempted:    0 (API reference)" in result.output


def test_dry_run_reports_exempted_pages(tmp_path):
    src, out = _corpus(tmp_path), tmp_path / "out"
    result = _pack(str(src), "-o", str(out), "--dry-run", "--dedup", "both")
    assert result.exit_code == 0, result.output
    assert "Dedup pages exempted:  " in result.output
# Sphinx autodoc
# ---------------------------------------------------------------------------

SPHINX = Path(__file__).parent / "fixtures" / "sphinx" / "html"


def _sphinx_page(name):
    return (SPHINX / name).read_text(encoding="utf-8")


def _sphinx_records(name):
    return {r.symbol: r for r in split_page(_sphinx_page(name))}


def test_sphinx_api_pages_are_split_and_prose_pages_kept_whole():
    split = split_api_pages(sorted(str(p) for p in SPHINX.iterdir()), str(SPHINX))
    assert sorted(split.records) == ["shapes.html", "tools.html"]
    assert split.kept_whole == [("index.html", "no supported generator")]


def test_sphinx_records_keep_page_order_with_the_module_first():
    assert [r.symbol for r in split_page(_sphinx_page("shapes.html"))] == [
        "fixture.shapes", "fixture.shapes.DEFAULT_NAME",
        "fixture.shapes.Shape", "fixture.shapes.Shape.sides", "fixture.shapes.Shape.name",
        "fixture.shapes.Shape.area",
        "fixture.shapes.Box", "fixture.shapes.Box.CAPACITY", "fixture.shapes.Box.Lid",
        "fixture.shapes.Box.Lid.is_closed", "fixture.shapes.Box.items", "fixture.shapes.Box.of",
        "fixture.shapes.Box.fits", "fixture.shapes.Box.size", "fixture.shapes.Box.put",
        "fixture.shapes.Box.map", "fixture.shapes.Box.shake",
        "fixture.shapes.Point", "fixture.shapes.Point.x", "fixture.shapes.Point.y",
        "fixture.shapes.Point.moved",
        "fixture.shapes.ShapeError", "fixture.shapes.BoxFullError",
        "fixture.shapes.apply", "fixture.shapes.scale",
    ]


def test_sphinx_module_container_record():
    module = split_page(_sphinx_page("shapes.html"))[0]
    assert (module.symbol, module.kind, module.symbol_kind) == ("fixture.shapes", "container", "module")
    assert (module.anchor, module.container, module.generator) == ("", "", "sphinx")
    assert module.breadcrumb == ["fixture.shapes"]
    assert module.text == "\n".join([
        "fixture.shapes (module)",
        "fixture.shapes",
        "Shapes and the boxes that store them.",
        "Typical use:",
        'box = Box.of("apple")',
        'box.put("pear")',
        "Data: DEFAULT_NAME",
        "Classes: Shape, Box, Point",
        "Exceptions: ShapeError, BoxFullError",
        "Functions: apply, scale",
    ])


def test_sphinx_class_container_record():
    box = _sphinx_records("shapes.html")["fixture.shapes.Box"]
    assert (box.kind, box.symbol_kind, box.anchor, box.container) == (
        "container", "class", "fixture.shapes.Box", "")
    assert box.breadcrumb == ["fixture.shapes.Box"]
    assert box.text == "\n".join([
        "fixture.shapes.Box (class)",
        "class fixture.shapes.Box(items: list[T] | None = None)",
        "Bases: Shape, Generic[T]",
        "A generic box that stores items in insertion order.",
        "Parameters:",
        "items – the first items",
        "Attributes: CAPACITY, items",
        "Classes: Lid",
        "Methods: of, fits, put, map, shake",
        "Properties: size",
    ])
    # A member's docstring lives on its member record only.
    assert "Store one item." not in box.text


def test_sphinx_nested_class_gets_its_own_container_record():
    recs = _sphinx_records("shapes.html")
    lid = recs["fixture.shapes.Box.Lid"]
    assert (lid.kind, lid.symbol_kind) == ("container", "class")
    assert lid.text == "\n".join([
        "fixture.shapes.Box.Lid (class)", "class Lid", "Bases: object", "The lid of a box.",
        "Methods: is_closed"])
    closed = recs["fixture.shapes.Box.Lid.is_closed"]
    assert closed.container == "fixture.shapes.Box.Lid"
    assert closed.breadcrumb == ["fixture.shapes.Box.Lid", "is_closed"]


def test_sphinx_exception_and_dataclass_containers():
    recs = _sphinx_records("shapes.html")
    error = recs["fixture.shapes.BoxFullError"]
    assert error.symbol_kind == "exception"
    assert error.text.split("\n")[:3] == [
        "fixture.shapes.BoxFullError (exception)",
        "exception fixture.shapes.BoxFullError(capacity: int)",
        "Bases: ShapeError",
    ]
    point = recs["fixture.shapes.Point"]
    assert point.text.split("\n")[1] == "class fixture.shapes.Point(x: int, y: int = 0)"
    assert "Attributes: x, y" in point.text.split("\n")
    assert recs["fixture.shapes.Point.y"].text == \
        "fixture.shapes.Point.y\ny: int = 0\nVertical position."


@pytest.mark.parametrize("symbol, symbol_kind, container, signature", [
    ("fixture.shapes.DEFAULT_NAME", "data", "fixture.shapes", "fixture.shapes.DEFAULT_NAME = 'shape'"),
    ("fixture.shapes.Shape.name", "property", "fixture.shapes.Shape", "property name: str"),
    ("fixture.shapes.Box.CAPACITY", "attribute", "fixture.shapes.Box", "CAPACITY: int = 16"),
    ("fixture.shapes.Box.of", "method", "fixture.shapes.Box", "classmethod of(*items: T) → Box[T]"),
    ("fixture.shapes.Box.fits", "method", "fixture.shapes.Box", "static fits(count: int) → bool"),
    ("fixture.shapes.Box.map", "method", "fixture.shapes.Box", "map(func: Callable[[T], U]) → Box[U]"),
    ("fixture.shapes.apply", "function", "fixture.shapes",
     "fixture.shapes.apply(func: Callable[[T], U], items: list[T]) → list[U]"),
])
def test_sphinx_member_kinds_and_signatures(symbol, symbol_kind, container, signature):
    rec = _sphinx_records("shapes.html")[symbol]
    assert (rec.kind, rec.symbol_kind, rec.container, rec.anchor) == ("member", symbol_kind, container, symbol)
    assert rec.breadcrumb == [container, symbol.rsplit(".", 1)[1]]
    assert rec.text.split("\n")[:2] == [symbol, signature]


def test_sphinx_member_record_holds_the_docstring_and_fields():
    put = _sphinx_records("shapes.html")["fixture.shapes.Box.put"]
    assert put.text == "\n".join([
        "fixture.shapes.Box.put",
        "put(item: T) → None",
        "Store one item.",
        "Parameters:",
        "item – the item to store",
        "Raises:",
        "BoxFullError – when the box already holds CAPACITY items",
    ])


def test_sphinx_undocumented_member_keeps_its_signature():
    recs = _sphinx_records("shapes.html")
    assert recs["fixture.shapes.Box.shake"].text == "fixture.shapes.Box.shake\nshake(times: int) → None"
    assert recs["fixture.shapes.Box.items"].text == "fixture.shapes.Box.items\nitems: list[T]"


def test_sphinx_overloads_keep_every_signature():
    assert _sphinx_records("shapes.html")["fixture.shapes.scale"].text == "\n".join([
        "fixture.shapes.scale",
        "fixture.shapes.scale(value: int, factor: int) → int",
        "fixture.shapes.scale(value: float, factor: float) → float",
        "Multiply value by factor, keeping its type.",
    ])


def test_sphinx_page_without_a_module_directive_names_its_module_from_the_objects():
    recs = split_page(_sphinx_page("tools.html"))
    assert [r.symbol for r in recs] == [
        "fixture.tools", "fixture.tools.Registry", "fixture.tools.Registry.get",
        "fixture.tools.Registry.register", "fixture.tools.first"]
    assert recs[0].text == "\n".join([
        "fixture.tools (module)", "Tools", "Helpers for registries.", "Registry", "Functions",
        "Classes: Registry", "Functions: first"])
    assert recs[2].text.split("\n")[1] == "get(key: K, default: V | None = None) → V | None"
    assert recs[3].text.split("\n")[1] == "register(key: K) → Callable[[V], V]"


def test_sphinx_record_url_carries_the_object_id():
    recs = _sphinx_records("shapes.html")
    page = "https://example.com/docs/shapes.html"
    assert recs["fixture.shapes"].url(page) == page
    assert recs["fixture.shapes.Box.put"].url(page) == page + "#fixture.shapes.Box.put"


@pytest.mark.parametrize("old, new, problem", [
    ('role="main"', 'role="article"', 'no role="main" element'),
    ('<dl class="py property">', '<dl class="py widget">', "unknown object type py widget"),
    ('<dt class="sig sig-object py" id="fixture.shapes.Box.put">', '<dt class="sig sig-object py">',
     "an object without an id"),
    ('id="fixture.shapes.Box.map"', 'id="fixture.shapes.Box.put"', "duplicate object id"),
    ('<span class="sig-name descname"><span class="pre">put</span></span>', "put",
     "a signature without a sig-name"),
])
def test_a_sphinx_page_with_other_markup_is_not_split(old, new, problem):
    page = _sphinx_page("shapes.html")
    assert old in page
    with pytest.raises(NotSplit, match=f"unsupported Sphinx markup: .*{problem}"):
        split_page(page.replace(old, new, 1))


def test_sphinx_parsing_stays_linear_on_hostile_markup():
    n = 20000

    def obj(i):
        return (f'<dl class="py function"><dt class="sig sig-object py" id="m.f{i}">'
                f'<span class="sig-name descname">f{i}</span></dt></dl>')
    # Deep unclosed nesting, stray end tags, nested name spans; and (separately) many objects.
    def hostile(deep, members):
        return ('<div role="main"><p>' + "<b>" * deep + "</i>" * deep + "</p>" * deep
                + '<dl class="py class"><dt class="sig sig-object py" id="m.C">'
                + '<span class="sig-name descname">' * max(deep, 1) + "C" + "</span>" * max(deep, 1) + "</dt><dd>"
                + "".join(obj(i) for i in range(members)))

    def run(page):
        assert len(split_page(page)) == page.count('<dl class="py function">') + 2
    assert_linear(lambda n: hostile(n, 0), run, n=NEST)
    assert_linear(lambda n: hostile(0, n), run, n=MEMBERS)
    with pytest.raises(NotSplit):
        split_page('<div role="main">' + '<dl class="py class"><dt class="sig sig-object py">' * n)
    # A chain of unclosed nested objects: each name repeats its ancestors', so output would be quadratic.
    def chain(n):
        return '<div role="main">' + "".join(
            f'<dl class="py class"><dt class="sig sig-object py" id="m.c{i}">'
            f'<span class="sig-prename descclassname">m.</span>'
            f'<span class="sig-name descname">c</span></dt><dd>' for i in range(n))

    def run_chain(page):
        with pytest.raises(NotSplit, match="a qualified name over 1000 characters"):
            split_page(page)
    assert_linear(chain, run_chain, n=4000)  # ~0.1 s at n: big enough to dwarf CI jitter


def _sphinx_corpus(tmp_path):
    src = tmp_path / "docs"
    shutil.copytree(SPHINX, src)
    return src


def test_pack_writes_sphinx_records(tmp_path):
    src, out = _sphinx_corpus(tmp_path), tmp_path / "out"
    result = _pack(str(src), "-o", str(out), "--format", "jsonl", "--api-records")
    assert result.exit_code == 0, result.output
    by_id = {r["id"]: r for r in _jsonl(out)}
    module = by_id["01_shapes.html"]
    assert {k: module[k] for k in ("symbol", "kind", "symbol_kind", "generator", "breadcrumb")} == {
        "symbol": "fixture.shapes", "kind": "container", "symbol_kind": "module",
        "generator": "sphinx", "breadcrumb": ["fixture.shapes"]}
    put = by_id["01_shapes.html#fixture.shapes.Box.put"]
    assert (put["kind"], put["symbol_kind"], put["container"], put["breadcrumb"]) == (
        "member", "method", "fixture.shapes.Box", ["fixture.shapes.Box", "put"])
    assert put["words"] == len(put["content"].split())
    assert "symbol" not in by_id["01_index.html"]
    assert "index.html: no supported generator" in result.stderr
    assert "API records:     2 pages split into 30 records (9 container, 21 member), 1 pages kept whole" \
        in result.output


def test_serve_finds_the_sphinx_member_record(tmp_path):
    src, out = _sphinx_corpus(tmp_path), tmp_path / "out"
    assert _pack(str(src), "-o", str(out), "--format", "jsonl", "--api-records").exit_code == 0
    chunks = load_chunks(str(out))
    tools = {t.name: t for t in build_tools(chunks, build_index(chunks), {}, {}, "docs_chunk_")}
    hits = tools["search_chunks"].handler({"query": "Box put item", "k": 3})["results"]
    assert hits[0]["id"] == "01_shapes.html#fixture.shapes.Box.put"
