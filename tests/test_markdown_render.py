"""Markdown structure in md output (issue #87): headings, links, lists and tables.

`strip_html(html, markdown=True)` renders them; plain text (txt, jsonl) is unchanged.
"""

import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.utils.content_extractor import extract_content
from dograpper.utils.dedup import _leading_token
from dograpper.utils.heading_extractor import extract_with_headings
from dograpper.utils.html_stripper import MAX_LIST_DEPTH, strip_html
from dograpper.utils.word_counter import count_words
from tests.linearity import assert_linear


def md(html):
    return strip_html(html, markdown=True)


# ---------------------------------------------------------------------------
# Headings
# ---------------------------------------------------------------------------

def test_headings_get_one_marker_per_level():
    html = "".join(f"<h{n}>Level {n}</h{n}>" for n in range(1, 7))
    assert md(html) == "\n\n".join(f"{'#' * n} Level {n}" for n in range(1, 7))
    assert strip_html(html) == "\n\n".join(f"Level {n}" for n in range(1, 7))


def test_heading_is_its_own_block_with_inline_markup_flattened():
    html = "<p>intro</p>text<h2>Using <code>a &amp; b</code></h2>more"
    assert md(html) == "intro\n\ntext\n\n## Using a & b\n\nmore"


# ---------------------------------------------------------------------------
# Links
# ---------------------------------------------------------------------------

def test_links_keep_their_target_as_written():
    # #115: the target moves from the line to a reference definition at the end of the page.
    html = ('<p>See <a href="Lua_(API).html">the Lua API</a>, <a href="mailto:a@b.c">mail</a> '
            'and <a href="https://x.org/w/index.php?title=T&amp;action=edit&amp;section=2">docs</a>.</p>')
    assert md(html) == ("See [the Lua API][1], [mail][2] and [docs][3].\n\n"
                        "[1]: <Lua_(API).html>\n[2]: mailto:a@b.c\n"
                        "[3]: https://x.org/w/index.php?title=T&action=edit&section=2")
    assert strip_html(html) == "See the Lua API, mail and docs."


def test_each_target_is_defined_once_in_first_use_order_at_the_end():
    html = ('<p><a href="b.html">B</a> <a href="a.html">A</a> <a href="b.html">again</a></p>'
            '<ul><li><a href="c.html">C</a></li></ul><h2>See <a href="a.html">A</a></h2>')
    assert md(html) == ("[B][1] [A][2] [again][1]\n\n- [C][3]\n\n## See [A][2]\n\n"
                        "[1]: b.html\n[2]: a.html\n[3]: c.html")
    assert md("<p>no links</p>") == "no links"


def test_a_line_of_links_is_as_long_as_its_text():
    # Item_tag.html: one table row lists every item of a tag (#115).
    row = ", ".join(f'<a href="https://pzwiki.net/wiki/Item_{i}_with_a_long_name">I{i}</a>'
                    for i in range(500))
    body, definitions = md(f"<table><tr><th>Tag</th><th>Items</th></tr>"
                           f"<tr><td>t</td><td>{row}</td></tr></table>").split("\n\n")
    assert body.split("\n")[-1] == "| t | " + ", ".join(f"[I{i}][{i + 1}]" for i in range(500)) + " |"
    assert definitions.split("\n")[:2] == ["[1]: https://pzwiki.net/wiki/Item_0_with_a_long_name",
                                           "[2]: https://pzwiki.net/wiki/Item_1_with_a_long_name"]


@pytest.mark.parametrize("href", [
    "javascript:alert(1)", " JaVa\tScRiPt:alert(1)", "data:text/html,x", "vbscript:x",
    "file:///etc/passwd", "#Functions", "", None,
])
def test_unsafe_or_page_local_targets_keep_only_the_text(href):
    attr = "" if href is None else f' href="{href}"'
    assert md(f"<p>Go <a{attr}>there</a> now</p>") == "Go there now"


