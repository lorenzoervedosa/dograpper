"""`pack --layout page`: one file per page under pages/, plus INDEX.md (ADR-0010)."""

import json
import os
import time

import pytest
from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.lib import page_layout
from dograpper.lib.page_layout import assign_page_paths, page_titles
from dograpper.utils.word_counter import count_words


@pytest.fixture(autouse=True)
def _cwd(tmp_path, monkeypatch):
    # No stray .dograpper.json / manifest / .docsignore from the caller's directory.
    monkeypatch.chdir(tmp_path)


def _write(root, files):
    for rel, body in files.items():
        path = os.path.join(root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(body)


def _wiki_page(title, body, marker_url=None):
    """MediaWiki-like page: the h1 sits outside the extracted <main>."""
    marker = (f"<!-- Mirrored from {marker_url} by HTTrack Website Copier/3.x "
              f"[XR&CO'2014], Mon, 01 Jan 2024 00:00:00 GMT -->\n") if marker_url else ""
    return (f"<html>{marker}<head><title>{title} - PZwiki</title></head><body>"
            f"<h1 id=\"firstHeading\">{title}</h1>"
            f"<main><h2>Usage</h2><p>{body}</p></main></body></html>")


def _corpus(root):
    _write(root, {
        "ActionGroup.html": _wiki_page(
            "ActionGroup", "action group words here",
            "pzwiki.net/wiki/ActionGroup"),
        "Help_Style_guide.html": _wiki_page("Help:Style guide", "style guide words"),
        "Modding.html": _wiki_page("Modding", "modding intro words"),
        "Modding/vi.html": _wiki_page("Bản Mod", "tiếng việt words"),
    })


def _pack(*args):
    return CliRunner().invoke(cli, ["pack", *args], catch_exceptions=False)


def _read(path):
    with open(path, encoding='utf-8') as f:
        return f.read()


def _tree(root):
    out = []
    for dirpath, _, files in os.walk(root):
        for f in files:
            out.append(os.path.relpath(os.path.join(dirpath, f), root).replace(os.sep, '/'))
    return sorted(out)


# ---------------------------------------------------------------------------
# File names (ADR-0010 point 2)
# ---------------------------------------------------------------------------

def test_paths_mirror_the_source_tree_with_the_format_extension():
    got = assign_page_paths(["Modding/vi.html", "Adding_new_tiles.html", "notes.txt"], "md")
    assert got == {
        "Adding_new_tiles.html": "pages/Adding_new_tiles.md",
        "Modding/vi.html": "pages/Modding/vi.md",
        "notes.txt": "pages/notes.md",
    }
    assert assign_page_paths(["a/b.htm"], "txt") == {"a/b.htm": "pages/a/b.txt"}


def test_httrack_forbidden_characters_become_underscores():
    got = assign_page_paths(['Help:Style_guide.html', 'a?b*c"d<e>f|g~h.html',
                             'x\x01y\x7fz.html', 'Lua_(language).html'], "md")
    assert got['Help:Style_guide.html'] == "pages/Help_Style_guide.md"
    assert got['a?b*c"d<e>f|g~h.html'] == "pages/a_b_c_d_e_f_g_h.md"
    assert got['x\x01y\x7fz.html'] == "pages/x_y_z.md"
    assert got['Lua_(language).html'] == "pages/Lua_(language).md"  # parentheses kept


def test_windows_reserved_names_and_trailing_dot_or_space_get_an_underscore():
    got = assign_page_paths(["CON.html", "nul.html", "Com1.html", "lpt9.html",
                             "COM0.html", "console.html", "trail..html", "space .html",
                             "aux/x.html", "dir./y.html"], "md")
    assert got["CON.html"] == "pages/CON_.md"
    assert got["nul.html"] == "pages/nul_.md"
    assert got["Com1.html"] == "pages/Com1_.md"
    assert got["lpt9.html"] == "pages/lpt9_.md"
    assert got["COM0.html"] == "pages/COM0.md"
    assert got["console.html"] == "pages/console.md"
    assert got["trail..html"] == "pages/trail_.md"
    assert got["space .html"] == "pages/space_.md"
    assert got["aux/x.html"] == "pages/aux_/x.md"
    assert got["dir./y.html"] == "pages/dir_/y.md"


def test_collisions_are_casefolded_and_numbered_in_sorted_source_order():
    got = assign_page_paths(["page.html", "Page.html", "PAGE.htm", "a:b.html", "a_b.html"], "md")
    # sorted source order: PAGE.htm, Page.html, a:b.html, a_b.html, page.html
    assert got["PAGE.htm"] == "pages/PAGE.md"
    assert got["Page.html"] == "pages/Page-2.md"
    assert got["page.html"] == "pages/page-3.md"
    assert got["a:b.html"] == "pages/a_b.md"
    assert got["a_b.html"] == "pages/a_b-2.md"
    # same tree, any input order, same names
    assert assign_page_paths(list(reversed(list(got))), "md") == got


# ---------------------------------------------------------------------------
# Titles (ADR-0010 points 3 and 4)
# ---------------------------------------------------------------------------

def test_title_is_the_head_title_minus_the_shared_site_suffix(tmp_path):
    _write(str(tmp_path / "d"), {
        "a.html": "<html><head><title>Alpha - PZwiki</title></head><body><p>x</p></body></html>",
        "b.html": "<html><head><title>Beta - Gamma - PZwiki</title></head><body></body></html>",
        "c.html": "<html><head><title>Sign-in - Two factor</title></head><body></body></html>",
    })
    titles = page_titles(["a.html", "b.html", "c.html"], str(tmp_path / "d"))
    # " - PZwiki" ends 2 of 3 titles; " - Two factor" ends only one and is kept
    assert titles == {"a.html": "Alpha", "b.html": "Beta - Gamma",
                      "c.html": "Sign-in - Two factor"}


def test_suffix_shared_by_half_the_titles_or_fewer_is_kept(tmp_path):
    _write(str(tmp_path / "d"), {
        "a.html": "<html><head><title>Alpha | Site</title></head></html>",
        "b.html": "<html><head><title>Beta | Site</title></head></html>",
        "c.html": "<html><head><title>Gamma — Other</title></head></html>",
        "d.html": "<html><head><title>Delta – Else</title></head></html>",
    })
    titles = page_titles(["a.html", "b.html", "c.html", "d.html"], str(tmp_path / "d"))
    assert titles["a.html"] == "Alpha | Site"
    assert titles["c.html"] == "Gamma — Other"


def test_each_separator_counts_as_a_suffix_boundary(tmp_path):
    _write(str(tmp_path / "d"), {
        f"{i}.html": f"<html><head><title>T{i}{sep}Docs</title></head></html>"
        for i, sep in enumerate([" — ", " — ", " — "])
    } | {"x.html": "<html><head><title>X – Docs</title></head></html>"})
    titles = page_titles(["0.html", "1.html", "2.html", "x.html"], str(tmp_path / "d"))
    assert [titles[f"{i}.html"] for i in range(3)] == ["T0", "T1", "T2"]
    assert titles["x.html"] == "X – Docs"  # " – Docs" is a different suffix


def test_svg_titles_in_the_body_are_not_the_page_title(tmp_path):
    _write(str(tmp_path / "d"), {
        "a.html": ("<html><head><meta charset=utf-8></head><body>"
                   "<svg><title>Copy</title></svg><h1>Real &amp; heading</h1></body></html>"),
        "b.html": ("<html><head><title>  Page\n   Title  </title></head><body>"
                   "<svg><title>Icon</title></svg></body></html>"),
    })
    titles = page_titles(["a.html", "b.html"], str(tmp_path / "d"))
    assert titles == {"a.html": "Real & heading", "b.html": "Page Title"}


def test_title_falls_back_to_the_raw_h1_then_to_the_file_stem(tmp_path):
    _write(str(tmp_path / "d"), {
        # h1 outside <main>: the extraction drops it, the title still has it
        "wiki.html": ("<html><head></head><body><h1 id=\"firstHeading\">Item <i>tags</i></h1>"
                      "<main><p>body</p></main></body></html>"),
        "sub/bare.html": "<html><body><p>no title, no h1</p></body></html>",
        "notes.md": "# Markdown heading\n\ntext",
        "empty_title.html": "<html><head><title>   </title></head><body><h1>H</h1></body></html>",
    })
    titles = page_titles(["wiki.html", "sub/bare.html", "notes.md", "empty_title.html"],
                         str(tmp_path / "d"))
    assert titles == {"wiki.html": "Item tags", "sub/bare.html": "bare",
                      "notes.md": "notes", "empty_title.html": "H"}


# ---------------------------------------------------------------------------
# CLI: tree, index, counts
# ---------------------------------------------------------------------------

def test_one_file_per_page_named_after_the_page(tmp_path):
    _corpus("docs")
    _write("docs", {"skip.html": "<html><body>x</body></html>", "data.json": "{}"})
    result = _pack("docs", "-o", "out", "--layout", "page", "--ignore", "skip.html")
    assert result.exit_code == 0, result.output
    assert _tree("out") == ["INDEX.md", "pages/ActionGroup.md", "pages/Help_Style_guide.md",
                            "pages/Modding.md", "pages/Modding/vi.md"]
    assert "WARNING" not in result.output
    assert "Pages written:   4" in result.output
    assert "Chunks generated" not in result.output
    body = _read("out/pages/Modding/vi.md")
    assert "tiếng việt words" in body
    assert "<!--" not in body and "Files in this chunk" not in body


def test_index_lists_every_page_once_in_the_adr_format(tmp_path):
    _corpus("docs")
    result = _pack("docs", "-o", "out", "--layout", "page")
    assert result.exit_code == 0, result.output
    lines = _read("out/INDEX.md").split("\n")
    # md pages are Markdown: their "##" heading markers are not words (#87).
    words = {rel: count_words(_read(f"out/pages/{rel}"), markdown=True) for rel in
             ("ActionGroup.md", "Help_Style_guide.md", "Modding.md", "Modding/vi.md")}
    assert lines == [
        "# Index",
        "4 pages. One line per page: - [title](<path>), N words, URL",
        "",
        f"- [ActionGroup](<pages/ActionGroup.md>), {words['ActionGroup.md']} words, "
        "http://pzwiki.net/wiki/ActionGroup",
        f"- [Help:Style guide](<pages/Help_Style_guide.md>), {words['Help_Style_guide.md']} words",
        f"- [Modding](<pages/Modding.md>), {words['Modding.md']} words",
        f"- [Bản Mod](<pages/Modding/vi.md>), {words['Modding/vi.md']} words",
        "",
    ]


def test_index_titles_are_escaped_and_neutralized(tmp_path):
    _write("docs", {
        "a.html": "<html><head><title>[x] \\ y]\n\t z\x07</title></head></html>",
    })
    result = _pack("docs", "-o", "out", "--layout", "page")
    assert result.exit_code == 0, result.output
    line = _read("out/INDEX.md").split("\n")[3]
    assert line.startswith("- [\\[x\\] \\\\ y\\] z\\x07](<pages/a.md>), ")


def test_page_layout_writes_no_chunk_files_and_respects_format_txt(tmp_path):
    _corpus("docs")
    result = _pack("docs", "-o", "out", "--layout", "page", "--format", "txt")
    assert result.exit_code == 0, result.output
    assert not [f for f in os.listdir("out") if f.startswith("docs_chunk_")]
    assert os.path.isfile("out/pages/Modding/vi.txt")
    assert "(<pages/Modding/vi.txt>)" in _read("out/INDEX.md")


def test_txt_pages_carry_code_without_its_fence(tmp_path):
    code = "local function onTick()\n    if x then\n\n        print(x)\n    end\nend"
    _write("docs", {"Events.html": (
        "<html><body><main><h2>Events</h2><p>Some prose so the page has text to extract.</p>"
        f'<div class="mw-highlight mw-highlight-lang-lua"><pre>{code}\n</pre></div>'
        "</main></body></html>")})
    for extra in ((), ("--context-header",)):
        result = _pack("docs", "-o", "out", "--layout", "page", "--format", "txt", *extra)
        assert result.exit_code == 0, result.output
        text = _read("out/pages/Events.txt")
        assert code in text, text
        assert "```" not in text
    body = text.split("\n-->\n\n", 1)[1]
    assert _header("out/pages/Events.txt")["word_count"] == len(body.split())
    assert f"), {len(body.split())} words" in _read("out/INDEX.md")
    result = _pack("docs", "-o", "out-md", "--layout", "page")
    assert "```lua\n" + code + "\n```" in _read("out-md/pages/Events.md")


def test_page_over_the_word_cap_is_neither_split_nor_warned(tmp_path):
    _write("docs", {"big.html": "<html><body><main><p>" + "w " * 600000
                    + "</p></main></body></html>"})
    result = _pack("docs", "-o", "out", "--layout", "page")
    assert result.exit_code == 0, result.output
    assert "exceed" not in result.output.lower()
    assert _tree("out") == ["INDEX.md", "pages/big.md"]


# ---------------------------------------------------------------------------
# Usage errors (exit 2)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("args", [
    ["--max-words-per-chunk", "1000"],
    ["--max-chunks", "50"],        # set to its default value: still set
    ["--strategy", "size"],
    ["--prefix", "x_"],
    ["--with-index"],
    ["--no-index"],
    ["--format", "jsonl"],
    ["--bundle", "notebooklm"],
    ["--bundle", "rag-standard"],
    ["--for-queries", "q.txt"],
    ["--dedup", "exact"],
    ["--dedup", "fuzzy"],
    ["--dedup", "both"],
])
def test_flags_without_meaning_in_the_page_layout_are_usage_errors(tmp_path, args):
    _corpus("docs")
    _write(".", {"q.txt": "modding\n"})
    result = _pack("docs", "-o", "out", "--layout", "page", *args)
    assert result.exit_code == 2, result.output
    assert "--layout page" in result.output
    assert not os.path.exists("out")


