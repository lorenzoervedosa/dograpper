"""lib/httrack/links.py: HTTrack's link extraction, dedup key and link rewriting."""

import logging
import time

import pytest

from dograpper.lib.httrack.links import css_links, page_links, rewrite_links, url_key
from dograpper.lib.httrack.policy import FetchMeta

PAGE = "https://h.test/docs/guide/intro.html"


def urls(html, url=PAGE, **kw):
    return [link.url for link in page_links(html.encode(), url, **kw)]


def metas(html, **kw):
    return {link.url: link.meta for link in page_links(html.encode(), PAGE, **kw)}


@pytest.mark.parametrize("a,b", [
    ("https://h.test/a#x", "https://h.test/a"),
    ("https://h.test//a//b?x=1//2", "https://h.test/a/b?x=1//2"),  # // collapsed before ?
    ("https://h.test/a?b=2&a=1", "https://h.test/a?a=1&b=2"),       # query fields sorted
    ("http://user:pw@H.TEST/a", "https://h.test/a"),                # scheme, login, host case
    ("https://h.test", "https://h.test/"),
])
def test_url_key_matches_httrack_dedup(a, b):
    # htshash.c hash_url_key with -%u: fil_normalized_ex, jump_identification_const
    assert url_key(a) == url_key(b)


def test_url_key_keeps_path_case_and_port():
    assert url_key("https://h.test/A") != url_key("https://h.test/a")
    assert url_key("https://h.test:8443/a") != url_key("https://h.test/a")


def test_links_from_href_and_httrack_attribute_table():
    html = ('<a href="a.html">A</a><area href="/map"><link rel="next" href="../next/">'
            '<img src="i.png" srcset="s1.png 1x, s2.png 2x" data-src="lazy.png">'
            '<video poster="p.jpg" src="v.mp4"></video><iframe src="frame.html"></iframe>'
            '<table background="bg.gif"><object data="obj.swf"></object>'
            '<form action="/submit"></form><a href="#top">top</a>'
            '<a href="mailto:x@h.test">m</a><a href="javascript:go()">j</a>'
            '<a href="https://other.test/x#frag">o</a>')
    assert urls(html) == [
        "https://h.test/docs/guide/a.html", "https://h.test/map",
        "https://h.test/docs/next/", "https://h.test/docs/guide/i.png",
        "https://h.test/docs/guide/s1.png", "https://h.test/docs/guide/s2.png",
        "https://h.test/docs/guide/lazy.png", "https://h.test/docs/guide/p.jpg",
        "https://h.test/docs/guide/v.mp4", "https://h.test/docs/guide/frame.html",
        "https://h.test/docs/guide/bg.gif", "https://h.test/docs/guide/obj.swf",
        "https://other.test/x"]  # action, #fragment, mailto: and javascript: are never links


def test_base_href_applies_to_the_links_after_it():
    html = '<a href="x">x</a><base href="https://h.test/api/"><a href="y">y</a>'
    assert urls(html) == ["https://h.test/docs/guide/x", "https://h.test/api/y"]


@pytest.mark.parametrize("content,want", [
    ("0; URL=/moved.html", "https://h.test/moved.html"),
    ("5;url='next.html'", "https://h.test/docs/guide/next.html"),
    ("10", None),
])
def test_meta_refresh_target_is_a_link(content, want):
    html = f'<meta http-equiv="Refresh" content="{content}"><meta name="x" content="/no">'
    assert urls(html) == ([want] if want else [])


def test_data_src_placeholders_are_not_links():
    html = ('<img data-src="placeholder"><img data-src="{{ img }}">'
            '<img data-srcset="null"><img data-src="real.png">')
    assert urls(html) == ["https://h.test/docs/guide/real.png"]


def test_meta_robots_nofollow_stops_the_links_after_it():
    html = ('<a href="before.html">b</a><meta name="robots" content="noindex, NOFOLLOW">'
            '<a href="after.html">a</a>')
    assert urls(html) == ["https://h.test/docs/guide/before.html"]
    assert len(urls(html, robots=False)) == 2  # --no-robots: meta robots is ignored too


