"""Tests for cross-reference link extraction and indexing."""

import json
import os
import re
import tempfile
from types import SimpleNamespace

import pytest
from click.testing import CliRunner

from dograpper.utils import link_extractor
from dograpper.utils.link_extractor import (
    LinkRef,
    extract_links,
    build_cross_ref_index,
    annotate_cross_refs,
)
from dograpper.commands.pack import pack


# ---------------------------------------------------------------------------
# extract_links tests
# ---------------------------------------------------------------------------

def test_simple_relative_links():
    """Simple relative links resolve correctly."""
    html = '<a href="other.html">Other Page</a>'
    links = extract_links(html, "docs/page.html")
    assert len(links) == 1
    assert links[0].target_path == "docs/other.html"
    assert links[0].link_text == "Other Page"
    assert links[0].source_path == "docs/page.html"


def test_links_with_dotdot():
    """Links with .. resolve correctly."""
    html = '<a href="../sibling/page.html">Sibling</a>'
    links = extract_links(html, "docs/sub/page.html")
    assert len(links) == 1
    assert links[0].target_path == "docs/sibling/page.html"


def test_links_with_fragment():
    """Links with #fragment separate path and anchor."""
    html = '<a href="routing.html#advanced">Advanced Routing</a>'
    links = extract_links(html, "docs/page.html")
    assert len(links) == 1
    assert links[0].target_path == "docs/routing.html"
    assert links[0].anchor == "#advanced"
    assert links[0].link_text == "Advanced Routing"


def test_external_links_discarded():
    """External links (https://) are discarded."""
    html = """
    <a href="https://example.com">External</a>
    <a href="http://example.com">HTTP</a>
    <a href="local.html">Local</a>
    """
    links = extract_links(html, "page.html")
    assert len(links) == 1
    assert links[0].target_path == "local.html"


def test_mailto_javascript_discarded():
    """mailto and javascript links are discarded."""
    html = """
    <a href="mailto:test@example.com">Email</a>
    <a href="javascript:void(0)">Click</a>
    <a href="real.html">Real</a>
    """
    links = extract_links(html, "page.html")
    assert len(links) == 1
    assert links[0].target_path == "real.html"


def test_index_html_normalized():
    """Links with index.html are normalized."""
    html = '<a href="subdir/index.html">Sub</a>'
    links = extract_links(html, "page.html")
    assert len(links) == 1
    assert links[0].target_path == "subdir"


def test_no_links_empty_list():
    """HTML without links returns empty list."""
    html = "<p>No links here</p>"
    links = extract_links(html, "page.html")
    assert links == []


def test_links_with_empty_text():
    """Links with empty text are still extracted."""
    html = '<a href="target.html"></a>'
    links = extract_links(html, "page.html")
    assert len(links) == 1
    assert links[0].link_text == ""
    assert links[0].target_path == "target.html"


def test_pure_fragment_links_discarded():
    """Pure fragment links (#something) are discarded."""
    html = '<a href="#section">Jump</a>'
    links = extract_links(html, "page.html")
    assert links == []


def test_dotslash_normalized():
    """Links starting with ./ are normalized."""
    html = '<a href="./other.html">Other</a>'
    links = extract_links(html, "docs/page.html")
    assert len(links) == 1
    assert links[0].target_path == "docs/other.html"


# ---------------------------------------------------------------------------
# build_cross_ref_index tests
# ---------------------------------------------------------------------------

def test_correct_chunk_mapping():
    """Correct chunk -> references_to / referenced_by mapping."""
    links = [
        LinkRef("a.html", "b.html", "", "See B"),
        LinkRef("b.html", "a.html", "#top", "Back to A"),
    ]
    file_to_chunk = {"a.html": "docs_chunk_01", "b.html": "docs_chunk_02"}
    index = build_cross_ref_index(links, file_to_chunk)

    assert "docs_chunk_02" in index["docs_chunk_01"]["references_to"]
    assert "docs_chunk_01" in index["docs_chunk_02"]["references_to"]
    assert "docs_chunk_02" in index["docs_chunk_01"]["referenced_by"]
    assert "docs_chunk_01" in index["docs_chunk_02"]["referenced_by"]


def test_unresolved_links():
    """Links to files outside pack go in 'unresolved'."""
    links = [
        LinkRef("a.html", "missing.html", "", "Gone"),
    ]
    file_to_chunk = {"a.html": "docs_chunk_01"}
    index = build_cross_ref_index(links, file_to_chunk)

    assert len(index["unresolved"]) == 1
    assert index["unresolved"][0]["target_file"] == "missing.html"


