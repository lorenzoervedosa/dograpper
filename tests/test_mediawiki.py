"""MediaWiki page cleanup (#88): chrome dropped before the generic extractor.

Every page here is synthesized markup written for this repo in the shape of
MediaWiki 1.43 with the Citizen skin (ADR-0009 fixture rule: no third-party
page is committed).
"""

import hashlib
import json
import os

import pytest

from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.utils.content_extractor import extract_content
from dograpper.utils.html_stripper import strip_html
from dograpper.utils.mediawiki import clean, is_mediawiki, page_metadata

MEDIAWIKI = '<meta name="generator" content="MediaWiki 1.43.10">'

EDIT_LINK = ('<small><span class="plainlinks"><a rel="nofollow" class="external text" '
             'href="https://wiki.example/w/index.php?title=Sample_page&amp;veaction=edit">Edit</a> '
             '(<a rel="nofollow" class="external text" '
             'href="https://wiki.example/w/index.php?title=Special:CreateAccount">Create account</a>)'
             '</span></small>')


def _mbox(template, lead, *collapsible, toggle=None):
    """A message box; ``toggle`` names its ``mw-customtoggle-mbox-*`` (maintenance boxes only)."""
    parts = "".join(f'<div class="mw-collapsible" id="mw-customcollapsible-mbox-{toggle}">{c}</div>'
                    for c in collapsible)
    if toggle:
        parts += f'<div class="toggle mw-customtoggle-mbox-{toggle}" title="Show/Hide"></div>'
    return ('<div class="mbox" style="border:1px solid #ff8010"><div style="background-color:#ff8010"></div>'
            '<div><span class="mw-default-size" typeof="mw:File">'
            f'<a href="https://wiki.example/wiki/Template:{template}" title="Template:{template}">'
            '<img src="icon.png" width="64" height="64" class="mw-file-element"/></a></span></div>'
            f'<div><div style="font-weight:bold">{lead}</div>{parts}</div></div>')


VERSION_BOX = _mbox(
    "Page version",
    "This page was last updated for an <i>older</i> version of the current build "
    '(<a href="https://wiki.example/wiki/Build_42.10.0" title="Build 42.10.0">42.10.0</a>).',
    'The current stable version is <a href="Build_42.22.2.html">42.22.2</a>, '
    "so information on this page may be inaccurate.",
    f"Help get this page updated by adding any missing content. {EDIT_LINK}",
    toggle="version")
STUB_BOX = _mbox("Stub", "This section may need more content.",
                 f"Editors are encouraged to add new material to the page. {EDIT_LINK}",
                 toggle="stub")
OUTDATED_BOX = _mbox("Outdated", "This article may be outdated.",
                     f"Editors are encouraged to update this article. {EDIT_LINK}",
                     toggle="outdated")
NOTE_BOX = _mbox("Note", "Prefer local variables: a global can clash with another mod.")
NAVBOX = (
    '<div class="navbox theme-blue" style="clear: both;">'
    '<div class="mw-customtoggle-navbox-modding" title="Show / Hide">'
    '<a href="https://wiki.example/wiki/Category:Modding">Modding</a></div>'
    '<div class="mw-collapsible mw-collapsed" id="mw-customcollapsible-navbox-modding">'
    '<div class="navbox-section"><div><div class="navbox-item">'
    '<div><p><a href="Guides.html">Modding guides</a></p></div>'
    '<div><p><a href="Start.html">Getting started</a> • <a href="Structure.html">Mod structure</a>'
    ' • <a href="Upload.html">Uploading mods</a></p></div>'
    # A nested navbox, as on item pages.
    '<div class="navbox theme-red"><div class="navbox-item"><p>'
    '<a href="Axe.html">Axe</a> • <a href="Cleaver.html">Meat cleaver</a></p></div></div>'
    '</div></div></div></div></div>'
)