@pytest.mark.parametrize("key, value", [
    ("max-words-per-chunk", 500000), ("max_chunks", 50), ("strategy", "semantic"),
    ("prefix", "docs_chunk_"), ("with-index", True), ("format", "jsonl"),
    ("bundle", "notebooklm"), ("dedup", "both"),
])
def test_chunk_only_keys_in_config_are_usage_errors(tmp_path, key, value):
    _corpus("docs")
    with open(".dograpper.json", "w", encoding="utf-8") as f:
        json.dump({"pack": {"layout": "page", key: value}}, f)
    result = _pack("docs", "-o", "out")
    assert result.exit_code == 2, result.output
    assert "--layout page" in result.output
    assert not os.path.exists("out")


def test_defaults_and_allowed_flags_never_trigger_an_error(tmp_path):
    _corpus("docs")
    with open(".dograpper.json", "w", encoding="utf-8") as f:
        json.dump({"pack": {"layout": "page", "dedup": "off", "format": "md",
                            "context-header": True}}, f)
    result = _pack("docs", "-o", "out", "--dedup", "off", "--format", "md",
                   "--cross-refs", "--score", "--show-tokens", "--no-extract")
    assert result.exit_code == 0, result.output


def test_explicit_cli_layout_beats_config(tmp_path):
    _corpus("docs")
    with open(".dograpper.json", "w", encoding="utf-8") as f:
        json.dump({"pack": {"layout": "page", "max-chunks": 10}}, f)
    result = _pack("docs", "-o", "out", "--layout", "chunk")
    assert result.exit_code == 0, result.output
    assert os.listdir("out") == ["docs_chunk_01.md"]