def test_link_to_the_page_itself_keeps_only_the_text():
    # A mirror writes "#anchor" as "page.html#anchor" (Sphinx permalinks).
    html = ('<h2>Usage<a class="headerlink" href="p.html#usage">¶</a></h2>'
            '<p><a href="p.html#">Back to top</a>, <a href="q.html#x">other</a></p>')
    assert strip_html(html, markdown=True, page="p.html") == (
        "## Usage¶\n\nBack to top, [other][1]\n\n[1]: q.html#x")
    doc = extract_with_headings(html, source_path="docs/p.html", markdown=True)
    assert doc.text == strip_html(html, markdown=True, page="p.html")


def test_link_target_and_text_cannot_break_out_of_the_link():
    assert md('<a href="a b<c>\\d\x07">x</a>') == "[x][1]\n\n[1]: a%20b%3Cc%3E%5Cd%07"
    assert md('<a href="f(x">y</a>') == "[y][1]\n\n[1]: <f(x>"
    assert md('<a href="u">a [b] \\ c</a>') == "[a \\[b\\] \\\\ c][1]\n\n[1]: u"


def test_link_whitespace_stays_outside_the_brackets():
    html = 'x<a href="u"> y </a>z'
    assert md(html) == "x [y][1] z\n\n[1]: u"
    assert strip_html(html) == "x y z"


def test_link_without_text_or_around_a_block_is_not_written():
    assert md('<p>a<a href="u"><img src="i.png"></a>b</p>') == "ab"
    assert md('<a href="u"><h3>Title</h3></a>') == "### Title"


# Javadoc 25 member signature, as IsoGameCharacter.html writes getInventory (#117).
SIGNATURE = ('<div class="member-signature"><span class="modifiers">public</span>&nbsp;'
             '<span class="return-type"><a href="../inventory/ItemContainer.html" '
             'title="class in zombie.inventory">ItemContainer</a></span>&nbsp;'
             '<span class="element-name">getInventory</span>()</div>')


def test_links_inside_code_keep_only_their_text():
    assert md(SIGNATURE) == "public ItemContainer getInventory()"
    assert md('<pre>x = <a href="u.html">y</a>()</pre>') == "```\nx = y()\n```"
    # A link around code is a prose link; prose links stay links.
    out = md('<p><code><a href="Foo.html">Foo</a>.bar()</code> or '
             '<a href="Foo.html"><code>Foo</code></a></p>')
    assert out.startswith("Foo.bar() or [Foo]")


def test_member_signature_ends_with_its_own_div():
    out = md('<div class="member-signature"><div>a <a href="u">b</a></div> <a href="v">c</a></div>'
             '<p><a href="w">d</a></p>').split("\n\n")
    assert out[:2] == ["a b", "c"] and out[2].startswith("[d]")


def test_pack_javadoc_signatures_read_as_the_source_shows_them(tmp_path):
    out = tmp_path / "out"
    javadoc = Path(__file__).parent / "fixtures" / "javadoc" / "html"
    result = CliRunner().invoke(cli, ["pack", str(javadoc), "-o", str(out), "--layout", "page"])
    assert result.exit_code == 0, result.output
    lines = (out / "pages" / "fixture" / "api" / "Box.md").read_text().split("\n")
    assert "public Box(String name)" in lines
    # the constructor summary: a row of the grid, the cell in code as the source shows it
    assert "| Box(String name) | Creates an empty box with a name. |" in lines


# ---------------------------------------------------------------------------
# Lists
# ---------------------------------------------------------------------------

def test_lists_get_markers_and_nesting_in_one_block():
    html = ('<ul><li>alpha</li><li>beta<ol start="3"><li>one</li><li>two</li></ol></li></ul>'
            '<p>after</p>')
    assert md(html) == "- alpha\n- beta\n  3. one\n  4. two\n\nafter"


def test_paragraphs_inside_an_item_stay_on_its_line():
    html = ('<ul class="simple"><li><p>first</p></li>'
            '<li><p>second <a href="x.html">link</a></p><p>more</p></li></ul>')
    assert md(html) == "- first\n- second [link][1] more\n\n[1]: x.html"


