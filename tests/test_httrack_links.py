"""lib/httrack/links.py: HTTrack's link extraction, dedup key and link rewriting."""

import logging

import pytest

from dograpper.lib.httrack import jsscan as J
from dograpper.lib.httrack.links import (
    css_links, page_links, rewrite_file_links, rewrite_links, script_links, url_key)
from dograpper.lib.httrack.policy import FetchMeta
from tests.linearity import assert_linear

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


def test_script_bodies_are_not_scanned_with_both_scans_off():
    # --no-parse-scripts --no-extended-parsing (HTTrack -j4 -%P0): a script names no link
    assert urls('<script>location.href = "/x.html"; var a = "y.html";</script>',
                parse_scripts=False, extended_parsing=False) == []


def test_script_bodies_are_scanned_by_default():
    # -j: hts_js_scan_link takes .href= (htsparse.c:603-604); -%P: the string after "="
    # names a file (htsparse.c:2180-2266); both on by default (htslib.c:5406, 5425)
    assert urls('<script>location.href = "/x.html"; var a = "y.html";</script>') == [
        "https://h.test/x.html", "https://h.test/docs/guide/y.html"]


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


@pytest.mark.parametrize("build, n", [
    (lambda k: b"<a href=" * k, 10000),
    (lambda k: b"<meta name=robots content=" + b"x" * k, 1000000),
    (lambda k: b"<style>" + b"url(" * k, 12000),
    (lambda k: b"<style>" + b"@import '" * k, 12000),
    (lambda k: b"<img srcset='" + b"a " * k + b"'>", 50000),
], ids=["unclosed-tags", "meta-robots", "css-url", "css-import", "srcset"])
def test_parsing_is_linear_on_hostile_pages(build, n):
    def parse(body):
        page_links(body, PAGE)
        rewrite_links(body, PAGE, "/o/p.html", {})
    assert_linear(build, parse, n)


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


# --- -j (script scan) and -%P (extended parsing), ported from htsparse.c -------------------
# The tables below are HTTrack's own self-test vectors (src/htsparse_selftest.c at
# xroche/httrack@06ada4a): text, byte offset of the cursor, in a tag, in CSS, found, and the
# URL's offset from the cursor and length.

def _bytes_at(raw: bytes, at: int) -> tuple[str, int]:
    return raw.decode("utf-8", "surrogateescape"), len(raw[:at].decode("utf-8", "surrogateescape"))