# ---------------------------------------------------------------------------
# Ownership of pages/ (ADR-0010 point 5)
# ---------------------------------------------------------------------------

def test_every_run_rebuilds_pages_so_stale_pages_disappear(tmp_path):
    _corpus("docs")
    assert _pack("docs", "-o", "out", "--layout", "page").exit_code == 0
    os.remove("docs/Modding/vi.html")
    os.rename("docs/Modding.html", "docs/Modding_intro.html")
    result = _pack("docs", "-o", "out", "--layout", "page")
    assert result.exit_code == 0, result.output
    assert _tree("out") == ["INDEX.md", "pages/ActionGroup.md", "pages/Help_Style_guide.md",
                            "pages/Modding_intro.md"]
    assert "Modding/vi" not in _read("out/INDEX.md")
    assert not [f for f in os.listdir("out") if f.startswith(".")]  # no temp dir left


def test_root_files_pack_does_not_own_survive_a_repack(tmp_path):
    _corpus("docs")
    _write("out", {"SKILL.md": "---\nname: wiki\n---\nhand-written\n",
                   "notes/keep.txt": "mine"})
    assert _pack("docs", "-o", "out", "--layout", "page").exit_code == 0
    assert _pack("docs", "-o", "out", "--layout", "page").exit_code == 0
    assert _read("out/SKILL.md") == "---\nname: wiki\n---\nhand-written\n"
    assert _read("out/notes/keep.txt") == "mine"


