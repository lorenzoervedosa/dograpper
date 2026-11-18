"""Tests for heading extraction and context header injection."""

import os
import tempfile

from click.testing import CliRunner

from dograpper.utils.heading_extractor import (
    extract_with_headings,
    get_active_headings,
    format_context_header,
    Heading,
    ExtractedDocument,
)
from dograpper.commands.pack import pack


# ---------------------------------------------------------------------------
# extract_with_headings
# ---------------------------------------------------------------------------

class TestExtractWithHeadings:

    def test_extracts_text_and_headings(self):
        html = """
        <html><body>
            <h1>Title</h1>
            <p>Introduction paragraph.</p>
            <h2>Section One</h2>
            <p>Content of section one.</p>
            <h3>Subsection A</h3>
            <p>Details of subsection A.</p>
        </body></html>
        """
        doc = extract_with_headings(html, source_path="test.html")

        assert "Introduction paragraph" in doc.text
        assert "Content of section one" in doc.text
        assert doc.source_path == "test.html"
        assert len(doc.headings) == 3
        assert doc.headings[0].level == 1
        assert doc.headings[0].text == "Title"
        assert doc.headings[1].level == 2
        assert doc.headings[1].text == "Section One"
        assert doc.headings[2].level == 3
        assert doc.headings[2].text == "Subsection A"

    def test_heading_order_preserved(self):
        html = """
        <h2>Second</h2><p>Text.</p>
        <h1>First</h1><p>Text.</p>
        <h3>Third</h3><p>Text.</p>
        """
        doc = extract_with_headings(html)
        levels = [h.level for h in doc.headings]
        assert levels == [2, 1, 3]

    def test_heading_offsets_increase(self):
        html = """
        <h1>A</h1><p>Some text here.</p>
        <h2>B</h2><p>More text here.</p>
        <h3>C</h3><p>Even more text.</p>
        """
        doc = extract_with_headings(html)
        offsets = [h.char_offset for h in doc.headings]
        assert offsets == sorted(offsets)
        assert len(set(offsets)) == len(offsets)

    def test_skips_script_style(self):
        html = """
        <h1>Title</h1>
        <script>var x = 1;</script>
        <style>.foo { color: red; }</style>
        <p>Real content.</p>
        """
        doc = extract_with_headings(html)
        assert "var x" not in doc.text
        assert "color" not in doc.text
        assert "Real content" in doc.text
        assert len(doc.headings) == 1

    def test_empty_heading_ignored(self):
        html = "<h1></h1><h2>Real Heading</h2><p>Content.</p>"
        doc = extract_with_headings(html)
        assert len(doc.headings) == 1
        assert doc.headings[0].text == "Real Heading"

    def test_nested_tags_in_heading(self):
        html = '<h2>Using <code>flask.run()</code> in Production</h2><p>Details.</p>'
        doc = extract_with_headings(html)
        assert len(doc.headings) == 1
        assert doc.headings[0].text == "Using flask.run() in Production"

    def test_block_tags_produce_newlines(self):
        html = "<p>First paragraph.</p><p>Second paragraph.</p>"
        doc = extract_with_headings(html)
        assert "\n\n" in doc.text

    def test_source_path_stored(self):
        doc = extract_with_headings("<p>text</p>", source_path="docs/api.html")
        assert doc.source_path == "docs/api.html"

    def test_pre_is_fenced_verbatim_like_strip_html(self):
        html = ('<h1>Events</h1><div class="mw-highlight mw-highlight-lang-lua">'
                '<pre>if x then\n\n    print(x)\nend</pre></div><p>After.</p>')
        doc = extract_with_headings(html)
        assert doc.text == "Events\n\n```lua\nif x then\n\n    print(x)\nend\n```\n\nAfter."

    def test_unclosed_pre_keeps_its_text(self):
        doc = extract_with_headings("<h1>T</h1><pre>a\n  b")
        assert doc.text == "T\n\n```\na\n  b\n```"

    def test_empty_html(self):
        doc = extract_with_headings("")
        assert doc.text == ""
        assert doc.headings == []

    def test_no_headings(self):
        html = "<p>Just a paragraph.</p><p>Another one.</p>"
        doc = extract_with_headings(html)
        assert doc.headings == []
        assert "Just a paragraph" in doc.text

    def test_malformed_html(self):
        html = "<h1>Unclosed heading<p>Paragraph<h2>Another"
        doc = extract_with_headings(html)
        assert isinstance(doc.text, str)
        assert isinstance(doc.headings, list)


# ---------------------------------------------------------------------------
# get_active_headings
# ---------------------------------------------------------------------------

