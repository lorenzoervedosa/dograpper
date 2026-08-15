"""Tests for cross-reference link extraction and indexing."""

import json
import os
import tempfile

from click.testing import CliRunner

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


def test_regex_special_chars_in_link_text_escaped():
    """Link text containing regex-special characters is treated literally."""
    text = "See C++ (advanced) for details."
    links = [LinkRef("a.html", "cpp.html", "", "C++ (advanced)")]
    file_to_chunk = {"cpp.html": "docs_chunk_01"}

    result = annotate_cross_refs(text, links, file_to_chunk)
    assert "C++ (advanced) [-> docs_chunk_01]" in result


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