def test_pages_without_index_is_not_ours_and_exits_1_before_writing(tmp_path):
    _corpus("docs")
    _write("out", {"pages/mine.md": "user data"})
    result = _pack("docs", "-o", "out", "--layout", "page", "--cross-refs", "--score")
    assert result.exit_code == 1, result.output
    assert "INDEX.md" in result.output
    assert _tree("out") == ["pages/mine.md"]


def test_dry_run_does_not_need_or_touch_pages(tmp_path):
    _corpus("docs")
    _write("out", {"pages/mine.md": "user data"})
    result = _pack("docs", "-o", "out", "--layout", "page", "--dry-run")
    assert result.exit_code == 0, result.output
    assert _tree("out") == ["pages/mine.md"]


def test_a_failed_write_keeps_the_previous_pages(tmp_path, monkeypatch):
    _corpus("docs")
    assert _pack("docs", "-o", "out", "--layout", "page").exit_code == 0
    before = {p: _read(f"out/{p}") for p in _tree("out")}
    _write("docs", {"New.html": _wiki_page("New", "new page")})

    real = page_layout._write_text
    calls = []

    def flaky(path, text):
        calls.append(path)
        if len(calls) == 3:
            raise OSError(28, "No space left on device")
        real(path, text)

    monkeypatch.setattr(page_layout, "_write_text", flaky)
    result = _pack("docs", "-o", "out", "--layout", "page")
    assert result.exit_code == 1
    assert "No space left on device" in result.output
    assert {p: _read(f"out/{p}") for p in _tree("out")} == before
    assert not [f for f in os.listdir("out") if f.startswith(".")]