class TestGetActiveHeadings:

    def _make_headings(self):
        return [
            Heading(level=1, text="Guide", char_offset=0),
            Heading(level=2, text="Installation", char_offset=100),
            Heading(level=3, text="Requirements", char_offset=200),
            Heading(level=3, text="Steps", char_offset=400),
            Heading(level=2, text="Configuration", char_offset=600),
            Heading(level=3, text="Database", char_offset=700),
        ]

    def test_at_beginning(self):
        headings = self._make_headings()
        active = get_active_headings(headings, char_offset=50)
        assert len(active) == 1
        assert active[0].text == "Guide"

    def test_at_h2(self):
        headings = self._make_headings()
        active = get_active_headings(headings, char_offset=150)
        assert len(active) == 2
        assert active[0].text == "Guide"
        assert active[1].text == "Installation"

    def test_at_h3(self):
        headings = self._make_headings()
        active = get_active_headings(headings, char_offset=250)
        assert len(active) == 3
        assert active[0].text == "Guide"
        assert active[1].text == "Installation"
        assert active[2].text == "Requirements"

    def test_new_h3_replaces_previous(self):
        headings = self._make_headings()
        active = get_active_headings(headings, char_offset=450)
        assert len(active) == 3
        assert active[2].text == "Steps"

    def test_new_h2_invalidates_h3(self):
        headings = self._make_headings()
        active = get_active_headings(headings, char_offset=650)
        assert len(active) == 2
        assert active[0].text == "Guide"
        assert active[1].text == "Configuration"

    def test_h3_after_new_h2(self):
        headings = self._make_headings()
        active = get_active_headings(headings, char_offset=750)
        assert len(active) == 3
        assert active[0].text == "Guide"
        assert active[1].text == "Configuration"
        assert active[2].text == "Database"

    def test_empty_headings(self):
        assert get_active_headings([], char_offset=100) == []

    def test_offset_before_any_heading(self):
        headings = [Heading(level=1, text="Title", char_offset=500)]
        active = get_active_headings(headings, char_offset=100)
        assert active == []

    def test_exact_offset_match(self):
        headings = [Heading(level=1, text="Title", char_offset=100)]
        active = get_active_headings(headings, char_offset=100)
        assert len(active) == 1
        assert active[0].text == "Title"


# ---------------------------------------------------------------------------
# format_context_header
# ---------------------------------------------------------------------------

class TestFormatContextHeader:

    def _parse_v1(self, header):
        """Extract and parse JSON from a dograpper-context-v1 header."""
        import json
        json_str = header.split("<!-- dograpper-context-v1\n")[1].split("\n-->")[0]
        return json.loads(json_str)

    def test_full_header(self):
        headings = [
            Heading(level=1, text="Guide", char_offset=0),
            Heading(level=2, text="Installation", char_offset=100),
        ]
        header = format_context_header(
            active_headings=headings,
            source_path="docs/guide/install.html",
            chunk_index=2,
            total_chunks=5,
        )
        assert "<!-- dograpper-context-v1" in header
        assert header.endswith("\n\n")
        data = self._parse_v1(header)
        assert data["source"] == "docs/guide/install.html"
        assert data["context_breadcrumb"] == ["Guide", "Installation"]
        assert data["chunk_index"] == 2
        assert data["total_chunks"] == 5
        assert data["schema_version"] == "v1"

    def test_single_chunk_no_position(self):
        header = format_context_header(
            active_headings=[Heading(1, "Title", 0)],
            source_path="doc.html",
            chunk_index=1,
            total_chunks=1,
        )
        data = self._parse_v1(header)
        assert data["source"] == "doc.html"
        assert data["context_breadcrumb"] == ["Title"]
        assert "chunk_index" not in data
        assert "total_chunks" not in data

    def test_no_headings(self):
        header = format_context_header(
            active_headings=[],
            source_path="genindex.html",
        )
        data = self._parse_v1(header)
        assert data["source"] == "genindex.html"
        assert "context_breadcrumb" not in data

    def test_no_source_path(self):
        header = format_context_header(
            active_headings=[Heading(1, "Title", 0)],
            source_path="",
        )
        data = self._parse_v1(header)
        assert "source" not in data
        assert data["context_breadcrumb"] == ["Title"]

    def test_empty_returns_empty(self):
        header = format_context_header(
            active_headings=[],
            source_path="",
        )
        assert header == ""

    def test_deep_hierarchy(self):
        headings = [
            Heading(1, "Docs", 0),
            Heading(2, "API", 50),
            Heading(3, "Auth", 100),
            Heading(4, "OAuth2", 150),
        ]
        header = format_context_header(active_headings=headings)
        data = self._parse_v1(header)
        assert data["context_breadcrumb"] == ["Docs", "API", "Auth", "OAuth2"]

    def test_unicode_in_headings(self):
        headings = [Heading(1, "Configuração", 0), Heading(2, "Opções básicas", 50)]
        header = format_context_header(active_headings=headings, source_path="config.html")
        data = self._parse_v1(header)
        assert data["context_breadcrumb"] == ["Configuração", "Opções básicas"]


# ---------------------------------------------------------------------------
# CLI integration
# ---------------------------------------------------------------------------