JSSCAN = [  # parse_selftest_jsscan, htsparse_selftest.c:661-738
    (b'x.src="pic.gif";', 1, False, False, True, 6, 7),
    (b'w.open("pic.gif",z)', 1, False, False, True, 7, 7),
    (b'x.SRC="pic.gif";', 1, False, False, True, 6, 7),
    (b'x.open("GET",u)', 1, False, False, False, 0, 0),
    (b'x.open("text/html")', 1, False, False, False, 0, 0),
    (b'url(pic.png)', 0, False, True, True, 4, 7),
    (b'url(pic.png)', 0, False, False, False, 0, 0),
    (b'@import "a.css" screen;', 1, False, False, True, 8, 5),
    (b' location="a";', 1, False, False, True, 10, 1),
    (b'alocation="a";', 1, False, False, False, 0, 0),
    (b'aurl="pic.gif";', 1, False, False, False, 0, 0),
    (b'myurl("pic.gif")', 2, False, False, False, 0, 0),
    (b'var myurl = "hello world";', 6, False, False, False, 0, 0),
    (b'var baseurl = "jquery7";', 8, False, False, False, 0, 0),
    (b'var a_url = "a.gif";', 6, False, False, False, 0, 0),
    (b'$url("a.gif")', 1, False, False, False, 0, 0),
    (b'\303\251url("a.gif")', 2, False, False, False, 0, 0),
    (b':url(a.png)', 1, False, True, True, 4, 5),
    (b',url(a.png)', 1, False, True, True, 4, 5),
    (b'(url(a.png)', 1, False, True, True, 4, 5),
    (b' url(a.png)', 1, False, True, True, 4, 5),
    (b'\302\240url(a.png)', 2, False, True, True, 4, 5),
    (b'content:"x"url(a.png)', 11, False, True, True, 4, 5),
    (b"`url('${t}')`", 1, False, False, False, 0, 0),
    (b"`url('/r/r1')`", 1, False, False, True, 5, 5),
    (b"`url('/a/${t}.png')`", 1, False, False, False, 0, 0),
    (b'o.url("/t/x.gif")', 1, False, False, True, 6, 8),
    (b'o.myurl("/t/x")', 1, False, False, False, 0, 0),
    (b"content:'x'url(a.png)", 11, False, True, True, 4, 5),
    (b"'url('a.gif')", 1, False, False, True, 5, 5),
    (b'"url("a.gif")', 1, False, False, True, 5, 5),
    (b'a_url("a.gif")', 2, False, False, False, 0, 0),
    (b'\343\200\200url(a.png)', 3, False, True, True, 4, 5),
    (b'\342\200\257url(a.png)', 3, False, True, True, 4, 5),
    (b'\341\273\277url(a.png)', 3, False, True, False, 0, 0),
    (b'\240url(a.png)', 1, False, True, True, 4, 5),
    (b'\341\232\200url("a.png")', 3, False, False, True, 5, 5),
    (b'\341\232\200url(a.png)', 3, False, True, False, 0, 0),
    (b'x\341\232\200url(a.png)', 4, False, True, False, 0, 0),
    (b'\357\273\277url("a.png")', 3, False, False, True, 5, 5),
    (b'\357\273\277url(a.png)', 3, False, True, False, 0, 0),
    (b'x\357\273\277url(a.png)', 4, False, True, False, 0, 0),
    (b'image-url(a.png)', 6, False, True, False, 0, 0),
    (b'image-url("a.png")', 6, False, False, True, 5, 5),
    (b'-url(a.png)', 1, False, True, False, 0, 0),
    (b'\342\201\237url(a.png)', 3, False, True, True, 4, 5),
    (b'\342\200\250url(a.png)', 3, False, True, True, 4, 5),
    (b'\342\200\251url(a.png)', 3, False, True, True, 4, 5),
    (b'\342\200\200url(a.png)', 3, False, True, True, 4, 5),
    (b'\342\200\212url(a.png)', 3, False, True, True, 4, 5),
    (b'\342\200\213url(a.png)', 3, False, True, False, 0, 0),
    (b'\342\200\214url(a.png)', 3, False, True, False, 0, 0),
    (b'new URL("a.gif")', 4, False, False, True, 5, 5),
    (b'x.src=",a.gif";', 1, False, False, False, 0, 0),
    (b'x.src="";', 1, False, False, False, 0, 0),
    (b"x.src='a.gif'\"", 1, True, False, True, 6, 5),
    (b'import x from"./x.js";', 9, False, False, True, 5, 6),
    (b'import x from "../x.js";', 9, False, False, True, 6, 7),
    (b'from"/x.js";', 0, False, False, True, 5, 5),
    (b'export{a}from"./x.js";', 9, False, False, True, 5, 6),
    (b'from"https://h/x.js";', 0, False, False, True, 5, 14),
    (b'import "https://h/x.js";', 0, False, False, True, 8, 14),
    (b'from"./x.js?v=1";', 0, False, False, True, 5, 10),
    (b'from"@scope/pkg";', 0, False, False, False, 0, 0),
    (b'from"..x.js";', 0, False, False, False, 0, 0),
    (b'from".config/a.js";', 0, False, False, False, 0, 0),
    (b'xfrom"./x.js";', 1, False, False, False, 0, 0),
    (b'x.from("./x.js")', 2, False, False, False, 0, 0),
    (b'var copyFrom = "hello world";', 8, False, False, False, 0, 0),
    (b'$from"./x.js";', 1, False, False, False, 0, 0),
    (b'\303\251from"./x.js";', 2, False, False, False, 0, 0),
    (b'\302\240from"./x.js";', 2, False, False, True, 5, 6),
]


@pytest.mark.parametrize("raw,at,in_tag,in_css,want,offset,length", JSSCAN)
def test_js_scan_link_matches_httrack_selftest(raw, at, in_tag, in_css, want, offset, length):
    text, p = _bytes_at(raw, at)
    got = J._js_link(text, p, J.Ctx(css=in_css, in_tag=in_tag, tag_lastc='"'))
    assert (got is not None) == want
    if want:
        assert (got[0] - p, got[1] - got[0]) == (offset, length)


