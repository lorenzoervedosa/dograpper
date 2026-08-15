"""Tests for the intelligent content extractor."""

import os
import tempfile
from click.testing import CliRunner

from dograpper.utils.content_extractor import extract_content, _matches_class
from dograpper.utils.html_stripper import strip_html
from dograpper.cli import cli


# ---------------------------------------------------------------------------
# Semantic container tests
# ---------------------------------------------------------------------------

def test_extracts_main_tag():
    """Content inside <main> is extracted, boilerplate outside is discarded."""
    html = """
    <html><body>
        <nav><a href="/">Home</a><a href="/docs">Docs</a></nav>
        <main>
            <h1>Installation</h1>
            <p>Run pip install mylib to get started.</p>
        </main>
        <footer>Copyright 2025</footer>
    </body></html>
    """
    result = extract_content(html)
    assert "Installation" in result
    assert "pip install" in result
    assert "Home" not in result
    assert "Copyright" not in result


def test_extracts_article_tag():
    """If no <main>, use <article>."""
    html = """
    <html><body>
        <div class="sidebar-nav">Menu lateral</div>
        <article>
            <h1>Getting Started</h1>
            <p>This guide covers the basics.</p>
        </article>
    </body></html>
    """
    result = extract_content(html)
    assert "Getting Started" in result
    assert "Menu lateral" not in result


def test_extracts_div_role_main():
    """Div with role='main' has priority over article."""
    html = """
    <html><body>
        <div role="main">
            <p>Conteúdo principal via role.</p>
        </div>
        <article>
            <p>Article secundário.</p>
        </article>
    </body></html>
    """
    result = extract_content(html)
    assert "Conteúdo principal via role" in result


def test_extracts_div_with_known_id():
    """Div with id='content' is recognized as container."""
    html = """
    <html><body>
        <nav>Nav</nav>
        <div id="content">
            <h2>API Reference</h2>
            <p>Detalhes da API aqui.</p>
        </div>
        <footer>Footer</footer>
    </body></html>
    """
    result = extract_content(html)
    assert "API Reference" in result
    assert "Nav" not in result


def test_extracts_div_with_known_class():
    """Div with class='markdown-body' (GitHub-style) is recognized."""
    html = """
    <html><body>
        <div class="markdown-body">
            <h1>README</h1>
            <p>Project description.</p>
        </div>
    </body></html>
    """
    result = extract_content(html)
    assert "README" in result


def test_priority_main_over_article():
    """<main> has priority over <article> when both exist."""
    html = """
    <html><body>
        <main><p>Conteúdo do main.</p></main>
        <article><p>Conteúdo do article.</p></article>
    </body></html>
    """
    result = extract_content(html)
    assert "Conteúdo do main" in result


def test_priority_main_over_article_reversed_order():
    """<main> wins even when <article> appears first in document order."""
    html = """
    <html><body>
        <article><p>Article first.</p></article>
        <main><p>Main second.</p></main>
    </body></html>
    """
    result = extract_content(html)
    assert "Main second" in result


# ---------------------------------------------------------------------------
# Density scoring tests
# ---------------------------------------------------------------------------

def test_density_fallback_when_no_semantic_container():
    """Without semantic tags, the block with most text wins."""
    html = """
    <html><body>
        <div class="menu">
            <a href="/a">Link A</a>
            <a href="/b">Link B</a>
            <a href="/c">Link C</a>
        </div>
        <div class="unknown-wrapper">
            <h1>Documentação Completa</h1>
            <p>Este é o conteúdo principal com bastante texto para
            garantir que o scoring identifique este bloco como o
            mais relevante da página. Inclui parágrafos, exemplos
            e explicações detalhadas sobre o funcionamento da lib.</p>
            <p>Segundo parágrafo com ainda mais conteúdo textual
            para aumentar o word count e o score deste bloco.</p>
        </div>
        <div class="footer-links">
            <a href="/terms">Terms</a>
            <a href="/privacy">Privacy</a>
        </div>
    </body></html>
    """
    result = extract_content(html)
    assert "Documentação Completa" in result
    assert "Link A" not in result