def test_meta_nofollow_needs_name_robots():
    html = '<meta name="googlebot" content="nofollow"><a href="a.html">a</a>'
    assert urls(html) == ["https://h.test/docs/guide/a.html"]


def test_css_urls_in_style_element_and_attribute():
    html = ("<style>@import 'theme.css'; body{background:url(\"bg.png\")}</style>"
            "<div style=\"background: url(dot.gif)\"></div>")
    assert urls(html) == ["https://h.test/docs/guide/theme.css",
                          "https://h.test/docs/guide/bg.png",
                          "https://h.test/docs/guide/dot.gif"]


def test_script_bodies_are_not_scanned():
    assert urls('<script>location.href = "/x.html"; var a = "y.html";</script>') == []


def test_css_file_links_are_classified_by_extension():
    got = css_links(b"@import url(a.css); src: url('f.woff2'); x: url(i.png); y: url(z)",
                    "https://h.test/s/main.css")
    assert [(l.url, l.meta) for l in got] == [
        ("https://h.test/s/a.css", FetchMeta("style", "no-cors", False)),
        ("https://h.test/s/f.woff2", FetchMeta("font", "cors", False)),
        ("https://h.test/s/i.png", FetchMeta("image", "no-cors", False)),
        ("https://h.test/s/z", FetchMeta("", "no-cors", False)),
    ]


def test_fetch_metadata_per_tag_and_attribute():
    # htsfetch.c hts_fetch_classify, link_dest and link_target_dest
    got = metas('<a href="a">a</a><a href="b" target="_blank">b</a><a href="c" target="pane">c</a>'
                '<a href="d" download>d</a><iframe src="e"></iframe><img src="f">'
                '<link rel="stylesheet" href="g"><link rel="next" href="h">'
                '<script type="module" src="i"></script><link rel="preload" as="font" href="j">'
                '<meta http-equiv="refresh" content="0;url=k">')
    base = "https://h.test/docs/guide/"
    assert got == {
        base + "a": FetchMeta("document", "navigate", True),
        base + "b": FetchMeta("document", "navigate", True),
        base + "c": FetchMeta("", "no-cors", True),
        base + "d": FetchMeta("", "no-cors", False),
        base + "e": FetchMeta("iframe", "navigate", False),
        base + "f": FetchMeta("image", "no-cors", False),
        base + "g": FetchMeta("style", "no-cors", False),
        base + "h": FetchMeta("", "no-cors", False),
        base + "i": FetchMeta("script", "cors", False),
        base + "j": FetchMeta("font", "cors", False),
        base + "k": FetchMeta("document", "navigate", False),
    }


def test_links_in_a_frame_page_and_under_base_target():
    assert metas('<a href="a">a</a>', frame="iframe")[
        "https://h.test/docs/guide/a"].dest == "iframe"
    # a <base target> anywhere sends every link without target to an unknown frame
    assert metas('<a href="a">a</a><base target="main">')[
        "https://h.test/docs/guide/a"].dest == ""


def _rewrite(html, local, page=PAGE, path=None):
    path = path or "/out/h.test/docs/guide/intro.html"
    keys = {url_key(u): p for u, p in local.items()}
    return rewrite_links(html.encode(), page, path, keys).decode()


def test_rewrite_points_saved_links_at_local_files():
    local = {"https://h.test/docs/guide/a.html": "/out/h.test/docs/guide/a.html",
             "https://h.test/docs/": "/out/h.test/docs/index.html",
             "https://h.test/docs/api/x?b=2&a=1": "/out/h.test/docs/api/x9a1b.html"}
    html = ('<a class="n" href="a.html#s">A</a> <a href=\'/docs/\'>D</a> '
            '<a href="../api/x?a=1&amp;b=2">X</a>')
    assert _rewrite(html, local) == ('<a class="n" href="a.html#s">A</a> '
                                     '<a href="../index.html">D</a> '
                                     '<a href="../api/x9a1b.html">X</a>')