@pytest.mark.parametrize("text,length,end,in_tag,entity", [
    # htsparse_selftest.c:804-822: a quoted url() may hold ")", a style attribute may
    # write its quotes as entities, a <style> block does not decode them
    ("url(a.png)", 5, ")", False, ""),
    ("url('a (2).png')", 9, "", False, ""),
    ('url("a (2).png")', 9, "", False, ""),
    ("url(&quot;a (2).png&quot;)", 9, "", True, '"'),
    ("url(&#39;a.png?b&amp;c&#x27;)", 13, "", True, "'"),
    ("url(&quot;it&#39;s.png&#34;)", 12, "", True, '"'),
    ("url(&quot;a.png&quot;)", 17, ")", False, ""),
    ("url(&APOS;a.png&APOS;)", 17, ")", True, ""),
])
def test_css_url_ends_as_httrack_ends_it(text, length, end, in_tag, entity):
    got = J._js_link(text, 0, J.Ctx(css=True, in_tag=in_tag, tag_lastc='"'))
    assert (got[1] - got[0], got[2], got[3]) == (length, end, entity)


@pytest.mark.parametrize("text", [  # htsparse_selftest.c:825-827
    "url(&quot;a.png&#39;)", 'url(&quot;a.png")', "url(&quot;a.png)>b&quot;)"])
def test_unclosed_entity_url_is_no_link(text):
    assert J._js_link(text, 0, J.Ctx(css=True, in_tag=True, tag_lastc='"')) is None


@pytest.mark.parametrize("s,after,inscript,want", [  # parse_selftest_dirtylink, :204-246
    ("/", ")", True, False), ("image/", ")", True, False), ("Alt+/", ")", True, False),
    ("$&/", ")", True, False), ("/#top", ")", True, True), ("/?q=1", ")", True, True),
    ("img/#x", ")", True, True), ("a/b/", ")", True, True), ("/a/b/", ")", True, True),
    ("a/b/", ")", False, False), ("http://ex.co/", ")", False, True),
    ("HTTP://ex.co/", ")", False, True), ("ftp://ex.co/", ")", False, True),
    ("mailto:a@b.c", ")", True, False), ("javascript:void(0)", ")", True, False),
    ("a.gif", "+", True, True), ("a.php", "+", True, True), ("page.html", ")", False, True),
    ("page.html#f", ")", False, True), ("http://ex.co/", "+", True, False),
    ("a/b/", "+", True, False), ("foobar@aol.com", ")", True, False),
    (".gif", ")", True, False), ("a*.gif", ")", True, False), ("a,b.gif", ")", True, False),
    ("<b>.gif", ")", True, False), ("#f", ")", True, False), ("?q=1", ")", True, False),
    ("", ")", True, False), ("a b.gif", ")", False, False), ("a b.gif", ")", True, True),
])
def test_dirty_link_is_url_matches_httrack_selftest(s, after, inscript, want):
    assert J._dirty_is_url(s, after, inscript) is want


def test_dirty_link_length_cap():
    # htsparse_selftest.c:286-296: a string at HTS_URLMAXSIZE gets no verdict, one under does
    big = "a" * (J.URL_MAX - 4) + ".gif"
    assert not J._dirty_is_url(big, ")", True) and J._dirty_is_url(big[1:], ")", True)


@pytest.mark.parametrize("before", ["", 'id="x" ', "alt = 'y'\t"])
@pytest.mark.parametrize("gap", ["", " ", "\t", "  "])
@pytest.mark.parametrize("quote", ['"', "'"])
@pytest.mark.parametrize("name,want", [  # parse_selftest_tagattr, htsparse_selftest.c:1114-1121
    *[(n, True) for n in ("href", "src", "data-src", "srcset", "background", "longdesc",
                          "xmlnsx", "onclick")],
    *[(n, False) for n in ("id", "name", "alt", "class", "title", "type", "style", "xmlns",
                           "xmlns:xlink")]])
def test_dirty_attr_name_and_refusal(before, gap, quote, name, want):
    # tagattr_case, htsparse_selftest.c:946-980: the name before "=" before the quote
    text = f"<a {before}{name}{gap}={gap}{quote}x.gif\">"
    q = len(f"<a {before}{name}{gap}={gap}")
    assert J._attr_name(text, q, 0) == (len(f"<a {before}"), len(f"<a {before}{name}"))
    assert (not J._refused(name)) is want