def test_no_links_empty_structure():
    """No links returns empty dict structure."""
    index = build_cross_ref_index([], {})
    assert index == {"unresolved": []}


def test_self_references_included():
    """Self-references (same chunk) are included."""
    links = [
        LinkRef("a.html", "b.html", "", "See B"),
    ]
    # Both files in the same chunk
    file_to_chunk = {"a.html": "docs_chunk_01", "b.html": "docs_chunk_01"}
    index = build_cross_ref_index(links, file_to_chunk)

    entry = index["docs_chunk_01"]
    assert "docs_chunk_01" in entry["references_to"]
    assert "docs_chunk_01" in entry["referenced_by"]


# ---------------------------------------------------------------------------
# annotate_cross_refs tests
# ---------------------------------------------------------------------------

def test_annotations_added():
    """Annotations added correctly."""
    text = "Click here to See Routing for more info."
    links = [LinkRef("a.html", "b.html", "#routing", "See Routing")]
    file_to_chunk = {"b.html": "docs_chunk_02"}

    result = annotate_cross_refs(text, links, file_to_chunk)
    assert "See Routing [-> docs_chunk_02]" in result


def test_only_first_occurrence_annotated():
    """Only first occurrence annotated."""
    text = "See Routing here. Also See Routing there."
    links = [LinkRef("a.html", "b.html", "", "See Routing")]
    file_to_chunk = {"b.html": "docs_chunk_02"}

    result = annotate_cross_refs(text, links, file_to_chunk)
    assert result.count("[-> docs_chunk_02]") == 1


def test_unresolved_links_not_annotated():
    """Unresolved links not annotated."""
    text = "See Missing Page for details."
    links = [LinkRef("a.html", "missing.html", "", "Missing Page")]
    file_to_chunk = {}  # nothing maps

    result = annotate_cross_refs(text, links, file_to_chunk)
    assert "[-> " not in result
    assert result == text


def test_substring_link_text_does_not_corrupt_word():
    """Link text that is a substring of an unrelated word is not annotated
    mid-word (e.g. "Install" must not match inside "Installation")."""
    text = "Installation Widgetize ships as a single self contained binary."
    links = [LinkRef("a.html", "install.html", "", "Install")]
    file_to_chunk = {"install.html": "docs_chunk_01"}

    result = annotate_cross_refs(text, links, file_to_chunk)
    assert "Install [-> docs_chunk_01]ation" not in result
    assert "Installation" in result
    assert "[-> docs_chunk_01]" not in result


def test_word_boundary_link_text_still_annotated():
    """A whole-word occurrence of the link text is still annotated."""
    text = "Install the CLI before running any command."
    links = [LinkRef("a.html", "install.html", "", "Install")]
    file_to_chunk = {"install.html": "docs_chunk_01"}

    result = annotate_cross_refs(text, links, file_to_chunk)
    assert "Install [-> docs_chunk_01]" in result


def test_link_text_preceded_by_word_char_not_annotated():
    """The left boundary holds too: a word that merely ends in the link text
    is skipped and the next whole-word occurrence is annotated."""
    text = "ReInstall the tool, then Install it."
    links = [LinkRef("a.html", "install.html", "", "Install")]
    file_to_chunk = {"install.html": "docs_chunk_01"}

    result = annotate_cross_refs(text, links, file_to_chunk)
    assert result == "ReInstall the tool, then Install [-> docs_chunk_01] it."


def test_link_text_inside_dotted_identifier_not_annotated():
    """A marker never lands inside a dotted identifier (#67:
    "zombie.characters.AttachedItems [-> docs_chunk_01].AttachedItems"); a
    sentence-final period still ends the match."""
    fqn = "java.lang.Object zombie.characters.AttachedItems.AttachedItems"
    text = f"{fqn}\n\nRead AttachedItems."
    links = [LinkRef("a.html", "AttachedItems.html", "", "AttachedItems")]
    file_to_chunk = {"AttachedItems.html": "docs_chunk_01"}

    result = annotate_cross_refs(text, links, file_to_chunk)
    assert result == f"{fqn}\n\nRead AttachedItems [-> docs_chunk_01]."


def test_regex_special_chars_in_link_text_escaped():
    """Link text containing regex-special characters is treated literally."""
    text = "See C++ (advanced) for details."
    links = [LinkRef("a.html", "cpp.html", "", "C++ (advanced)")]
    file_to_chunk = {"cpp.html": "docs_chunk_01"}

    result = annotate_cross_refs(text, links, file_to_chunk)
    assert "C++ (advanced) [-> docs_chunk_01]" in result