def test_item_holding_sections_is_rendered_as_blocks_without_a_marker():
    # Javadoc wraps each member's documentation in a list item.
    html = ('<ul class="member-list"><li><section class="detail"><h3>getX</h3>'
            '<div class="member-signature">public int getX()</div>'
            '<div class="block">Returns X.</div></section></li>'
            '<li><section><h3>getY</h3><div>Returns Y.</div></section></li></ul>')
    assert md(html) == "### getX\n\npublic int getX()\n\nReturns X.\n\n### getY\n\nReturns Y."


def test_list_mixing_entries_and_blocks_keeps_item_numbers():
    html = "<ol><li>Install</li><li><pre>make\nmake install</pre></li><li>Run</li></ol>"
    assert md(html) == "1. Install\n\n```\nmake\nmake install\n```\n\n3. Run"


# ---------------------------------------------------------------------------
# Tables
# ---------------------------------------------------------------------------

MAP_INFO_TABLE = (
    '<table class="wikitable theme-blue">\n<caption>List of parameters\n</caption>\n'
    "<tbody><tr>\n<th>Parameter name</th>\n<th>Description\n</th></tr>\n"
    '<tr>\n<td style="padding: 10px;"><big><code>title</code></big>\n</td>\n'
    "<td>Title of the map - shown in menus.\n</td></tr>\n"
    "<tr>\n<td><big><code>lots</code></big>\n</td>\n"
    "<td>Use <code>lots=Muldraugh, KY</code> | or not.\n"
    '<div class="mbox"><div><div>Need more information.</div></div></div>\n</td></tr>\n'
    "</tbody></table>"
)


def test_table_row_stays_on_one_line():
    assert md(MAP_INFO_TABLE) == (
        "List of parameters\n\n"
        "| Parameter name | Description |\n"
        "| --- | --- |\n"
        "| title | Title of the map - shown in menus. |\n"
        "| lots | Use lots=Muldraugh, KY \\| or not. Need more information. |")


def test_table_without_header_cells_uses_its_first_row_and_pads_it():
    html = "<table><tr><td>k</td></tr><tr><td>a</td><td>b</td></tr></table>"
    assert md(html) == "| k |  |\n| --- | --- |\n| a | b |"


def test_one_line_code_in_a_cell_becomes_a_code_span():
    html = ("<table><tr><th>Name</th><th>Example</th></tr><tr><td>shadowExtents</td><td>"
            '<div class="mw-highlight mw-highlight-lang-text"><pre>shadowExtents = `0.75`,\n'
            "</pre></div></td></tr></table>")
    assert md(html) == ("| Name | Example |\n| --- | --- |\n"
                        "| shadowExtents | ``shadowExtents = `0.75`,`` |")


def test_table_with_multi_line_code_in_a_cell_keeps_the_code_block():
    html = ("<table><tr><td>boolean</td><td><pre>type = boolean,\ndefault = true,</pre>"
            "</td></tr></table>")
    assert md(html) == "boolean\n\n```\ntype = boolean,\ndefault = true,\n```"


def test_list_in_a_cell_is_written_inline():
    html = ("<table><tr><th>Room</th><th>Tiles</th></tr><tr><td>Salon</td><td><ul>"
            "<li><p>t_32</p></li><li><p>t_33</p></li></ul></td></tr></table>")
    assert md(html) == "| Room | Tiles |\n| --- | --- |\n| Salon | t_32 t_33 |"


def test_nested_table_keeps_the_outer_table_as_blocks():
    html = "<table><tr><td>outer<table><tr><td>a</td><td>b</td></tr></table></td></tr></table>"
    assert md(html) == "outer\n\n| a | b |\n| --- | --- |"


def test_omitted_end_tags_close_items_and_cells():
    assert md("<ul><li>a<li>b</ul>") == "- a\n- b"
    assert md("<table><tr><td>a<td>b<tr><td>c<td>d</table>") == (
        "| a | b |\n| --- | --- |\n| c | d |")


def test_unclosed_structures_keep_their_text():
    assert md("<p>x</p><ul><li>a<li>b") == "x\n\n- a\n- b"
    assert md("<table><tr><td>a") == "| a |\n| --- |"
    assert md("<h2>Title") == "## Title"