def _heading(text, anchor):
    return (f'<div class="mw-heading mw-heading2"><h2 id="{anchor}">{text}</h2>'
            '<span class="mw-editsection"><span class="mw-editsection-bracket">[</span>'
            f'<a href="https://wiki.example/w/index.php?title=Sample_page&amp;action=edit&amp;section=1" '
            f'title="Edit section: {text}"><span>edit</span></a>'
            '<span class="mw-editsection-bracket">]</span></span></div>')


BODY = (VERSION_BOX + STUB_BOX + NOTE_BOX
        + '<p>ActionGroups collect the action states of one animation set.</p>'
        + _heading("Usage", "Usage")
        + '<p>Call the loader once per session, before the first state change.</p>'
        + OUTDATED_BOX + NAVBOX
        + '<p>Text after the navigation box is page content.</p>')


def _hidden_categories(*names):
    links = "".join(f'<li><a href="https://wiki.example/wiki/Category:{n.replace(" ", "_")}" '
                    f'title="Category:{n}">{n}</a></li>' for n in names)
    return ('<div id="mw-hidden-catlinks" class="mw-hidden-catlinks mw-hidden-cats-hidden">'
            f'Hidden categories: <ul>{links}</ul></div>')


def _page(body=BODY, generator=MEDIAWIKI, title="Sample page", page_name="Sample_page",
          categories=""):
    config = json.dumps({"wgPageName": page_name, "wgTitle": title})
    return (
        f'<!DOCTYPE html>\n<html lang="en"><head><meta charset="UTF-8">\n<title>{title} - Example Wiki</title>\n'
        f'<script>RLCONF={config};</script>\n{generator}\n</head>\n'
        '<body><main class="mw-body" id="content">\n'
        f'<header class="mw-body-header"><h1 id="firstHeading">{title}</h1></header>\n'
        '<div id="bodyContent"><div id="contentSub"><div id="mw-content-subtitle"></div></div>\n'
        '<div id="mw-content-text" class="mw-body-content">'
        f'<div class="mw-content-ltr mw-parser-output" lang="en" dir="ltr">{body}</div></div></div>\n'
        f'</main>\n<footer><div id="catlinks" class="catlinks">{categories}</div></footer>\n'
        '</body></html>\n')


def _text(html):
    return strip_html(extract_content(html))


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------

def test_detected_by_the_generator_meta():
    assert is_mediawiki(_page())
    assert not is_mediawiki(_page(generator='<meta name="generator" content="Sphinx 7.2">'))
    assert not is_mediawiki(_page(generator=""))


# ---------------------------------------------------------------------------
# Chrome dropped
# ---------------------------------------------------------------------------

def test_navboxes_nested_ones_included_are_dropped():
    text = _text(_page())
    for chrome in ("Modding guides", "Getting started", "Mod structure", "Meat cleaver"):
        assert chrome not in text
    assert "Text after the navigation box is page content." in text


def test_edit_section_links_are_dropped():
    text = _text(_page())
    assert "Usage" in text
    assert "[" not in text and "edit" not in text.split()


def test_maintenance_boxes_are_dropped_with_their_edit_links():
    text = _text(_page(STUB_BOX + OUTDATED_BOX + "<p>Body.</p>"))
    assert "may need more content" not in text
    assert "may be outdated" not in text
    assert "Create account" not in text


def test_the_version_box_leaves_the_text_once_its_version_is_read():
    text = _text(_page())
    assert "42.10.0" not in text and "current stable version" not in text
    assert "Create account" not in text
    assert page_metadata(_page()) == {"version": "42.10.0", "version_status": "outdated"}


def test_a_note_box_has_no_maintenance_toggle_and_stays():
    assert "Prefer local variables: a global can clash with another mod." in _text(_page())


def test_page_content_around_the_chrome_is_kept():
    text = _text(_page())
    assert "ActionGroups collect the action states of one animation set." in text
    assert "Call the loader once per session, before the first state change." in text