def test_rewrite_makes_other_links_absolute_and_blanks_base():
    html = ('<base href="https://h.test/docs/guide/"><a href="b.html">B</a>'
            '<a href="https://other.test/x">O</a><a href="#top">T</a><a href="mailto:m@h">M</a>')
    assert _rewrite(html, {}) == ('<base href=""><a href="https://h.test/docs/guide/b.html">B</a>'
                                  '<a href="https://other.test/x">O</a><a href="#top">T</a>'
                                  '<a href="mailto:m@h">M</a>')


def test_rewrite_srcset_and_meta_refresh_parts():
    local = {"https://h.test/docs/guide/next.html": "/out/h.test/docs/guide/next.html"}
    html = ('<img srcset="s1.png 1x, s2.png 2x">'
            '<meta http-equiv="refresh" content="3; URL=next.html">')
    assert _rewrite(html, local) == (
        '<img srcset="https://h.test/docs/guide/s1.png 1x, https://h.test/docs/guide/s2.png 2x">'
        '<meta http-equiv="refresh" content="3; URL=next.html">')


def test_rewrite_keeps_every_other_byte():
    body = ("<!doctype html>\n<p>café &amp; <b>x</b></p>\n<a  HREF = /x >x</a>\n"
            "<!-- <a href=/y> --><script>var s = '<a href=/z>';</script>").encode() + b"\xff"
    out = rewrite_links(body, PAGE, "/out/h.test/docs/guide/intro.html",
                        {url_key("https://h.test/x"): "/out/h.test/x.html"})
    assert out == body.replace(b"= /x >", b'= "../../x.html" >')
    no_links = b"<p>plain \xe9 text</p>"
    assert rewrite_links(no_links, PAGE, "/o/p.html", {}) is no_links


def test_rewritten_names_escape_percent_and_hash():
    local = {"https://h.test/docs/guide/100%25": "/out/h.test/docs/guide/100%.html",
             "https://h.test/docs/guide/C%23": "/out/h.test/docs/guide/C#.html"}
    html = '<a href="100%25">a</a><a href="C%23">b</a>'
    assert _rewrite(html, local) == '<a href="100%25.html">a</a><a href="C%23.html">b</a>'


@pytest.mark.parametrize("body", [
    b"<a href=" * 40000,
    b"<meta name=robots content=" + b"x" * 400000,
    b"<style>" + b"url(" * 100000,
    b"<style>" + b"@import '" * 100000,
    b"<img srcset='" + b"a " * 200000 + b"'>",
], ids=["unclosed-tags", "meta-robots", "css-url", "css-import", "srcset"])
def test_parsing_is_linear_on_hostile_pages(body):
    t0 = time.perf_counter()
    page_links(body, PAGE)
    rewrite_links(body, PAGE, "/o/p.html", {})
    assert time.perf_counter() - t0 < 2.0


def test_rewrite_relative_path_uses_forward_slashes(tmp_path):
    page = str(tmp_path / "h.test" / "a" / "p.html")
    target = str(tmp_path / "h.test" / "b" / "q.html")
    out = rewrite_links(b'<a href="/b/q">q</a>', "https://h.test/a/p", page,
                        {url_key("https://h.test/b/q"): target})
    assert out == b'<a href="../b/q.html">q</a>'


def test_nofollow_log_line_redacts_the_page_url(caplog):
    # the URL logged can come from the page itself (<base href>): login and controls go
    html = ('<base href="https://user:secret@h.test/\x1b[2Jdocs/">'
            '<meta name="robots" content="nofollow"><a href="a">a</a>')
    with caplog.at_level(logging.INFO, logger="dograpper.lib.httrack.links"):
        assert page_links(html.encode(), PAGE) == []
    [line] = [r.getMessage() for r in caplog.records]
    assert "h.test" in line and "secret" not in line and "user" not in line
    assert "\x1b" not in line and "%1b[2jdocs" in line.lower()