# ---------------------------------------------------------------------------
# Code fences (#86) are unchanged
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("html", [
    "<p>Run:</p><pre>\n  make\n  make install\n</pre>",
    "<pre>a\n\n\n  b</pre><p>after</p>",
    "<pre>```\nnested\n```</pre>",
    '<div class="mw-highlight mw-highlight-lang-lua"><pre>if x then\n  y()\nend</pre></div>',
])
def test_code_fences_are_the_same_in_markdown(html):
    assert md(html) == strip_html(html)


# ---------------------------------------------------------------------------
# Untrusted input stays linear
# ---------------------------------------------------------------------------

def test_deep_nesting_and_huge_tables_render_in_linear_time():
    n = 2500

    def nested(k):
        return "<ul><li>x" * k + "</li></ul>" * k

    def table(k):
        return "<table>" + "<tr><td>k</td><td>v</td></tr>" * k + "</table>"

    lines = md(nested(n)).split("\n")
    assert len(lines) == n
    assert max(len(line) - len(line.lstrip()) for line in lines) <= 2 * MAX_LIST_DEPTH
    assert md("<ul><li><div>x" * n).count("x") == n
    assert len(md(table(n)).split("\n")) == n + 1
    assert_linear(nested, md, n)
    assert_linear(lambda k: "<ul><li><div>x" * k, md, n)
    assert_linear(table, md, n)


def test_many_links_render_in_linear_time():
    def page(n):
        return ("<p>" + "".join(f'<a href="u{i % 1000}">x{i}</a> ' for i in range(n)) + "</p>"
                + "<table>" + '<tr><td><a href="v">k</a></td></tr>' * n + "</table>")

    n = 2500
    assert len(md(page(n)).rsplit("\n\n", 1)[1].split("\n")) == 1001
    assert_linear(page, md, n)


# ---------------------------------------------------------------------------
# Heading offsets and word counts
# ---------------------------------------------------------------------------

def test_md_heading_offsets_point_at_their_heading_lines():
    html = ('<h1>Guide</h1><p>See <a href="https://example.com/a/very/long/url">this</a>.</p>'
            "<h2>Install</h2><ul><li>a</li></ul><h3>Steps &amp; more</h3><p>x</p>")
    doc = extract_with_headings(html, markdown=True)
    assert doc.text == md(html)
    assert [(h.level, h.text) for h in doc.headings] == [
        (1, "Guide"), (2, "Install"), (3, "Steps & more")]
    for h in doc.headings:
        assert doc.text[h.char_offset:].startswith("#" * h.level + " " + h.text)


PAGE = (
    "<html><body><main><h2>Parameters</h2>\n"
    '<p>See <a href="Map.info.html">the map info page</a> first.</p>\n'
    + MAP_INFO_TABLE +
    "\n<ul><li>one item</li><li>two <ol><li>nested</li></ol></li></ul>\n"
    "<pre># a comment\n- not a list\n| not a table |</pre>\n"
    "</main></body></html>"
)


def test_markdown_markup_is_not_counted_as_words():
    plain, rendered = strip_html(PAGE), md(PAGE)
    assert count_words(rendered, markdown=True) == count_words(plain) == len(plain.split())
    assert count_words(rendered) == len(rendered.split()) > count_words(rendered, markdown=True)


def test_link_definitions_are_not_counted_as_words():
    assert count_words("a [b c][1] d\n\n[1]: u\n[2]: <v w>", markdown=True) == 4
    # Only the block that ends the text is the page's definitions.
    assert count_words("[1]: u\n\nend", markdown=True) == 3
    assert count_words("a[1]: u", markdown=True) == 2
    assert count_words("[1]: u\n[2]: v\n", markdown=True) == 0


@pytest.mark.parametrize("block,token", [
    ("## Parameters of the map", "Parameters"),
    ("| title | Title of the map. |\n| --- | --- |", "title"),
    ("- one item\n- two", "one"),
])
def test_dedup_leading_token_skips_markdown_markers(block, token):
    assert _leading_token(block) == token


# ---------------------------------------------------------------------------
# pack: md renders, txt and jsonl stay plain
# ---------------------------------------------------------------------------