def test_markup_outside_the_dropped_elements_is_kept_byte_for_byte():
    page = _page()
    cleaned = clean(page)
    for kept in ('<p>ActionGroups collect the action states of one animation set.</p>',
                 NOTE_BOX, '<h2 id="Usage">Usage</h2>', '<title>Sample page - Example Wiki</title>'):
        assert kept in cleaned
    for dropped in (NAVBOX, VERSION_BOX, STUB_BOX, OUTDATED_BOX, 'mw-editsection'):
        assert dropped not in cleaned


def test_a_box_whose_end_tag_never_comes_is_kept():
    # Nothing closes it before the end of the document: dropping it would eat the page.
    page = _page() + '<div class="navbox"><p>Unclosed box text.</p>'
    assert clean(page).endswith('<div class="navbox"><p>Unclosed box text.</p>')


def test_clean_leaves_a_non_mediawiki_page_alone():
    page = _page(generator="")
    assert clean(page) is page


# ---------------------------------------------------------------------------
# Page version as metadata
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("lead, version, status", [
    ("This page has been revised for the current stable version (42.22.2).", "42.22.2", "current"),
    ("This page was last updated for an <i>older</i> version of the current build (42.10.0).",
     "42.10.0", "outdated"),
    ("This page was last updated for an <i>older</i> version (41.78.19).", "41.78.19", "older-build"),
])
def test_each_banner_wording_gives_the_version_and_its_status(lead, version, status):
    page = _page(_mbox("Page version", lead, "Help by adding any missing content.", toggle="version")
                 + "<p>Body text.</p>")
    assert page_metadata(page) == {"version": version, "version_status": status}
    assert version not in _text(page)


def test_the_banner_wins_over_the_hidden_version_categories():
    page = _page(categories=_hidden_categories("Version 42.21.0", "Version 42.10.0", "Stub articles"))
    assert page_metadata(page) == {"version": "42.10.0", "version_status": "outdated"}


def test_without_a_banner_the_first_hidden_version_category_gives_the_version():
    cats = _hidden_categories("Stub articles", "Version 42.21.0", "Version history")
    assert page_metadata(_page("<p>Body text.</p>", categories=cats)) == {"version": "42.21.0"}
    # "Version history" names no version
    assert page_metadata(_page("<p>Body text.</p>", categories=_hidden_categories("Version history"))) == {}


def test_a_version_box_with_unknown_wording_stays_in_the_text():
    page = _page(_mbox("Page version", "Valid for build 42 (see the changelog).", toggle="version")
                 + "<p>Body text.</p>")
    assert page_metadata(page) == {}
    assert "Valid for build 42 (see the changelog)." in _text(page)


def test_a_page_from_another_generator_has_no_metadata():
    assert page_metadata(_page(generator="", categories=_hidden_categories("Version 42.21.0"))) == {}


# ---------------------------------------------------------------------------
# Non-MediaWiki pages: byte-identical to the generic extractor of before #88
# ---------------------------------------------------------------------------

# sha256 of extract_content() for _page() under another generator (or none),
# recorded on the base branch (3fc1a41) before the MediaWiki adapter existed.
GENERIC_EXTRACT_SHA256 = "aa2b2696d2812b70454c0b4ea73eb3c05581c9c639b0888760d5cce073ac1a11"


def test_a_page_from_another_generator_is_extracted_exactly_as_before():
    for generator in ('<meta name="generator" content="Sphinx 7.2">', ""):
        html = extract_content(_page(generator=generator))
        text = strip_html(html)
        assert "Mod structure" in text and "Edit (Create account)" in text
        assert "[" in text and "may be outdated" in text
        assert hashlib.sha256(html.encode()).hexdigest() == GENERIC_EXTRACT_SHA256


# ---------------------------------------------------------------------------
# Pack
# ---------------------------------------------------------------------------