@pytest.mark.parametrize("before,want", [  # parse_selftest_jsimport, htsparse_selftest.c:889-917
    ("import(", True), ("import (", True), ("import\t(\n", True), ("await import(", True),
    ("e=>import(", True), (";import(", True), ("preimport(", False), ("foo.import(", False),
    ("_import(", False), ("$import(", False), ("2import(", False), ('a="import("', False),
    ("(", False), ("import", False), ("importx(", False), ("import()(", False), ("", False),
    ("mport(", False), ("\u00a0import(", True), ("\u2028import(", True),
    ("caf\u00e9import(", False), ("// import(", True), ("/* import(", True)])
def test_dynamic_import_argument(before, want):
    text = before + '"x")'
    assert J._import_arg(text, len(before)) is want


def test_script_keywords_and_strings():
    # hts_js_scan_link keywords (htsparse.c:589-669) and -%P strings (2180-2266) in <script>
    html = ('<script>img.src = "a.gif"; document.location="b.html"; w.open("c.html", "n");'
            ' x.open("GET", "/api"); import "./m.js"; import y from "./n.js";'
            ' import z from "pkg"; new URL("d.html"); f("e.png", g); h = "f.html" + i;'
            ' j = "dir/" + k; l = "/api/v1/"; m = "image/";</script>')
    base = "https://h.test/docs/guide/"
    assert urls(html) == [base + u for u in (
        "a.gif", "b.html", "c.html", "m.js", "n.js", "d.html", "e.png", "f.html")] + [
        "https://h.test/api/v1/"]


def test_comments_and_strings_hide_keywords():
    # the automaton (htsparse.c:1229-1254): no keyword is tried in a comment or a string;
    # a // in a stylesheet file is no comment (htsparse.c:132-135, #139)
    html = ('<script>// x.src="a.gif"\n/* y.src="b.gif" */ s = \'z.src="c.gif"\';'
            ' t.src="d.gif";</script>')
    assert urls(html, extended_parsing=False) == ["https://h.test/docs/guide/d.gif"]
    css = "a{b:url(http://x.test/a.png)} c{d:url(b.png)}"
    assert [l.url for l in css_links(css.encode(), "https://h.test/s.css")] == [
        "http://x.test/a.png", "https://h.test/b.png"]
    # the fix is for stylesheet files only: in a <style> block the // of http:// still opens
    # a comment to the end of the line, so HTTrack misses the second url()
    assert urls(f"<style>{css}</style>") == ["http://x.test/a.png"]


def test_event_handlers_style_and_javascript_urls_are_scripts():
    # onXxx= from the table or with an upper-case X, style= as CSS (htsparse.c:1945-1980);
    # a javascript: URL is parsed as a script (htsparse.c:2366-2386)
    html = ("<img onMouseOver=\"this.src='a.gif'\" onPointerDown=\"x.src='b.gif'\""
            " onpointerup=\"x.src='no.gif'\" style=\"background:url(c.png)\">"
            "<a href=\"javascript:location='d.html'\">d</a>")
    got = metas(html, extended_parsing=False)
    base = "https://h.test/docs/guide/"
    assert list(got) == [base + u for u in ("a.gif", "b.gif", "c.png", "d.html")]
    # a script's link carries no fetch metadata, a stylesheet's goes by its path
    assert got[base + "a.gif"] == FetchMeta("", "no-cors", False)
    assert got[base + "c.png"] == FetchMeta("image", "no-cors", False)


def test_extended_parsing_in_tags():
    # -%P in a tag: a quoted value after "=" naming a file, unless its attribute never holds
    # a link (hts_nodetect, xmlns, framework bindings: htsparse.c:153-187, 2207-2245); a
    # nested string is judged by the attribute holding it (intag_startattr)
    html = ('<div data-page="a.html" title="no.html" class="no.gif" v-bind:src="no2.gif">'
            '<meta property="og:image" content="/b.png"><span data-x="go(\'c.html\')"'
            ' alt="f(\'no3.html\')" data-y="a b.html"><a href="e.html" data-z="f.png">')
    base = "https://h.test/docs/guide/"
    assert urls(html) == [base + "a.html", "https://h.test/b.png", base + "c.html",
                          base + "e.html", base + "f.png"]
    assert urls(html, extended_parsing=False) == [base + "e.html"]
    assert metas(html)[base + "a.html"] == FetchMeta("", "no-cors", False)