def test_density_penalizes_link_heavy_blocks():
    """Blocks with many links (disguised nav) are penalized."""
    html = """
    <html><body>
        <div>
            <a href="/1">L1</a><a href="/2">L2</a><a href="/3">L3</a>
            <a href="/4">L4</a><a href="/5">L5</a><a href="/6">L6</a>
            <a href="/7">L7</a><a href="/8">L8</a><a href="/9">L9</a>
            <a href="/10">L10</a>
            <p>Algum texto aqui mas poucos.</p>
        </div>
        <div>
            <p>Este bloco tem menos links e mais texto corrido que
            deveria ser considerado o conteúdo principal da página.
            Adicionamos bastante texto aqui para garantir que o score
            deste bloco supere o limiar mínimo de cinquenta palavras
            necessárias para que o bloco seja considerado válido pelo
            algoritmo de scoring por densidade de texto.</p>
        </div>
    </body></html>
    """
    result = extract_content(html)
    assert "conteúdo principal" in result


# ---------------------------------------------------------------------------
# Blacklist removal tests
# ---------------------------------------------------------------------------

def test_removes_nav_inside_main():
    """Even inside <main>, blacklisted elements are removed."""
    html = """
    <main>
        <nav class="breadcrumb"><a href="/">Home</a> &gt; Docs</nav>
        <h1>Title</h1>
        <p>Content here.</p>
    </main>
    """
    result = extract_content(html)
    assert "Title" in result
    assert "Content here" in result
    assert "breadcrumb" not in result.lower()
    assert "Home" not in result


def test_removes_sidebar_by_class():
    """Element with class containing 'sidebar' is removed."""
    html = """
    <main>
        <div class="docs-sidebar left-panel">
            <ul><li>Nav item 1</li><li>Nav item 2</li></ul>
        </div>
        <div class="doc-content">
            <p>Conteúdo real.</p>
        </div>
    </main>
    """
    result = extract_content(html)
    assert "Conteúdo real" in result
    assert "Nav item" not in result


def test_removes_footer_by_id():
    """Element with id in blacklist is removed."""
    html = """
    <main>
        <p>Conteúdo principal.</p>
        <div id="footer">
            <p>Copyright 2025 Acme Corp.</p>
        </div>
    </main>
    """
    result = extract_content(html)
    assert "Conteúdo principal" in result
    assert "Copyright" not in result


def test_removes_copy_button():
    """'Copy to clipboard' buttons are removed."""
    html = """
    <main>
        <pre><code>pip install dograpper</code></pre>
        <button class="copy-to-clipboard">Copy</button>
        <p>Install the package.</p>
    </main>
    """
    result = extract_content(html)
    assert "pip install" in result
    assert "Copy" not in result


def test_removes_version_banner():
    """Version selection banners are removed."""
    html = """
    <main>
        <div class="version-warning">
            You are viewing docs for v2.x. Switch to v3.x.
        </div>
        <h1>API Docs</h1>
        <p>Reference material.</p>
    </main>
    """
    result = extract_content(html)
    assert "API Docs" in result
    assert "viewing docs for" not in result


def test_removes_feedback_section():
    """'Was this helpful?' sections are removed."""
    html = """
    <main>
        <p>How to configure SSL.</p>
        <div class="was-this-helpful">
            <p>Was this page helpful?</p>
            <button>Yes</button><button>No</button>
        </div>
    </main>
    """
    result = extract_content(html)
    assert "configure SSL" in result
    assert "helpful" not in result


def test_removes_edit_on_github():
    """'Edit on GitHub' links are removed."""
    html = """
    <main>
        <p>Documentation text.</p>
        <a class="edit-on-github" href="https://github.com/...">Edit this page</a>
    </main>
    """
    result = extract_content(html)
    assert "Documentation text" in result
    assert "Edit this page" not in result