# ---------------------------------------------------------------------------
# Interactions (ADR-0010 point 5)
# ---------------------------------------------------------------------------

def test_delta_gates_the_run_and_a_run_that_passes_rebuilds_everything(tmp_path):
    _corpus("docs")
    assert _pack("docs", "-o", "out", "--layout", "page", "--delta").exit_code == 0
    second = _pack("docs", "-o", "out", "--layout", "page", "--delta")
    assert "Nothing to do" in second.output
    time.sleep(0.05)
    _write("docs", {"Modding.html": _wiki_page("Modding", "changed words now")})
    third = _pack("docs", "-o", "out", "--layout", "page", "--delta")
    assert third.exit_code == 0, third.output
    assert len(_tree("out/pages")) == 4
    delta = json.loads(_read("out/delta_manifest.json"))
    assert delta["modified"] == ["Modding.html"]
    assert {c["chunk"] for c in delta["chunks_generated"]} == {
        "pages/ActionGroup.md", "pages/Help_Style_guide.md", "pages/Modding.md",
        "pages/Modding/vi.md"}


def test_links_to_packed_pages_point_at_their_files(tmp_path):
    _write("docs", {
        "a.html": ('<main><p>See <a href="sub/b.html#x">B</a>, <a href="gone.html">gone</a>, '
                   '<a href="https://example.com/sub/b.html">web</a> and '
                   '<a href="sub/b.html?x=1">query</a>.</p></main>'),
        "sub/b.html": ('<main><p>Back to <a href="../a.html">A</a>, <a href="c%20(d).html">C</a> '
                       'or <a href="../../out.html">out</a>.</p></main>'),
        "sub/c (d).html": "<main><p>C</p></main>",
    })
    result = _pack("docs", "-o", "out", "--layout", "page")
    assert result.exit_code == 0, result.output
    # A packed page: its file, relative to the linking one. Anything else: as written (#118).
    assert _read("out/pages/a.md").endswith(
        "\n\n[1]: <sub/b.md#x>\n[2]: gone.html\n[3]: https://example.com/sub/b.html\n"
        "[4]: sub/b.html?x=1\n")
    assert _read("out/pages/sub/b.md").endswith(
        "\n\n[1]: <../a.md>\n[2]: <c (d).md>\n[3]: ../../out.html\n")
    words = count_words(_read("out/pages/sub/b.md"), markdown=True)
    assert f"(<pages/sub/b.md>), {words} words" in _read("out/INDEX.md") and words == 6


def _mediawiki_page(name, redirected_from=None, body=""):
    config = {"wgPageName": name, **({"wgRedirectedFrom": redirected_from} if redirected_from else {})}
    return ('<html><head><meta name="generator" content="MediaWiki 1.43.10">'
            f"<script>RLCONF={json.dumps(config)};</script></head>"
            f"<body><main><p>{name} page. {body}</p></main></body></html>")