def test_pack_drops_the_chrome_from_mediawiki_pages_only(tmp_path):
    src = tmp_path / "wiki"
    src.mkdir()
    (src / "Sample_page.html").write_text(_page(), encoding="utf-8")
    (src / "Other.html").write_text(_page(generator="", title="Other"), encoding="utf-8")
    out = tmp_path / "out"
    result = CliRunner().invoke(cli, ["pack", str(src), "-o", str(out), "--layout", "page"],
                                catch_exceptions=False)
    assert result.exit_code == 0, result.output
    wiki = (out / "pages" / "Sample_page.md").read_text(encoding="utf-8")
    other = (out / "pages" / "Other.md").read_text(encoding="utf-8")
    assert "Mod structure" not in wiki and "may be outdated" not in wiki
    assert "Mod structure" in other and "may be outdated" in other
    assert os.path.isfile(out / "INDEX.md")


def _headers(text):
    return [json.loads(block.split("\n-->")[0])
            for block in text.split("<!-- dograpper-context-v1\n")[1:]]


def test_page_layout_header_carries_the_version_instead_of_the_text(tmp_path):
    src = tmp_path / "wiki"
    src.mkdir()
    (src / "Sample_page.html").write_text(_page(), encoding="utf-8")
    (src / "Other.html").write_text(_page(generator="", title="Other"), encoding="utf-8")
    out = tmp_path / "out"
    result = CliRunner().invoke(cli, ["pack", str(src), "-o", str(out), "--layout", "page",
                                      "--context-header"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    wiki = (out / "pages" / "Sample_page.md").read_text(encoding="utf-8")
    [header] = _headers(wiki)
    assert list(header) == ["title", "source", "version", "version_status", "word_count",
                            "schema_version"]
    assert (header["version"], header["version_status"]) == ("42.10.0", "outdated")
    assert "42.10.0" not in wiki.split("\n-->\n", 1)[1]
    [other] = _headers((out / "pages" / "Other.md").read_text(encoding="utf-8"))
    assert "version" not in other and "version_status" not in other


def test_dedup_exact_keeps_the_version_of_every_page_with_the_same_banner(tmp_path):
    # #89: as text, an identical banner survived on the first page only.
    src = tmp_path / "wiki"
    src.mkdir()
    for name in ("Alpha", "Beta", "Gamma"):
        body = VERSION_BOX + f"<p>{name} has its own body text, long enough for dedup to look at it.</p>"
        (src / f"{name}.html").write_text(_page(body, title=name, page_name=name), encoding="utf-8")
    out = tmp_path / "out"
    result = CliRunner().invoke(cli, ["pack", str(src), "-o", str(out), "--context-header",
                                      "--dedup", "exact", "--max-words-per-chunk", "1",
                                      "--max-chunks", "100", "--no-index"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    headers = [h for f in sorted(os.listdir(out)) if f.endswith(".md")
               for h in _headers((out / f).read_text(encoding="utf-8"))]
    assert {h["source"]: h["version"] for h in headers} == {
        "Alpha.html": "42.10.0", "Beta.html": "42.10.0", "Gamma.html": "42.10.0"}


def test_jsonl_records_carry_the_version_of_a_mediawiki_page_only(tmp_path):
    src = tmp_path / "wiki"
    src.mkdir()
    (src / "Sample_page.html").write_text(_page(), encoding="utf-8")
    (src / "Other.html").write_text(_page(generator="", title="Other"), encoding="utf-8")
    out = tmp_path / "out"
    result = CliRunner().invoke(cli, ["pack", str(src), "-o", str(out), "--format", "jsonl",
                                      "--context-header"], catch_exceptions=False)
    assert result.exit_code == 0, result.output
    records = {}
    for f in sorted(os.listdir(out)):
        if f.endswith(".jsonl"):
            for line in (out / f).read_text(encoding="utf-8").splitlines():
                record = json.loads(line)
                records.setdefault(record["source"], []).append(record)
    wiki, other = records["Sample_page.html"], records["Other.html"]
    assert [(r["version"], r["version_status"]) for r in wiki] == [("42.10.0", "outdated")] * len(wiki)
    assert "42.10.0" not in "".join(r["content"] for r in wiki)
    assert all("version" not in r and "version_status" not in r for r in other)