def _annotate_one(text, link_text, target):
    link = LinkRef(source_path="a.html", target_path=target, anchor="", link_text=link_text)
    return annotate_cross_refs(text, [link], {target: "c1"})


@pytest.mark.parametrize("text,expected", [
    ("see [Item](Item.html) now", "see [Item](Item.html) [-> c1] now"),
    ("see [Item](<Item_(x).html>) now", "see [Item](<Item_(x).html>) [-> c1] now"),
    ("[docs](https://x.org/wiki/Item) and [Item](Item.html)",
     "[docs](https://x.org/wiki/Item) and [Item](Item.html) [-> c1]"),
    ("plain Item text", "plain Item [-> c1] text"),
])
def test_marker_follows_a_markdown_link_and_never_enters_its_destination(text, expected):
    assert _annotate_one(text, "Item", "Item.html") == expected


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

def _create_html_files(base_dir, file_specs):
    """Create HTML files for cross-ref testing.

    file_specs: list of (relative_path, html_content)
    """
    paths = []
    for rel_path, content in file_specs:
        full = os.path.join(base_dir, rel_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w') as f:
            f.write(content)
        paths.append(full)
    return paths


def test_cross_refs_generates_json():
    """--cross-refs generates cross_refs.json."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as d:
        input_dir = os.path.join(d, 'input')
        os.makedirs(input_dir)
        _create_html_files(input_dir, [
            ("a.html", '<html><body><p>Hello</p><a href="b.html">Go to B</a></body></html>'),
            ("b.html", '<html><body><p>World</p></body></html>'),
        ])

        output_dir = os.path.join(d, 'out')
        result = runner.invoke(pack, [input_dir, '-o', output_dir, '--cross-refs'])
        assert result.exit_code == 0

        cross_path = os.path.join(output_dir, 'cross_refs.json')
        assert os.path.exists(cross_path)


def test_no_cross_refs_no_json():
    """Without --cross-refs, no cross_refs.json."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as d:
        input_dir = os.path.join(d, 'input')
        os.makedirs(input_dir)
        _create_html_files(input_dir, [
            ("a.html", '<html><body><p>Hello</p><a href="b.html">Go to B</a></body></html>'),
            ("b.html", '<html><body><p>World</p></body></html>'),
        ])

        output_dir = os.path.join(d, 'out')
        result = runner.invoke(pack, [input_dir, '-o', output_dir])
        assert result.exit_code == 0

        cross_path = os.path.join(output_dir, 'cross_refs.json')
        assert not os.path.exists(cross_path)


def test_cross_refs_json_structure():
    """cross_refs.json has valid structure."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as d:
        input_dir = os.path.join(d, 'input')
        os.makedirs(input_dir)
        _create_html_files(input_dir, [
            ("a.html", '<html><body><main><p>Page A content here</p><a href="b.html">Go to B</a></main></body></html>'),
            ("b.html", '<html><body><main><p>Page B content here</p><a href="a.html">Back to A</a></main></body></html>'),
        ])

        output_dir = os.path.join(d, 'out')
        result = runner.invoke(pack, [input_dir, '-o', output_dir, '--cross-refs'])
        assert result.exit_code == 0

        cross_path = os.path.join(output_dir, 'cross_refs.json')
        with open(cross_path, 'r') as f:
            data = json.load(f)

        assert "unresolved" in data
        assert isinstance(data["unresolved"], list)

        # At least one chunk entry should exist with proper keys
        chunk_keys = [k for k in data if k != "unresolved"]
        if chunk_keys:
            entry = data[chunk_keys[0]]
            assert "references_to" in entry
            assert "referenced_by" in entry
            assert "links" in entry


def test_cross_refs_summary_line():
    """Summary shows cross-refs line."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as d:
        input_dir = os.path.join(d, 'input')
        os.makedirs(input_dir)
        _create_html_files(input_dir, [
            ("a.html", '<html><body><p>Hello</p><a href="b.html">Go to B</a></body></html>'),
            ("b.html", '<html><body><p>World</p></body></html>'),
        ])

        output_dir = os.path.join(d, 'out')
        result = runner.invoke(pack, [input_dir, '-o', output_dir, '--cross-refs'])
        assert result.exit_code == 0
        assert "Cross-refs:" in result.output
        assert "cross_refs.json" in result.output


# Issue #67 repro: the page that holds the link is not the first place its
# text appears in the chunk, and its text also appears in metadata ("Item.html").
_REPRO_PAGES = [
    ("Item.html", "<html><body><main><h1>Item</h1><p>The Item class represents "
                  "an inventory item with a weight and a name field.</p></main></body></html>"),
    ("z_guide.html", '<html><body><main><h1>Guide</h1><p>To pick something up, call '
                     'the getter on <a href="Item.html">Item</a> and check the weight '
                     'first.</p></main></body></html>'),
]


def _pack_repro(d, fmt, *extra):
    input_dir = os.path.join(d, 'input')
    os.makedirs(input_dir)
    _create_html_files(input_dir, _REPRO_PAGES)
    output_dir = os.path.join(d, 'out')
    result = CliRunner().invoke(
        pack, [input_dir, '-o', output_dir, '--format', fmt, '--cross-refs', *extra])
    assert result.exit_code == 0, result.output
    with open(os.path.join(output_dir, f'docs_chunk_01.{fmt}'), encoding='utf-8') as f:
        return f.read()


@pytest.mark.parametrize("extra", [(), ("--context-header",)])
def test_cross_refs_jsonl_annotates_only_the_linking_record(extra):
    """The marker goes into the content of the record that holds the link,
    never into id/source or another record (#67)."""
    with tempfile.TemporaryDirectory() as d:
        text = _pack_repro(d, 'jsonl', *extra)

    records = [json.loads(line) for line in text.splitlines()]
    assert [(r["id"], r["source"]) for r in records] == [
        ("01_Item.html", "Item.html"), ("01_z_guide.html", "z_guide.html")]
    item, guide = records
    assert "[-> " not in item["content"]
    assert "call the getter on Item [-> docs_chunk_01] and check" in guide["content"]
    assert text.count("[-> ") == 1


@pytest.mark.parametrize("fmt", ["md", "txt"])
@pytest.mark.parametrize("extra", [(), ("--context-header",)])
def test_cross_refs_text_formats_annotate_only_the_linking_page(fmt, extra):
    """md/txt: the file index, source separators and context headers stay
    intact; only the linking page's content gets the marker (#67)."""
    with tempfile.TemporaryDirectory() as d:
        text = _pack_repro(d, fmt, *extra)

    assert "- Item.html (15 words)" in text
    assert "call the getter on Item [-> docs_chunk_01] and check" in text
    assert text.count("[-> ") == 1


def test_cross_refs_compile_one_pattern_per_distinct_link_text(monkeypatch):
    """Hundreds of pages sharing link texts compile one pattern per distinct
    text, not one per link per record (#67: a ~1,900-page corpus did not
    finish in 10 minutes)."""
    compiled = []

    def counting_compile(pattern, *args):
        compiled.append(pattern)
        return re.compile(pattern, *args)

    monkeypatch.setattr(link_extractor, "re",
                        SimpleNamespace(compile=counting_compile, escape=re.escape))

    n_pages, n_targets, links_per_page = 300, 20, 5
    specs = [(f"t{t:02d}.html", f"<html><body><main><p>Target{t:02d} body</p></main></body></html>")
             for t in range(n_targets)]
    for i in range(n_pages):
        targets = [(i + j) % n_targets for j in range(links_per_page)]
        links = " ".join(f'<a href="t{t:02d}.html">Target{t:02d}</a>' for t in targets)
        specs.append((f"p{i:03d}.html", f"<html><body><main><p>Page {i} links {links}</p></main></body></html>"))

    with tempfile.TemporaryDirectory() as d:
        input_dir = os.path.join(d, 'input')
        os.makedirs(input_dir)
        _create_html_files(input_dir, specs)
        output_dir = os.path.join(d, 'out')
        result = CliRunner().invoke(pack, [input_dir, '-o', output_dir, '--format', 'jsonl',
                                           '--cross-refs', '--max-words-per-chunk', '200'])
        assert result.exit_code == 0, result.output

        records = []
        for name in sorted(os.listdir(output_dir)):
            if name.endswith('.jsonl'):
                with open(os.path.join(output_dir, name), encoding='utf-8') as f:
                    records.extend(json.loads(line) for line in f)

    pages = [r for r in records if r["source"].startswith("p")]
    assert len(pages) == n_pages
    assert all(r["content"].count("[-> ") == links_per_page for r in pages)
    assert len(compiled) <= n_targets