def test_no_parse_scripts_also_stops_css_urls():
    # url() and @import are hts_js_scan_link keywords, so -j4 stops them (htsparse.c:584);
    # a quoted one is still a -%P string after "("
    html = "<style>a{b:url(x.png)} c{d:url('y.png')}</style>"
    assert urls(html, parse_scripts=False) == ["https://h.test/docs/guide/y.png"]
    assert urls(html, parse_scripts=False, extended_parsing=False) == []
    assert css_links(b"a{b:url(x.png)}", "https://h.test/s.css", parse_scripts=False) == []


def test_script_file_links_take_the_page_base_but_modules_their_own():
    # htsparse.c:1280-1285 parent_relative, htscore.h:276 relative_to_parent(): a module
    # specifier resolves against the script itself
    body = b'img.src = "i.png"; import a from "./mod.js"; load(import("./dyn.js"))'
    got = script_links(body, "https://h.test/static/js/app.js", "https://h.test/docs/p.html")
    assert [(l.url, l.meta) for l in got] == [
        ("https://h.test/docs/i.png", FetchMeta("", "no-cors", False)),
        ("https://h.test/static/js/mod.js", FetchMeta("", "no-cors", False)),
        ("https://h.test/static/js/dyn.js", FetchMeta("", "no-cors", False))]
    assert script_links(body, "https://h.test/a.js", "https://h.test/",
                        parse_scripts=False, extended_parsing=False) == []


def test_script_links_follow_nofollow_and_base():
    html = ('<base href="https://h.test/b/"><script>x.src="a.gif";</script>'
            '<meta name="robots" content="nofollow"><script>y.src="c.gif";</script>')
    assert urls(html) == ["https://h.test/b/a.gif"]


def test_script_link_needs_an_end_after_its_quote():
    # hts_js_scan_link takes an assignment only before ";", a line end or the end of the
    # page (htsparse.c:712-720): HTTrack misses x.src="a.gif"</script>, and so does this
    assert urls('<script>x.src="a.gif"</script><script>y.src="b.gif"\n</script>',
                extended_parsing=False) == ["https://h.test/docs/guide/b.gif"]


G = "https://h.test/docs/guide/"
SAVED = {G + "a": "/out/h.test/docs/guide/a.html",
         "https://h.test/docs/": "/out/h.test/docs/index.html",
         G + "img/b.png?w=2&v=1": "/out/h.test/docs/guide/img/b1f2e.png"}


def test_script_style_and_dirty_links_are_rewritten_as_httrack_writes_them():
    # HTTrack rewrites every link it records (htsparse.c:3379-3502; history.txt:151): a
    # saved file becomes its relative path with the link's query after it (includequery,
    # 3475-3480), any other relative link the absolute URL (sink_add_absolute_url,
    # 1011-1033); & becomes &amp; in a tag, never in <script>/<style> text (sink_raw_text,
    # 977-988, #1616). An absolute link to no saved file, and every other byte, stay.
    html = ('<script>img.src = "a"; x = "far.html"; y = "/docs/"; '
            'w.open("https://other.test/x.html");</script>'
            '<style>p{background:url(img/b.png?v=1&w=2)}</style>'
            '<p style="background:url(&quot;img/b.png?v=1&amp;w=2&quot;)" '
            'onclick="x.src=\'a#top\'" data-p="far.png?x=1&amp;y=2">'
            '<a href="javascript:location.href=\'/docs/\'">j</a>')
    assert _rewrite(html, SAVED) == (
        '<script>img.src = "a.html"; x = "https://h.test/docs/guide/far.html"; '
        'y = "../index.html"; w.open("https://other.test/x.html");</script>'
        '<style>p{background:url(img/b1f2e.png?v=1&w=2)}</style>'
        '<p style="background:url(&quot;img/b1f2e.png?v=1&amp;w=2&quot;)" '
        'onclick="x.src=\'a.html#top\'" data-p="https://h.test/docs/guide/far.png?x=1&amp;y=2">'
        '<a href="javascript:location.href=\'../index.html\'">j</a>')


def test_rewritten_script_names_are_escaped_as_httrack_escapes_them():
    # escape_uri_utf (htslib.c:4452-4455, 4613-4618, lower-case hex) on the relative path,
    # then "(" and ")" percent-encoded in a CSS url() (escape_url_parens, htsparse.c:851-870,
    # #163); the query only loses " , blanks and controls (escape_check_url, 2688-2702)
    name = "/out/h.test/docs/guide/a b'(1)é&c.png"
    local = {G + "a%20b%27(1)%C3%A9&c.png": name, G + "a%20b%27(1)%C3%A9&c.png?q=a b": name}
    html = ('<style>p{background:url("a%20b%27(1)%C3%A9&c.png?q=a b")}</style>'
            "<script>img.src = 'a%20b%27(1)%C3%A9&c.png';</script>")
    assert _rewrite(html, local) == (
        '<style>p{background:url("a%20b%27%281%29%c3%a9%26c.png?q=a%20b")}</style>'
        "<script>img.src = 'a%20b%27(1)%c3%a9%26c.png';</script>")