class TestContextHeaderCLI:

    def _create_html_files(self, tmp_dir):
        input_dir = os.path.join(tmp_dir, "input")
        os.makedirs(input_dir)
        with open(os.path.join(input_dir, "guide.html"), "w") as f:
            f.write("""
            <html><body><main>
                <h1>User Guide</h1>
                <p>Welcome to the user guide with enough words for chunking purposes here.</p>
                <h2>Installation</h2>
                <p>To install the package, run pip install mypackage in your terminal now.</p>
                <h2>Configuration</h2>
                <p>Configuration is done via the config file located in your home directory path.</p>
            </main></body></html>
            """)
        return input_dir

    def test_context_header_injected(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = self._create_html_files(tmp)
            output_dir = os.path.join(tmp, "output")

            runner = CliRunner()
            result = runner.invoke(pack, [
                input_dir, "-o", output_dir, "--context-header",
            ])

            assert result.exit_code == 0
            chunks = os.listdir(output_dir)
            assert len(chunks) >= 1
            with open(os.path.join(output_dir, chunks[0])) as f:
                content = f.read()
            assert "dograpper-context-v1" in content
            assert '"source"' in content

    def test_without_context_header_no_injection(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = self._create_html_files(tmp)
            output_dir = os.path.join(tmp, "output")

            runner = CliRunner()
            result = runner.invoke(pack, [
                input_dir, "-o", output_dir,
            ])

            assert result.exit_code == 0
            chunks = os.listdir(output_dir)
            with open(os.path.join(output_dir, chunks[0])) as f:
                content = f.read()
            assert "dograpper-context-v1" not in content

    def test_context_header_contains_breadcrumb(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = self._create_html_files(tmp)
            output_dir = os.path.join(tmp, "output")

            runner = CliRunner()
            result = runner.invoke(pack, [
                input_dir, "-o", output_dir, "--context-header",
            ])

            assert result.exit_code == 0
            chunks = os.listdir(output_dir)
            with open(os.path.join(output_dir, chunks[0])) as f:
                content = f.read()
            assert "User Guide" in content
            assert "dograpper-context-v1" in content

    def test_context_header_with_txt_format(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = self._create_html_files(tmp)
            output_dir = os.path.join(tmp, "output")

            runner = CliRunner()
            result = runner.invoke(pack, [
                input_dir, "-o", output_dir, "--context-header", "--format", "txt",
            ])

            assert result.exit_code == 0
            chunks = [f for f in os.listdir(output_dir) if f.endswith('.txt')]
            assert len(chunks) >= 1
            with open(os.path.join(output_dir, chunks[0])) as f:
                content = f.read()
            assert "dograpper-context-v1" in content

    def test_xml_format_deprecated(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = self._create_html_files(tmp)
            output_dir = os.path.join(tmp, "output")

            runner = CliRunner()
            result = runner.invoke(pack, [
                input_dir, "-o", output_dir, "--context-header", "--format", "xml",
            ])

            assert result.exit_code != 0
            assert "deprecated" in result.output.lower() or "deprecated" in str(result.exception).lower()

    def test_non_html_file_source_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = os.path.join(tmp, "input")
            os.makedirs(input_dir)
            with open(os.path.join(input_dir, "readme.txt"), "w") as f:
                f.write("This is a plain text file with enough words for testing purposes.")
            output_dir = os.path.join(tmp, "output")

            runner = CliRunner()
            result = runner.invoke(pack, [
                input_dir, "-o", output_dir, "--context-header",
            ])

            assert result.exit_code == 0
            chunks = os.listdir(output_dir)
            with open(os.path.join(output_dir, chunks[0])) as f:
                content = f.read()
            assert "dograpper-context-v1" in content
            assert '"source": "readme.txt"' in content
            assert "context_breadcrumb" not in content

    def test_regression_pack_without_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = self._create_html_files(tmp)
            output_dir = os.path.join(tmp, "output")

            runner = CliRunner()
            result = runner.invoke(pack, [
                input_dir, "-o", output_dir,
            ])

            assert result.exit_code == 0
            assert os.path.exists(output_dir)
            chunks = os.listdir(output_dir)
            assert len(chunks) > 0
            for chunk_name in chunks:
                with open(os.path.join(output_dir, chunk_name)) as f:
                    content = f.read()
                assert "dograpper-context-v1" not in content

    def test_context_header_with_dedup(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = os.path.join(tmp, "input")
            os.makedirs(input_dir)
            shared = "This block of documentation text appears across multiple pages with enough words to pass dedup threshold."
            with open(os.path.join(input_dir, "page_a.html"), "w") as f:
                f.write(f"<html><body><h1>Page A</h1><p>Unique content for page A here.</p><p>{shared}</p></body></html>")
            with open(os.path.join(input_dir, "page_b.html"), "w") as f:
                f.write(f"<html><body><h1>Page B</h1><p>Unique content for page B here.</p><p>{shared}</p></body></html>")
            output_dir = os.path.join(tmp, "output")

            runner = CliRunner()
            result = runner.invoke(pack, [
                input_dir, "-o", output_dir, "--context-header", "--dedup", "exact",
            ])

            assert result.exit_code == 0

    def test_context_header_with_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = self._create_html_files(tmp)

            runner = CliRunner()
            result = runner.invoke(pack, [
                input_dir, "-o", os.path.join(tmp, "out"),
                "--context-header", "--dry-run",
            ])

            assert result.exit_code == 0
            assert not os.path.exists(os.path.join(tmp, "out"))