def _pack(tmp_path, fmt, *extra, pages=None):
    docs = tmp_path / "docs"
    docs.mkdir(exist_ok=True)
    for name, html in (pages or {"page.html": PAGE}).items():
        (docs / name).write_text(html)
    out = tmp_path / f"out-{fmt}"
    result = CliRunner().invoke(cli, ["pack", str(docs), "-o", str(out), "--format", fmt, *extra])
    assert result.exit_code == 0, result.output
    return out


def test_pack_md_renders_markdown_and_txt_stays_plain(tmp_path):
    written = next(_pack(tmp_path, "md", "--no-index").glob("*.md")).read_text()
    assert "## Parameters\n" in written
    assert "[the map info page][1]" in written and written.endswith("\n\n[1]: Map.info.html")
    assert "| title | Title of the map - shown in menus. |\n" in written
    assert "- one item\n- two\n  1. nested\n" in written
    txt = next(_pack(tmp_path, "txt", "--no-index").glob("*.txt")).read_text()
    plain = strip_html(extract_content(PAGE)).replace("```\n", "").replace("\n```", "")
    assert txt == "=== SOURCE: page.html ===\n\n" + plain


def test_pack_jsonl_content_stays_plain(tmp_path):
    record, = [json.loads(line) for line in
               next(_pack(tmp_path, "jsonl").glob("*.jsonl")).read_text().splitlines()]
    assert record["content"] == strip_html(extract_content(PAGE)).replace(
        "```\n", "").replace("\n```", "")


NO_CODE_PAGE = PAGE.replace("<pre># a comment\n- not a list\n| not a table |</pre>\n", "")


def test_pack_md_counts_words_without_markup(tmp_path):
    pages = {"a.html": NO_CODE_PAGE, "b.html": NO_CODE_PAGE.replace("Parameters", "Usage")}
    md_out = _pack(tmp_path, "md", "--context-header", pages=pages)
    txt_out = _pack(tmp_path, "txt", "--context-header", pages=pages)
    md_text = next(md_out.glob("*.md")).read_text()
    txt_text = next(txt_out.glob("*.txt")).read_text()
    # Same per-file budget (the file list) and header counts in both formats.
    def listed(text):
        return [line for line in text.split("\n") if line.endswith(" words)")]
    assert listed(md_text) == listed(txt_text) and len(listed(md_text)) == 2
    counts = [json.loads(h.split("\n-->")[0])["word_count"]
              for h in md_text.split("<!-- dograpper-context-v1\n")[1:]]
    assert counts == [json.loads(h.split("\n-->")[0])["word_count"]
                      for h in txt_text.split("<!-- dograpper-context-v1\n")[1:]]
    bodies = [h.split("\n-->\n\n", 1)[1] for h in md_text.split("<!-- dograpper-context-v1\n")[1:]]
    assert counts == [count_words(b.strip(), markdown=True) for b in bodies]


def test_page_layout_md_renders_markdown_and_counts_without_markup(tmp_path):
    out = _pack(tmp_path, "md", "--layout", "page", "--context-header", "--score")
    body = (out / "pages" / "page.md").read_text().split("\n-->\n\n", 1)[1]
    assert "## Parameters\n" in body and "| --- | --- |\n" in body
    words = count_words(body, markdown=True)
    assert f"), {words} words" in (out / "INDEX.md").read_text()
    readiness = json.loads((out / "llm-readiness.json").read_text())
    assert [c["word_count"] for c in readiness["chunks"]] == [words]
    assert body.endswith("\n\n[1]: Map.info.html\n")
    txt = (_pack(tmp_path, "txt", "--layout", "page") / "pages" / "page.txt").read_text()
    assert "## " not in txt and "](" not in txt and "| --- |" not in txt and "[1]" not in txt


def test_each_page_of_a_chunk_ends_with_its_own_definitions(tmp_path):
    pages = {"a.html": '<p>see <a href="x.html">x</a></p>',
             "b.html": '<p>see <a href="y.html">y</a></p>'}
    text = next(_pack(tmp_path, "md", "--no-index", pages=pages).glob("*.md")).read_text()
    assert text == ("<!-- SOURCE: a.html -->\n\nsee [x][1]\n\n[1]: x.html\n\n"
                    "<!-- SOURCE: b.html -->\n\nsee [y][1]\n\n[1]: y.html")