# ---------------------------------------------------------------------------
# Blacklist skip termination (issue #42)
# ---------------------------------------------------------------------------

def test_void_element_with_blacklisted_class_does_not_eat_the_rest():
    """A blacklisted void element has no end tag; skipping must not run away."""
    html = """
    <main>
        <p>First paragraph of the page.</p>
        <img class="copy-button" src="copy.png">
        <p>Second paragraph, this is the payload as text.</p>
    </main>
    """
    result = strip_html(extract_content(html))
    assert "First paragraph" in result
    assert "payload as text" in result


def test_void_element_with_blacklisted_id_does_not_eat_the_rest():
    """Same guarantee when the void element matches by id instead of class."""
    html = """
    <main>
        <p>Search the docs below.</p>
        <input id="sidebar-search" type="text">
        <p>Second paragraph, this is the payload as text.</p>
    </main>
    """
    result = strip_html(extract_content(html))
    assert "Search the docs" in result
    assert "payload as text" in result


def test_unclosed_blacklisted_tag_recovers_at_the_enclosing_element():
    """Stray markup in a code sample opens <aside> that never closes.

    The skip must end when the enclosing element closes, instead of
    discarding every sibling that follows.
    """
    html = """
    <main>
        <p>Example:</p>
        <pre><code>print("hello<aside>")</code></pre>
        <p>Second paragraph, this is the payload as text.</p>
    </main>
    """
    result = strip_html(extract_content(html))
    assert "Example:" in result
    assert "payload as text" in result


def test_blacklisted_void_element_is_still_removed():
    """Terminating the skip must not resurrect the blacklisted element."""
    html = """
    <main>
        <p>Body text.</p>
        <img class="copy-button" alt="Copy to clipboard" src="copy.png">
    </main>
    """
    result = extract_content(html)
    assert "Body text" in result
    assert "copy-button" not in result
    assert "Copy to clipboard" not in result


def test_closed_blacklisted_block_still_removes_its_children():
    """The recovery path must not weaken normal blacklist removal."""
    html = """
    <main>
        <p>Body text.</p>
        <aside class="related"><p>Sidebar noise.</p><img src="x.png"></aside>
        <p>Trailing text.</p>
    </main>
    """
    result = strip_html(extract_content(html))
    assert "Body text" in result
    assert "Trailing text" in result
    assert "Sidebar noise" not in result


# ---------------------------------------------------------------------------
# Fallback and edge cases
# ---------------------------------------------------------------------------

def test_fallback_returns_full_html_when_no_container_found():
    """If no container is found, return full HTML (never lose content)."""
    html = "<p>Texto simples sem nenhum wrapper.</p>"
    result = extract_content(html)
    assert "Texto simples" in result


def test_empty_html():
    """Empty HTML returns empty string."""
    result = extract_content("")
    assert result == ""


def test_whitespace_only_html():
    """Whitespace-only HTML returns empty string."""
    result = extract_content("   \n\t  ")
    assert result == ""


def test_html_with_only_blacklisted_content():
    """If HTML only has blacklisted content, result has no text."""
    html = """
    <nav>Menu</nav>
    <footer>Footer</footer>
    """
    result = extract_content(html)
    assert "Menu" not in result
    assert "Footer" not in result


def test_nested_semantic_containers():
    """<article> inside <main> — use <main> as container."""
    html = """
    <main>
        <article>
            <p>Nested content.</p>
        </article>
        <p>Extra main content.</p>
    </main>
    """
    result = extract_content(html)
    assert "Nested content" in result
    assert "Extra main content" in result


def test_malformed_html_does_not_crash():
    """Malformed HTML does not raise an exception."""
    html = """
    <main>
        <p>Unclosed paragraph
        <div>Nested without closing
        <p>More text</p>
    """
    result = extract_content(html)
    assert isinstance(result, str)