def test_scan_links_stay_as_written_with_the_scans_off():
    html = b'<script>x.src="a";</script><div data-p="a.html"></div><a href="a">a</a>'
    keys = {url_key(u): p for u, p in SAVED.items()}
    out = rewrite_links(html, PAGE, "/out/h.test/docs/guide/intro.html", keys,
                        parse_scripts=False, extended_parsing=False)
    assert out == html.replace(b'href="a"', b'href="a.html"')


def test_script_inside_a_rewritten_srcset_is_left_to_the_attribute():
    # the tokenizer reads srcset candidates past a javascript: one; the attribute's rewrite
    # replaces the whole value, so the script link inside it is not written twice
    html = '<img srcset="javascript:x.src=\'a\'; 1x, img/c.png 2x">'
    assert _rewrite(html, SAVED) == ('<img srcset="javascript:x.src=&#x27;a&#x27;; 1x, '
                                     'https://h.test/docs/guide/img/c.png 2x">')


@pytest.mark.parametrize("raw,writer,want", [  # st_sink, htsparse_selftest.c:1309-1328
    ('a&"<\xe9', True, 'a&%22%3c\xe9'), ('a&"<\xe9', False, 'a&amp;%22%3c\xe9')])
def test_absolute_url_writer_matches_httrack_selftest(raw, writer, want):
    from dograpper.lib.httrack.links import _url_text
    assert _url_text(raw, writer) == want


CSS = "https://h.test/docs/css/site.css"


def test_stylesheet_links_are_rewritten_relative_to_the_stylesheet():
    # a stylesheet is parsed as one script (htsparse.c:1264-1287) and written back
    # (3807-3852), its links relative to itself (relativesavename(), htscore.h:282-283);
    # comments are no links
    local = {"https://h.test/docs/css/t.css?page=2": "/out/h.test/docs/css/t1234.css",
             "https://h.test/docs/img/a.png": "/out/h.test/docs/img/a.png",
             "https://h.test/docs/img/a%20(1).png": "/out/h.test/docs/img/a (1).png"}
    body = (b'@import "t.css?page=2" screen;\nh1{background:url(../img/a.png)}\n'
            b'p{background:url("../img/a%20(1).png")} /* url(x.png) */ i{background:url(m.png)}'
            b"\xff")
    out = rewrite_file_links(body, CSS, "/out/h.test/docs/css/site.css",
                             {url_key(u): p for u, p in local.items()}, css=True)
    assert out == (b'@import "t1234.css?page=2" screen;\nh1{background:url(../img/a.png)}\n'
                   b'p{background:url("../img/a%20%281%29.png")} /* url(x.png) */ '
                   b"i{background:url(https://h.test/docs/css/m.png)}\xff")


def test_script_file_links_are_written_relative_to_the_page_that_loaded_it():
    # a script's links take its page's base and its page's save name, a module specifier
    # the script's own (relative_to_parent(), htscore.h:276-283); "./" is dropped
    # (htsparse.c:2718-2725), as lienrelatif writes a path in the same directory
    js = "https://h.test/docs/static/app.js"
    local = {url_key(G + "a"): "/out/h.test/docs/guide/a.html",
             url_key("https://h.test/docs/static/m.js"): "/out/h.test/docs/static/m.js"}
    body = b'img.src = "a"; import "./m.js";'
    out = rewrite_file_links(body, js, "/out/h.test/docs/static/app.js", local, css=False,
                             page=PAGE, page_path="/out/h.test/docs/guide/intro.html")
    assert out == b'img.src = "a.html"; import "m.js";'
    # a page with no saved file: its links are made absolute, a module's stay relative
    out = rewrite_file_links(body, js, "/out/h.test/docs/static/app.js", local, css=False,
                             page=PAGE, page_path=None)
    assert out == b'img.src = "https://h.test/docs/guide/a"; import "m.js";'
    # a script with no page (a start URL) resolves and writes against itself
    out = rewrite_file_links(b'x.src = "../guide/a";', js, "/out/h.test/docs/static/app.js",
                             local, css=False)
    assert out == b'x.src = "../guide/a.html";'
    assert rewrite_file_links(body, js, "/o/app.js", local, css=False, page=PAGE,
                              page_path="/o/p.html", parse_scripts=False,
                              extended_parsing=False) is body