def test_a_link_to_a_skipped_redirect_alias_points_at_its_target(tmp_path):
    _write("docs", {
        "Map.info.html": _mediawiki_page("Map.info", body='See <a href="Translations.html">translation</a>.'),
        "Translation.html": _mediawiki_page("Translation"),
        "Translations.html": _mediawiki_page("Translation", redirected_from="Translations"),
    })
    result = _pack("docs", "-o", "out", "--layout", "page")
    assert result.exit_code == 0, result.output
    assert "1 redirect alias page(s) skipped" in result.output
    assert _read("out/pages/Map.info.md").endswith(
        "See [translation][1].\n\n[1]: <Translation.md>\n")


def test_cross_refs_point_at_page_paths(tmp_path):
    _write("docs", {
        "a.html": "<html><body><main><p>See <a href=\"sub/b.html\">Beta page</a> now.</p></main></body></html>",
        "sub/b.html": "<html><body><main><p>Back to <a href=\"../a.html\">Alpha</a>.</p></main></body></html>",
    })
    result = _pack("docs", "-o", "out", "--layout", "page", "--cross-refs")
    assert result.exit_code == 0, result.output
    # md writes reference links (#115) to the page files (#118); the marker follows the link.
    assert _read("out/pages/a.md").endswith(
        "[Beta page][1] [-> pages/sub/b.md] now.\n\n[1]: <sub/b.md>\n")
    assert _read("out/pages/sub/b.md").endswith(
        "[Alpha][1] [-> pages/a.md].\n\n[1]: <../a.md>\n")
    refs = json.loads(_read("out/cross_refs.json"))
    assert refs["pages/a.md"]["references_to"] == ["pages/sub/b.md"]
    assert "[->" not in _read("out/INDEX.md")


def test_score_and_report_use_page_paths_as_ids(tmp_path):
    _corpus("docs")
    result = _pack("docs", "-o", "out", "--layout", "page", "--report")
    assert result.exit_code == 0, result.output
    snap = json.loads(_read("out/llm-readiness.json"))
    assert [c["chunk_id"] for c in snap["chunks"]] == [
        "pages/ActionGroup.md", "pages/Help_Style_guide.md", "pages/Modding.md",
        "pages/Modding/vi.md"]
    assert os.path.isfile("out/readiness-report.html")


def test_show_tokens_counts_the_page_files(tmp_path):
    _corpus("docs")
    result = _pack("docs", "-o", "out", "--layout", "page", "--show-tokens")
    assert result.exit_code == 0, result.output
    assert "Failed to count tokens" not in result.output
    assert "tokens" in result.output.lower()


def test_dry_run_projects_pages_without_a_chunk_cap(tmp_path):
    _write("docs", {f"p{i}.html": "<html><body><main><p>" + "w " * 20
                    + "</p></main></body></html>" for i in range(60)})
    result = _pack("docs", "-o", "out", "--layout", "page", "--dry-run", "--score")
    assert result.exit_code == 0, result.output
    assert "Projected pages:       60" in result.output
    assert "(max)" not in result.output and "Oversize" not in result.output
    assert "pages/p0.md" in result.output
    assert not os.path.exists("out")


def test_sync_forwards_layout(tmp_path, monkeypatch):
    from dograpper.commands import sync as sync_mod
    import click

    @click.command()
    def fake_download(**kwargs):
        pass

    monkeypatch.setattr(sync_mod, "_download_cmd", fake_download)
    _corpus("docs")
    result = CliRunner().invoke(cli, ["sync", "https://pzwiki.net/", "-o", "docs",
                                      "--chunks-dir", "out", "--layout", "page"])
    assert result.exit_code == 0, result.output
    assert os.path.isfile("out/INDEX.md")
    assert os.path.isfile("out/pages/Modding/vi.md")


# ---------------------------------------------------------------------------
# One context header per page (ADR-0010 point 4, #85)
# ---------------------------------------------------------------------------

def _header(path):
    text = _read(path)
    assert text.startswith("<!-- dograpper-context-v1\n"), text[:80]
    return json.loads(text.split("<!-- dograpper-context-v1\n", 1)[1].split("\n-->", 1)[0])