SPLIT_PAGE = ("<html><body><main>"
              + "".join(f'<h2>Part {i}</h2><p>{"word " * 30}<a href="t{i % 2}.html">target {i}</a>'
                        ' and <a href="common.html">common</a>.</p>' for i in range(4))
              + "</main></body></html>")


def test_each_context_section_ends_with_the_definitions_it_uses(tmp_path):
    # A page split over several context headers: no section depends on another's definitions.
    def sections(fmt):
        out = _pack(tmp_path, fmt, "--context-header", "--max-words-per-chunk", "40",
                    pages={"page.html": SPLIT_PAGE})
        text = next(out.glob(f"*.{fmt}")).read_text()
        return [s.split("\n-->\n\n", 1) for s in text.split("<!-- dograpper-context-v1\n")[1:]]

    md_sections = sections("md")
    assert len(md_sections) == 4
    for i, (header, body) in enumerate(md_sections):
        prose, definitions = body.rstrip("\n").rsplit("\n\n", 1)
        # Page-wide numbers: t0.html is 1, common.html 2, t1.html 3.
        assert definitions == ("[1]: t0.html\n[2]: common.html" if i % 2 == 0
                               else "[2]: common.html\n[3]: t1.html")
        assert json.loads(header)["word_count"] == count_words(prose, markdown=True) > 30
    assert [json.loads(h)["word_count"] for h, _ in md_sections] == [
        json.loads(h)["word_count"] for h, _ in sections("txt")]



def test_pack_md_drops_links_to_the_page_itself(tmp_path):
    page = ('<html><body><main><h2>Usage<a class="headerlink" href="page.html#usage">¶</a></h2>'
            '<p>See <a href="page.html#x">above</a> and <a href="other.html">other</a>.</p>'
            "</main></body></html>")
    for extra in ((), ("--context-header",)):
        out = _pack(tmp_path, "md", "--no-index", *extra, pages={"page.html": page})
        written = next(out.glob("*.md")).read_text()
        assert "See above and [other][1]." in written and "\n\n[1]: other.html" in written


# ---------------------------------------------------------------------------
# <br> separates its neighbours (issue #116)
# ---------------------------------------------------------------------------

BR_CELL = ("<table><tr><th>Name</th><th>Example</th></tr><tr><td>debuglog</td>"
           "<td><code>-debuglog=All</code><br/><code>-debuglog=Network,Sound</code></td></tr></table>")


def test_br_in_a_table_cell_separates_the_values_and_keeps_the_row_on_one_line():
    assert md(BR_CELL).splitlines()[-1] == (
        "| debuglog | -debuglog=All; -debuglog=Network,Sound |")


def test_br_in_a_table_cell_separates_the_values_in_txt():
    assert "-debuglog=All\n-debuglog=Network,Sound" in strip_html(BR_CELL)


@pytest.mark.parametrize("markdown", [True, False])
def test_br_in_body_text_is_a_line_break_inside_one_paragraph(markdown):
    out = strip_html("<p>one<br>two <br/> <br>three</p><p>four</p>", markdown=markdown)
    assert out == "one\ntwo\nthree\n\nfour"


@pytest.mark.parametrize("markdown", [True, False])
def test_br_does_not_add_words(markdown):
    assert count_words(strip_html("<p>one<br>two</p>", markdown=markdown)) == 2
    assert count_words(strip_html("<p>a<br>b <br> c</p>", markdown=markdown)) == count_words("a b c")


@pytest.mark.parametrize("markdown", [True, False])
@pytest.mark.parametrize("page", ["<p>onetwo</p>", "<p>one&#xE000;two</p>", "<p>one&amp;#xE000;two</p>"])
def test_a_page_cannot_forge_a_br(page, markdown):
    assert "\n" not in strip_html(page, markdown=markdown)


# ---------------------------------------------------------------------------
# Plain-text table cells (#125)
# ---------------------------------------------------------------------------

ROW = "<table><tr><th>Name</th><th>Example</th></tr><tr><td>debuglog</td><td>-debuglog=All</td></tr></table>"