HOSTILE = {  # (head, piece repeated n times, tail, n): each must cost linear CPU time
    "unclosed-string": (b"<script>x.src=\"", b"a", b"", 20000),
    "unclosed-comment": (b"<script>/*", b"x.src='a.gif' ", b"", 20000),
    "unclosed-script": (b"<script>", b'.src="a', b"", 5000),
    "quotes": (b"<script>", b"\"'", b"</script>", 10000),
    "backslashes": (b"<script>\"", b"\\", b"\"</script>", 20000),
    "one-line-calls": (b"<script>", b'f("a.gif",', b"</script>", 1000),
    "keywords": (b"<script>", b".src.location.open(url(import from ", b"</script>", 1000),
    "css-url": (b"<style>", b"url(", b"</style>", 5000),
    "style-attr-urls": (b'<a style="', b"url(a.png) ", b'">', 2000),
    "tag-quotes": (b"<p ", b'="', b">", 5000),
    "tag-nested": (b"<p data-x=\"", b"(',", b"\">", 5000),
    "tag-blanks": (b"<p a=x", b" \"'", b">", 5000),
    "handler": (b"<p onclick=\"", b"x.src='a", b"\">", 5000),
}


@pytest.mark.parametrize("name", list(HOSTILE))
def test_script_scans_are_linear_on_hostile_pages(name):
    # CPU time, not wall time: 4x the input may cost at most ~4x (quadratic would be 16x);
    # n is per shape, so each case stays short while a quadratic scan of it still fails
    head, piece, tail, n = HOSTILE[name]
    def scan(b):
        page_links(b, PAGE)
    assert_linear(lambda k: head + piece * k + tail, scan, n, bound=9, floor=1e-3)


@pytest.mark.parametrize("text,at,in_tag,in_css,escape", [  # htsparse_selftest.c:804-822
    ("url(a.png)", 0, False, True, True), ("url('a (2).png')", 0, False, True, True),
    ('x.src="a (2).png";', 1, False, False, False),
    ("url(&quot;a (2).png&quot;)", 0, True, True, True), ('new URL("a.gif")', 4, False, False, False)])
def test_css_url_links_escape_their_parentheses(text, at, in_tag, in_css, escape):
    got = J._js_link(text, at, J.Ctx(css=in_css, in_tag=in_tag, tag_lastc='"'))
    assert got[5] is escape


HOSTILE_KEYS = {url_key(u): p for u, p in {  # every hostile link is rewritten
    **SAVED, G + "a.png": "/out/h.test/docs/guide/img/a.png"}.items()}
HOSTILE_REWRITES = {  # (head, piece repeated n times, tail, n)
    "script-links": (b"<script>", b'x.src="a";', b"</script>", 3000),
    "style-attr-urls": (b'<p style="', b"url(a) ", b'">', 3000),  # the #127 shape
    "style-attr-unclosed-urls": (b'<p style="', b"url(", b'">', 3000),
    "dirty-tags": (b"", b'<p data-p="a.png">', b"", 2000),
}


@pytest.mark.parametrize("name", list(HOSTILE_REWRITES))
def test_rewrite_of_scanned_links_is_linear_on_hostile_pages(name):
    # n is large enough that a quadratic pass over the edits (one Python step per earlier
    # edit) reaches a ratio near 9-12, while a linear one stays near 4
    head, piece, tail, n = HOSTILE_REWRITES[name]

    def rewrite(b):
        rewrite_links(b, PAGE, "/out/h.test/docs/guide/intro.html", HOSTILE_KEYS)
    assert_linear(lambda k: head + piece * k + tail, rewrite, n)


@pytest.mark.parametrize("piece,css", [
    (b"url(a) ", True), (b"url(", True), (b'x.src = "a";\n', False)],
    ids=["css-urls", "css-unclosed", "js-links"])
def test_rewrite_of_stylesheets_and_scripts_is_linear(piece, css):
    def rewrite(b):
        rewrite_file_links(b, PAGE, "/out/h.test/docs/guide/x", HOSTILE_KEYS, css=css)
    assert_linear(lambda k: piece * k, rewrite, 4000)