def test_preserves_code_blocks():
    """<pre><code> blocks inside content are preserved."""
    html = """
    <main>
        <h1>Example</h1>
        <pre><code>
def hello():
    print("world")
        </code></pre>
        <p>Explanation of the code.</p>
    </main>
    """
    result = extract_content(html)
    assert "def hello():" in result
    assert "print" in result
    assert "Explanation" in result


def test_nested_divs_same_tag():
    """Nested divs of the same tag type are handled correctly."""
    html = """
    <html><body>
        <nav>Nav</nav>
        <div id="content">
            <div class="inner">
                <p>Inner content.</p>
            </div>
            <p>Outer content.</p>
        </div>
    </body></html>
    """
    result = extract_content(html)
    assert "Inner content" in result
    assert "Outer content" in result
    assert "Nav" not in result


# ---------------------------------------------------------------------------
# Integration with strip_html
# ---------------------------------------------------------------------------

def test_extract_then_strip_produces_clean_text():
    """Full pipeline: extract_content -> strip_html produces clean text."""
    html = """
    <html><body>
        <nav><a href="/">Home</a></nav>
        <main>
            <h1>Installation Guide</h1>
            <p>Run the following command:</p>
            <pre><code>pip install dograpper</code></pre>
        </main>
        <footer>Copyright 2025</footer>
    </body></html>
    """
    extracted = extract_content(html)
    text = strip_html(extracted)

    assert "Installation Guide" in text
    assert "pip install dograpper" in text
    assert "Home" not in text
    assert "Copyright" not in text
    assert "<" not in text


# ---------------------------------------------------------------------------
# CLI integration (pack)
# ---------------------------------------------------------------------------

def test_pack_uses_extraction_by_default(tmp_path):
    """Pack without --no-extract should apply intelligent extraction."""
    html_file = tmp_path / "input" / "test.html"
    html_file.parent.mkdir()
    html_file.write_text("""
    <html><body>
        <nav>Navigation noise</nav>
        <main><p>Real documentation content here.</p></main>
        <footer>Footer noise</footer>
    </body></html>
    """)

    output_dir = tmp_path / "output"
    runner = CliRunner()
    result = runner.invoke(cli, ["pack", str(html_file.parent),
                                 "-o", str(output_dir)])
    assert result.exit_code == 0

    chunks = list(output_dir.glob("*.md"))
    assert len(chunks) >= 1
    content = chunks[0].read_text()
    assert "Real documentation" in content
    assert "Navigation noise" not in content
    assert "Footer noise" not in content


def test_pack_no_extract_preserves_boilerplate(tmp_path):
    """Pack with --no-extract should keep all content (legacy behavior)."""
    html_file = tmp_path / "input" / "test.html"
    html_file.parent.mkdir()
    html_file.write_text("""
    <html><body>
        <nav>Navigation noise</nav>
        <main><p>Real content.</p></main>
        <footer>Footer noise</footer>
    </body></html>
    """)

    output_dir = tmp_path / "output"
    runner = CliRunner()
    result = runner.invoke(cli, ["pack", str(html_file.parent),
                                 "-o", str(output_dir), "--no-extract"])
    assert result.exit_code == 0

    chunks = list(output_dir.glob("*.md"))
    content = chunks[0].read_text()
    assert "Navigation noise" in content
    assert "Footer noise" in content


# ---------------------------------------------------------------------------
# Utility function tests
# ---------------------------------------------------------------------------

def test_matches_class_substring():
    """_matches_class does substring match on individual classes."""
    assert _matches_class("docs-sidebar left-nav", {"sidebar"}) is True
    assert _matches_class("main-content", {"sidebar"}) is False
    assert _matches_class("breadcrumb-item", {"breadcrumb"}) is True
    assert _matches_class("content", {"content"}) is True
    assert _matches_class("my-content-wrapper", {"content"}) is True
    assert _matches_class("", {"sidebar"}) is False


def test_matches_class_no_false_positive_on_unrelated():
    """_matches_class does not match unrelated strings."""
    assert _matches_class("pagination", {"nav"}) is False
    assert _matches_class("main-body", {"sidebar"}) is False