def test_plain_text_separates_the_cells_of_a_row_with_a_tab():
    assert strip_html(ROW) == "Name\tExample\n\ndebuglog\t-debuglog=All"


def test_plain_text_keeps_empty_cells_and_drops_the_trailing_separator():
    assert strip_html("<table><tr><td>a</td><td></td><td>b</td><td></td></tr></table>") == "a\t\tb"


def test_plain_text_separates_cells_whose_end_tags_are_omitted():
    assert strip_html("<table><tr><td>a<td>b<tr><td>c<th>d</table>") == "a\tb\n\nc\td"


def test_plain_text_cell_separator_is_not_a_word():
    assert count_words(strip_html(ROW)) == 4
    assert count_words(strip_html("<table><tr><td>a b</td><td>c</td></tr></table>")) == 3


def test_md_table_is_unchanged_by_the_plain_cell_separator():
    assert md(ROW).splitlines()[-1] == "| debuglog | -debuglog=All |"


@pytest.mark.parametrize("page", ["<p>onetwo</p>", "<p>one&#xE001;two</p>", "<p>one&amp;#xE001;two</p>"])
def test_a_page_cannot_forge_a_cell_separator(page):
    assert "\t" not in strip_html(page)


# ---------------------------------------------------------------------------
# Javadoc summary grids (#120): div.summary-table, cells are flat child divs
# ---------------------------------------------------------------------------

GRID = (
    '<div class="summary-table three-column-summary">'
    '<div class="table-header col-first">Modifier and Type</div>'
    '<div class="table-header col-second">Constant Field</div>'
    '<div class="table-header col-last">Value</div>'
    '<div class="col-first even-row-color"><code>static&nbsp;final&nbsp;double</code></div>'
    '<div class="col-second even-row-color"><code><a href="M.html#PI">PI</a></code></div>'
    '<div class="col-last even-row-color"><code>3.14</code></div>'
    '<div class="col-first odd-row-color"><code>int</code></div>'
    '<div class="col-second odd-row-color"><code>N</code></div>'
    '<div class="col-last odd-row-color">\n<div class="block">Count.</div>\n<div class="block">More.</div>\n</div>'
    '</div><p>after</p>'
)


def test_javadoc_summary_grid_is_a_pipe_table_one_line_per_row():
    assert md(GRID) == (
        "| Modifier and Type | Constant Field | Value |\n"
        "| --- | --- | --- |\n"
        "| static final double | PI | 3.14 |\n"
        "| int | N | Count. More. |\n\nafter")


def test_javadoc_two_column_grid_and_stray_div_are_handled():
    html = ('<div class="summary-table two-column-summary">'
            '<div class="table-header col-first">Constructor</div>'
            '<div class="table-header col-last">Description</div>'
            '<div class="col-first"><code>Box()</code></div><div class="col-last">Empty.</div>'
            '<div class="col-first"><code>Box(int)</code></div></div>')
    assert md(html) == ("| Constructor | Description |\n| --- | --- |\n"
                        "| Box() | Empty. |\n| Box(int) |")


def test_div_without_the_grid_class_is_still_one_paragraph_per_div():
    assert md('<div class="x"><div>a</div><div>b</div></div>') == "a\n\nb"


def test_javadoc_summary_grid_row_is_one_line_in_a_pack(tmp_path):
    page = "<html><body><main><h1>Consts</h1>" + GRID + "</main></body></html>"
    written = next(_pack(tmp_path, "md", "--no-index", pages={"c.html": page}).glob("*.md")).read_text()
    assert "| int | N | Count. More. |\n" in written


def test_unclosed_javadoc_grids_render_in_linear_time():
    n = 2500

    def unclosed(k):
        return '<div class="summary-table two-column-summary"><div>k<div>v' * k

    def grid(k):
        return '<div class="summary-table three-column-summary">' + "<div>a</div>" * 3 * k + "</div>"

    assert md(unclosed(n)).count("k") == n
    assert len(md(grid(n)).split("\n")) == n + 1
    assert_linear(unclosed, md, n)
    assert_linear(grid, md, n)