def test_context_header_is_written_once_at_the_top_of_each_page(tmp_path):
    _corpus("docs")
    result = _pack("docs", "-o", "out", "--layout", "page", "--context-header", "--score")
    assert result.exit_code == 0, result.output
    index = _read("out/INDEX.md")
    for rel in _tree("out/pages"):
        text = _read(f"out/pages/{rel}")
        assert text.count("dograpper-context-v1") == 1, rel
        data = _header(f"out/pages/{rel}")
        assert set(data) <= {"title", "source", "url", "word_count", "llm_readiness",
                             "schema_version"}, data
        assert f"), {data['word_count']} words" in index
        body = text.split("\n-->\n\n", 1)[1]
        assert data["word_count"] == count_words(body, markdown=True)
    data = _header("out/pages/Help_Style_guide.md")
    assert data["title"] == "Help:Style guide"  # " - PZwiki" suffix stripped
    assert data["source"] == "Help_Style_guide.html"
    assert "url" not in data
    assert data["llm_readiness"]["grade"] in "ABC"
    assert data["schema_version"] == "v1"
    assert list(data)[0] == "title"


def test_header_title_comes_from_an_h1_outside_the_extracted_container(tmp_path):
    _write("docs", {"Item_tag.html": (
        "<html><head></head><body><h1 id=\"firstHeading\">Item tag</h1>"
        "<main><p>Tags group items for recipes and more words.</p></main></body></html>")})
    result = _pack("docs", "-o", "out", "--layout", "page", "--context-header")
    assert result.exit_code == 0, result.output
    assert "Item tag" not in _read("out/pages/Item_tag.md").split("-->", 1)[1]
    assert _header("out/pages/Item_tag.md")["title"] == "Item tag"


def test_header_url_comes_from_the_manifest_or_the_page_marker(tmp_path):
    _corpus("docs")
    with open("docs/.dograpper-manifest.json", "w", encoding="utf-8") as f:
        json.dump({"base_url": "https://pzwiki.net/", "files": {"Modding.html": {
            "url": "https://pzwiki.net/wiki/Modding", "local_path": "Modding.html",
            "size_bytes": 1, "etag": None, "last_modified": None, "mtime": 0}}}, f)
    result = _pack("docs", "-o", "out", "--layout", "page", "--context-header",
                   "--manifest", ".dograpper-manifest.json")  # relative to INPUT_DIR (#95)
    assert result.exit_code == 0, result.output
    assert _header("out/pages/Modding.md")["url"] == "https://pzwiki.net/wiki/Modding"
    assert _header("out/pages/ActionGroup.md")["url"] == "http://pzwiki.net/wiki/ActionGroup"
    assert "url" not in _header("out/pages/Modding/vi.md")
    assert "https://pzwiki.net/wiki/Modding\n" in _read("out/INDEX.md")


def test_a_title_holding_the_comment_end_cannot_close_the_header(tmp_path):
    _write("docs", {"x.html": "<html><head><title>a --> b</title></head>"
                    "<body><main><p>body words</p></main></body></html>"})
    result = _pack("docs", "-o", "out", "--layout", "page", "--context-header")
    assert result.exit_code == 0, result.output
    text = _read("out/pages/x.md")
    assert text.count("-->") == 1
    assert _header("out/pages/x.md")["title"] == "a --> b"
    assert "- [a --> b](<pages/x.md>)" in _read("out/INDEX.md")


def test_headers_add_at_most_five_percent_to_the_page_files(tmp_path):
    sections = "".join(
        f"<h2>Section {s}</h2><h3>Detail {s}</h3><p>" + " ".join(
            f"word{s}x{w}" for w in range(120)) + "</p>" for s in range(8))
    _write("docs", {
        f"Area{i // 10}/Page_{i}.html": (
            f"<!-- Mirrored from pzwiki.net/wiki/Page_{i} by HTTrack Website Copier/3.x "
            f"[XR&CO'2014], Mon, 01 Jan 2024 00:00:00 GMT -->\n<html><head><title>Page {i}"
            f" - PZwiki</title></head><body><h1 id=\"firstHeading\">Page {i}</h1>"
            f"<main>{sections}</main></body></html>")
        for i in range(30)})

    def size(out):
        return sum(os.path.getsize(os.path.join(out, "pages", p)) for p in _tree(f"{out}/pages"))

    assert _pack("docs", "-o", "plain", "--layout", "page").exit_code == 0
    assert _pack("docs", "-o", "hdr", "--layout", "page", "--context-header").exit_code == 0
    assert size("hdr") <= size("plain") * 1.05, (size("plain"), size("hdr"))
