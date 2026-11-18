"""mirror_site(): the httrack profile's recursive crawl, against the local `server` fixture."""

import json
import logging
import os
import random
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.lib.httrack.fetcher import Fetcher
from dograpper.lib.httrack.mirror import mirror_site
from dograpper.lib.httrack.policy import FetchMeta, build_policy
from dograpper.lib.url_filter import UrlFilters

HTML = {"content-type": "text/html"}


class FakeTime:
    def __init__(self):
        self.now, self.lock = 1000.0, threading.Lock()

    def clock(self):
        return self.now

    def sleep(self, s):
        with self.lock:
            self.now += s


class Spy(Fetcher):
    """Records every GET; `jitter` shuffles completion order with real sleeps."""

    def __init__(self, policy, jitter=False):
        ft = FakeTime()
        super().__init__(policy, clock=ft.clock, sleep=ft.sleep)
        self.calls, self.jitter = [], jitter

    def get(self, url, **kw):
        self.calls.append((url, kw))
        if self.jitter:
            time.sleep(random.random() / 100)
        return super().get(url, **kw)


def crawl(start, out, exts="html", depth=0, filters=None, jitter=False, **kw):
    policy = build_policy(retries=0, **kw)
    spy = Spy(policy, jitter)
    res = mirror_site(start, str(out), policy, exts, depth=depth, fetcher=spy, filters=filters)
    return res, spy


def page(*hrefs, extra=""):
    return (HTML, ("<html><body>" + extra +
                   "".join(f'<a href="{h}">{h}</a>' for h in hrefs) + "</body></html>").encode())


def site(script, pages):
    script["/robots.txt"] = (404, {}, b"")
    for path, (hdrs, body) in pages.items():
        script[path] = (200, hdrs, body)


def rel(res, out):
    return sorted(os.path.relpath(f, out).split(os.sep, 1)[1] for f in res.files_downloaded)


def test_follows_links_in_scope_only(server, tmp_path):
    base, script, seen = server
    site(script, {
        "/docs/": page("a.html", "sub/b", "/other/x", "http://example.invalid/y",
                       "/cdn-cgi/l/email-protection", "i.png", "mailto:m@x"),
        "/docs/a.html": page("/docs/"),
        "/docs/sub/b": page("../a.html#top"),
        "/other/x": page(),
    })
    res, _ = crawl(f"{base}/docs/", tmp_path)
    assert rel(res, tmp_path) == ["docs/a.html", "docs/index.html", "docs/sub/b.html"]
    assert sorted(p for p in seen if p != "/robots.txt") == ["/docs/", "/docs/a.html",
                                                              "/docs/sub/b"]  # parallel: any order
    assert res.report.out_of_scope == sorted([f"{base}/cdn-cgi/l/email-protection",
                                              f"{base}/other/x", "http://example.invalid/y"])
    assert res.report.filtered == [f"{base}/docs/i.png"]  # never requested
    assert res.success and not res.front_failed


def test_start_directory_of_a_file_url_is_its_parent(server, tmp_path):
    base, script, seen = server
    site(script, {"/docs/index.html": page("guide.html", "/blog/"), "/docs/guide.html": page()})
    res, _ = crawl(f"{base}/docs/index.html", tmp_path)
    assert rel(res, tmp_path) == ["docs/guide.html", "docs/index.html"]
    assert "/blog/" not in seen


def test_depth_counts_link_hops_from_the_start(server, tmp_path):
    base, script, seen = server
    site(script, {"/": page("a"), "/a": page("b"), "/b": page("c"), "/c": page()})
    res, _ = crawl(f"{base}/", tmp_path, depth=2)
    assert rel(res, tmp_path) == ["a.html", "b.html", "index.html"]
    assert "/c" not in seen
    res, _ = crawl(f"{base}/", tmp_path / "all", depth=0)
    assert len(res.files_downloaded) == 4


def test_filters_refuse_and_widen_the_scope(server, tmp_path):
    base, script, seen = server
    site(script, {"/docs/": page("private/p", "pub", "/shared/s"), "/docs/pub": page(),
                  "/docs/private/p": page(), "/shared/s": page()})
    filters = UrlFilters(["-*/private/*", "+*/shared/*"])
    res, _ = crawl(f"{base}/docs/", tmp_path, filters=filters)
    assert rel(res, tmp_path) == ["docs/index.html", "docs/pub.html", "shared/s.html"]
    assert "/docs/private/p" not in seen
    assert filters.excluded == {f"{base}/docs/private/p"}


def test_meta_robots_nofollow_and_robots_txt(server, tmp_path):
    base, script, seen = server
    site(script, {"/": page("a", "blocked/x"),
                  "/a": page("b", extra='<meta name="robots" content="nofollow">'),
                  "/b": page(), "/blocked/x": page()})
    script["/robots.txt"] = (200, {"content-type": "text/plain"},
                             b"User-agent: *\nDisallow: /blocked/\n")
    res, _ = crawl(f"{base}/", tmp_path)
    assert rel(res, tmp_path) == ["a.html", "index.html"]
    assert "/b" not in seen and "/blocked/x" not in seen
    assert res.report.robots_blocked == [f"{base}/blocked/x"]
    res, _ = crawl(f"{base}/", tmp_path / "nr", obey_robots=False)
    assert len(res.files_downloaded) == 4  # --no-robots ignores both


def test_redirects_are_scoped_and_rewritten_to_the_target(server, tmp_path):
    base, script, seen = server
    site(script, {"/docs/": page("old", "away", "/docs/new"), "/docs/new": page("/docs/")})
    script["/docs/old"] = (301, {"location": "/docs/new"}, b"")
    script["/docs/away"] = (302, {"location": "/elsewhere/"}, b"")
    res, _ = crawl(f"{base}/docs/", tmp_path)
    assert rel(res, tmp_path) == ["docs/index.html", "docs/new.html"]
    assert "/elsewhere/" not in seen and f"{base}/elsewhere/" in res.report.out_of_scope
    index = open(tmp_path / f"127.0.0.1:{base.rsplit(':', 1)[1]}" / "docs" / "index.html").read()
    assert 'href="new.html">old<' in index and 'href="new.html">/docs/new<' in index
    assert seen.count("/docs/new") == 1


def test_redirect_target_drops_its_fragment_and_must_be_http(server, tmp_path):
    base, script, _ = server
    site(script, {"/": page("a", "b"), "/new": page()})
    script["/a"] = (302, {"location": "/new#part"}, b"")
    script["/b"] = (302, {"location": "ftp://127.0.0.1/x"}, b"")
    res, spy = crawl(f"{base}/", tmp_path)
    assert rel(res, tmp_path) == ["index.html", "new.html"]
    assert f"{base}/new" in [u for u, _ in spy.calls]
    assert res.report.out_of_scope == ["ftp://127.0.0.1/x"]
    assert all("#" not in u for u, _ in spy.calls)


def test_start_redirect_out_of_its_directory_rebases_the_scope(server, tmp_path):
    base, script, _ = server
    site(script, {"/en/latest/": page("guide"), "/en/latest/guide": page()})
    script["/latest/"] = (302, {"location": "/en/latest/"}, b"")
    res, _ = crawl(f"{base}/latest/", tmp_path)
    assert rel(res, tmp_path) == ["en/latest/guide.html", "en/latest/index.html"]
    assert res.urls[res.files_downloaded[1]] == f"{base}/latest/"  # the URL requested


def test_start_redirect_to_another_host_stops_the_run(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/"] = (301, {"location": "http://example.invalid/"}, b"")
    res, _ = crawl(f"{base}/", tmp_path)
    assert res.front_failed and not res.success
    assert res.report.out_of_scope == ["http://example.invalid/"]


def test_challenges_and_errors_are_never_written(server, tmp_path):
    base, script, _ = server
    site(script, {"/": page("cf", "moment", "gone")})
    script["/cf"] = (403, {**HTML, "cf-mitigated": "challenge"}, b"<p>x</p>")
    script["/moment"] = (200, HTML, b"<title>Just a moment...</title>")
    script["/gone"] = (404, HTML, b"<p>gone</p>")
    res, _ = crawl(f"{base}/", tmp_path)
    assert rel(res, tmp_path) == ["index.html"]
    assert res.report.challenged == [f"{base}/cf", f"{base}/moment"]
    assert res.report.errors == [(f"{base}/gone", "HTTP 404", f"{base}/")]  # with referrer
    assert sum(len(f) for _, _, f in os.walk(tmp_path)) == 1


def test_challenged_start_url_is_a_front_failure(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/"] = (403, {**HTML, "cf-mitigated": "challenge"}, b"")
    res, _ = crawl(f"{base}/", tmp_path)
    assert res.front_failed and res.report.challenged == [f"{base}/"]


def test_links_point_at_the_saved_files(server, tmp_path):
    base, script, _ = server
    site(script, {"/": page("guide/", "api/x?b=2&a=1", "notes.txt", "/missing"),
                  "/guide/": page("../", "/api/x?a=1&b=2#m"),
                  "/api/x?b=2&a=1": page(),  # requested as first linked
                  "/notes.txt": ({"content-type": "text/plain"}, b"<a href=x>not html</a>")})
    res, _ = crawl(f"{base}/", tmp_path, exts="html,txt")
    host = tmp_path / f"127.0.0.1:{base.rsplit(':', 1)[1]}"
    names = sorted(os.listdir(host / "api"))
    assert len(names) == 1 and names[0].startswith("x") and names[0].endswith(".html")
    index = (host / "index.html").read_text()
    assert 'href="guide/index.html"' in index and f'href="api/{names[0]}"' in index
    assert 'href="notes.txt"' in index and f'href="{base}/missing"' in index
    guide = (host / "guide" / "index.html").read_text()
    assert 'href="../index.html"' in guide and f'href="../api/{names[0]}#m"' in guide
    assert (host / "notes.txt").read_bytes() == b"<a href=x>not html</a>"  # only HTML is rewritten


def test_manifest_urls_are_the_urls_requested(server, tmp_path):
    base, script, _ = server
    site(script, {"/": page("a", "b"), "/a": page(), "/t": page()})
    script["/b"] = (301, {"location": "/t"}, b"")
    res, _ = crawl(f"{base}/", tmp_path)
    by_name = {os.path.basename(f): u for f, u in res.urls.items()}
    assert by_name == {"index.html": f"{base}/", "a.html": f"{base}/a", "t.html": f"{base}/b"}
    assert sorted(res.urls) == res.files_downloaded


def test_referer_and_fetch_metadata_per_link(server, tmp_path):
    base, script, _ = server
    site(script, {"/": page("a", extra='<iframe src="f"></iframe>'), "/a": page(),
                  "/f": page()})
    res, spy = crawl(f"{base}/", tmp_path)
    calls = {u: kw for u, kw in spy.calls if not u.endswith("/robots.txt")}
    assert calls[f"{base}/"] == {"kind": "navigate", "referer": None,
                                 "meta": FetchMeta()}
    assert calls[f"{base}/a"] == {"kind": "linked", "referer": f"{base}/",
                                  "meta": FetchMeta("document", "navigate", True)}
    assert calls[f"{base}/f"]["meta"] == FetchMeta("iframe", "navigate", False)


def test_redirect_target_is_requested_as_htsmirror_c_requests_it(server, tmp_path):
    # htsmirror.c:190-261 (a known non-page target: a fresh link with the moved link's
    # parent) and 279-324 (any other: a stub page whose link it becomes); both copy the
    # moved link's fetch metadata through hts_fetch_through (htsfetch.c:452-465)
    base, script, _ = server
    site(script, {"/": page("old", "doc"), "/new": page(),
                  "/f.txt": ({"content-type": "text/plain"}, b"t")})
    script["/old"] = (301, {"location": "/new"}, b"")
    script["/doc"] = (301, {"location": "/f.txt"}, b"")
    res, spy = crawl(f"{base}/", tmp_path, exts="html,txt")
    calls = {u: kw for u, kw in spy.calls if not u.endswith("/robots.txt")}
    linked = FetchMeta("document", "navigate", True, "same-origin")
    assert calls[f"{base}/new"] == {"kind": "linked", "referer": f"{base}/old", "meta": linked}
    assert calls[f"{base}/f.txt"] == {"kind": "linked", "referer": f"{base}/", "meta": linked}


def test_start_url_redirect_target_keeps_sec_fetch_site_none(server, tmp_path):
    base, script, _ = server
    site(script, {"/en/": page()})
    script["/latest/"] = (302, {"location": "/en/"}, b"")
    _, spy = crawl(f"{base}/latest/", tmp_path)
    calls = {u: kw for u, kw in spy.calls if not u.endswith("/robots.txt")}
    assert calls[f"{base}/en/"] == {"kind": "linked", "referer": f"{base}/latest/",
                                    "meta": FetchMeta("document", "navigate", True, "none")}


class _Silent(BaseHTTPRequestHandler):  # answers 501 to everything
    def log_message(self, *a):
        pass


def test_redirect_chain_sends_its_worst_sec_fetch_site(server, tmp_path):
    base, script, _ = server
    other = ThreadingHTTPServer(("127.0.0.1", 0), _Silent)
    threading.Thread(target=other.serve_forever, kwargs={"poll_interval": 0.01},
                     daemon=True).start()
    try:
        target = f"http://127.0.0.1:{other.server_address[1]}/x"  # same host, other port
        site(script, {"/": page("old")})
        script["/old"] = (301, {"location": target}, b"")
        _, spy = crawl(f"{base}/", tmp_path,
                       filters=UrlFilters([f"+127.0.0.1:{other.server_address[1]}/*"]))
    finally:
        other.shutdown()
        other.server_close()
    assert dict(spy.calls)[target]["meta"] == FetchMeta("document", "navigate", True,
                                                        "same-site")


def test_max_links_ends_the_crawl_partial(server, tmp_path):
    base, script, seen = server
    site(script, {"/": page("a", "b", "c"), "/a": page(), "/b": page(), "/c": page()})
    res, _ = crawl(f"{base}/", tmp_path, max_links=3)
    assert res.report.partial and len(res.files_downloaded) == 3
    assert "/c" not in seen


def test_progress_lines_have_the_growing_shape(server, tmp_path, caplog):
    base, script, _ = server
    site(script, {"/": page("a"), "/a": page()})
    with caplog.at_level(logging.INFO):
        crawl(f"{base}/", tmp_path)
    lines = [r.getMessage() for r in caplog.records if r.getMessage().startswith("[progress]")]
    assert re.fullmatch(rf"\[progress\] httrack crawl: 2 files · 0\.0 MB · \d+s · queued 0 · "
                        rf"last: {re.escape(base)}/a", lines[-1]), lines


def _tree(root):
    out = {}
    for d, _, files in os.walk(root):
        for f in files:
            p = os.path.join(d, f)
            out[os.path.relpath(p, root)] = open(p, "rb").read()
    return out


def test_output_does_not_depend_on_thread_completion_order(server, tmp_path):
    base, script, _ = server
    hrefs = [h for i in range(12) for h in (f"p{i}", f"p{i}.html")]  # colliding pairs in flight
    site(script, {"/": page(*hrefs),
                  **{f"/p{i}": page("/", f"p{i}.html") for i in range(12)},
                  **{f"/p{i}.html": page("/") for i in range(12)}})
    trees = []
    for run in ("one", "two"):
        res, _ = crawl(f"{base}/", tmp_path / run, connections=4, jitter=True)
        trees.append((_tree(tmp_path / run), [os.path.relpath(f, tmp_path / run)
                                              for f in res.files_downloaded],
                      sorted((os.path.relpath(f, tmp_path / run), u)
                             for f, u in res.urls.items())))
    assert trees[0] == trees[1]
    assert len(trees[0][0]) == 25  # /p0 and /p0.html both want p0.html: one gets p0-2.html


def test_pack_cross_refs_resolve_links_of_a_crawled_tree(server, tmp_path):
    base, script, _ = server
    words = " ".join(["documentation"] * 40)
    site(script, {"/docs/": page("install.html", extra=f"<h1>Home</h1><p>{words}</p>"),
                  "/docs/install.html": page("/docs/", extra=f"<h1>Install</h1><p>{words}</p>")})
    out = tmp_path / "mirror"
    res, _ = crawl(f"{base}/docs/", out)
    assert len(res.files_downloaded) == 2
    chunks = tmp_path / "chunks"
    r = CliRunner().invoke(cli, ["pack", str(out), "-o", str(chunks), "--cross-refs",
                                 "--max-words-per-chunk", "60"])
    assert r.exit_code == 0, r.output
    refs = json.loads((chunks / "cross_refs.json").read_text())
    resolved = [link for key, entry in refs.items() if key != "unresolved"
                for link in entry["links"]]
    assert {(os.path.basename(l["source_file"]), l["target_file"].rsplit("/", 1)[-1])
            for l in resolved} >= {("index.html", "install.html")}
    assert refs["unresolved"] == []


CSS, JS = {"content-type": "text/css"}, {"content-type": "text/javascript"}
SCANNED = {  # links only the script scans find, to files whose names are not their URLs
    "/": page(extra='<link rel="stylesheet" href="css/site.css"><script src="js/app.js">'
                    '</script><script>img.src = "next";</script>'),
    "/css/site.css": (CSS, b'@import "t.css?page=2";\np{background:url(../next)}'),
    "/css/t.css?page=2": (CSS, b"p{}"),
    "/js/app.js": (JS, b'x.src = "next"; import "./m.js";'),
    "/js/m.js": (JS, b"export {};"), "/next": page()}


def test_links_found_by_the_scans_point_at_the_saved_files(server, tmp_path):
    """HTTrack rewrites every link it records, in a page's scripts and in the stylesheets
    and scripts it saves (htsparse.c:3379-3502, 3807-3852; history.txt:151); a script's
    link is written from the page that loaded it, a module's from the script
    (htscore.h:276-283)."""
    base, script, _ = server
    site(script, SCANNED)
    res, _ = crawl(f"{base}/", tmp_path, exts="html,css,js")
    host = tmp_path / f"127.0.0.1:{base.rsplit(':', 1)[1]}"
    [t] = [n for n in os.listdir(host / "css") if n.startswith("t")]
    assert re.fullmatch(r"t[0-9a-f]{4}\.css", t) and res.report.errors == []
    assert '<script>img.src = "next.html";</script>' in (host / "index.html").read_text()
    assert (host / "css" / "site.css").read_bytes() == (
        f'@import "{t}?page=2";\np{{background:url(../next.html)}}'.encode())
    assert (host / "js" / "app.js").read_bytes() == b'x.src = "next.html"; import "m.js";'
    res, _ = crawl(f"{base}/", tmp_path / "off", exts="html,css,js", parse_scripts=False)
    assert (tmp_path / "off" / host.name / "index.html").read_bytes() == SCANNED["/"][1]


# -- update mode: a crawl over the previous run's manifest --

from dograpper.lib.manifest import build_manifest  # noqa: E402

LM = "Mon, 01 Jan 2024 00:00:00 GMT"


def validated(etag, hdrs, body, log, path, then=None):
    """`body` with `etag`; 304 (or `then`) when the request names that ETag."""
    def reply(h):
        log.append((path, h.get("If-None-Match")))
        if h.get("If-None-Match") == etag:
            return then or (304, {"etag": etag}, b"")
        return (200, {**hdrs, "etag": etag, "last-modified": LM}, body)
    return reply


def vsite(script, pages, log):
    script["/robots.txt"] = (404, {}, b"")
    for path, (hdrs, body) in pages.items():
        script[path] = validated(f'"{path}"', hdrs, body, log, path)


def update(start, out, first, **kw):
    previous = build_manifest(start, str(out), first.urls, records=first.records)
    policy = build_policy(**{"retries": 0, **kw})
    spy = Spy(policy)
    return mirror_site(start, str(out), policy, "html", fetcher=spy, previous=previous), spy


def test_unchanged_page_is_kept_and_its_links_followed_from_the_saved_copy(server, tmp_path):
    """HTTrack re-parses a 304 page from its cache (htsback.c:4437-4494); dograpper reads
    the kept copy, whose links relink() made local, back through the manifest."""
    base, script, _ = server
    log = []
    vsite(script, {"/": page("guide/", "api?page=2", "/far", "t?token=s"),
                   "/guide/": page("../"), "/api?page=2": page(), "/far": page(),
                   "/t?token=s": page()}, log)
    first, _ = crawl(f"{base}/", tmp_path)
    host = tmp_path / f"127.0.0.1:{base.rsplit(':', 1)[1]}"
    index = (host / "index.html").read_bytes()
    assert b'href="guide/index.html"' in index
    log.clear()
    script["/far"] = validated('"far2"', HTML, b"<p>new</p>", log, "/far")
    res, _ = update(f"{base}/", tmp_path, first)
    # a file the manifest records no URL for (a query off the allowlist) is not followed
    assert sorted(log) == [("/", '"/"'), ("/api?page=2", '"/api?page=2"'), ("/far", '"/far"'),
                           ("/guide/", '"/guide/"')]
    assert (host / "index.html").read_bytes() == index
    assert rel(res, tmp_path) == ["far.html"] and len(res.kept) == 3
    assert res.report.not_modified == 3 and res.report.errors == []
    assert res.success and not res.front_failed
    assert {f: u for f, u in res.urls.items() if "?token" not in u} == {
        f: u for f, u in first.urls.items() if "?token" not in u}


def test_start_url_error_on_update_keeps_the_mirror_and_goes_on(server, tmp_path):
    base, script, _ = server
    log = []
    vsite(script, {"/": page("a"), "/a": page()}, log)
    first, _ = crawl(f"{base}/", tmp_path)
    script["/"] = validated('"/"', HTML, b"", log, "/", then=(503, HTML, b"<p>down</p>"))
    log.clear()
    res, _ = update(f"{base}/", tmp_path, first, retries=2)
    assert log == [("/", '"/"'), ("/a", '"/a"')]
    assert res.report.kept == [(f"{base}/", "HTTP 503")] and not res.front_failed


def test_challenged_start_url_on_update_fails_the_front_and_keeps_the_copy(server, tmp_path):
    base, script, _ = server
    log = []
    vsite(script, {"/": page("a"), "/a": page()}, log)
    first, _ = crawl(f"{base}/", tmp_path)
    before = open(first.files_downloaded[0], "rb").read()
    script["/"] = validated('"/"', HTML, b"", log, "/",
                            then=(403, {**HTML, "cf-mitigated": "challenge"}, b""))
    script["/a"] = validated('"a2"', HTML, b"<p>a v2</p>", log, "/a")
    res, _ = update(f"{base}/", tmp_path, first)
    assert res.front_failed and res.report.challenged == [f"{base}/"]
    assert open(first.files_downloaded[0], "rb").read() == before
    assert res.files_downloaded == []  # the run fails before the manifest is saved: no write


def test_redirected_start_url_revalidates_its_target(server, tmp_path):
    base, script, _ = server
    log = []
    vsite(script, {"/new": page()}, log)
    script["/old"] = (301, {"location": "/new"}, b"")
    first, _ = crawl(f"{base}/old", tmp_path)
    assert list(first.records.values())[0]["redirected"] is True
    log.clear()
    res, spy = update(f"{base}/old", tmp_path, first)
    sent = {u.rsplit("/", 1)[1]: dict(kw.get("validators", ())) for u, kw in spy.calls
            if not u.endswith("robots.txt")}
    assert sent["old"] == {} and sent["new"]["If-None-Match"] == '"/new"'
    assert [os.path.basename(f) for f in res.kept] == ["new.html"] and not res.front_failed


def test_new_url_never_takes_the_name_of_a_kept_file(server, tmp_path):
    """Names come in queue order; a page added to a changed site must not overwrite a kept
    file whose URL now comes later (NameRegistry.reserve)."""
    base, script, _ = server
    log = []
    vsite(script, {"/": page("b/x", "a/x"), "/a/x": page(), "/b/x": page()}, log)
    script["/a/X"] = (200, HTML, b"<p>new page</p>")
    first, _ = crawl(f"{base}/", tmp_path)
    vsite(script, {"/": page("a/X", "b/x", "a/x"), "/a/x": page(), "/b/x": page()}, log)
    script["/"] = (200, HTML, page("a/X", "b/x", "a/x")[1])  # the index changed
    res, _ = update(f"{base}/", tmp_path, first)
    host = tmp_path / f"127.0.0.1:{base.rsplit(':', 1)[1]}"
    assert (host / "a" / "x.html").read_bytes() == page()[1]
    assert sorted(os.listdir(host / "a")) == sorted(["x.html", "X-2.html"])


def test_new_page_never_takes_the_name_of_a_redirected_file(server, tmp_path):
    """/old -> /new was saved as new.html; a page /new.html linked first must not take it."""
    base, script, _ = server
    log = []
    vsite(script, {"/": page("old"), "/new": page(extra="<p>new</p>")}, log)
    script["/old"] = (301, {"location": "/new"}, b"")
    first, _ = crawl(f"{base}/", tmp_path)
    script["/"] = (200, HTML, page("new.html", "old")[1])
    script["/new.html"] = (200, HTML, b"<p>another page</p>")
    res, _ = update(f"{base}/", tmp_path, first)
    host = tmp_path / f"127.0.0.1:{base.rsplit(':', 1)[1]}"
    assert (host / "new.html").read_bytes() == page(extra="<p>new</p>")[1]
    assert (host / "new-2.html").read_bytes() == b"<p>another page</p>"
    kept = str((host / "new.html").resolve())
    assert res.kept == [kept] and res.urls[kept] == f"{base}/old"
    assert res.records[kept]["etag"] == '"/new"'


def test_kept_page_follows_its_rewritten_style_links(server, tmp_path):
    base, script, seen = server
    log = []
    vsite(script, {"/docs/": page("p", extra='<style>@import "/docs/s.css";</style>'),
                   "/docs/p": page()}, log)
    script["/docs/s.css"] = (200, {"content-type": "text/css"}, b"body{}")
    first = mirror_site(f"{base}/docs/", str(tmp_path), build_policy(retries=0), "html,css",
                        fetcher=Spy(build_policy(retries=0)))
    previous = build_manifest(f"{base}/docs/", str(tmp_path), first.urls, records=first.records)
    seen.clear()
    mirror_site(f"{base}/docs/", str(tmp_path), build_policy(retries=0), "html,css",
                fetcher=Spy(build_policy(retries=0)), previous=previous)
    assert "/docs/s.css" in seen and "/docs/p" in seen


def test_kept_stylesheets_and_scripts_follow_their_rewritten_links(server, tmp_path):
    """A kept stylesheet or script is re-parsed (htsback.c:4437-4494) from the saved copy,
    whose links relink() wrote as saved names: each maps back through the manifest, as a
    kept page's does, so no rewritten name is requested as a URL."""
    base, script, _ = server
    log = []
    vsite(script, SCANNED, log)
    policy = build_policy(retries=0)
    first = mirror_site(f"{base}/", str(tmp_path), policy, "html,css,js", fetcher=Spy(policy))
    previous = build_manifest(f"{base}/", str(tmp_path), first.urls, records=first.records)
    log.clear()
    res = mirror_site(f"{base}/", str(tmp_path), policy, "html,css,js", fetcher=Spy(policy),
                      previous=previous)
    assert sorted(path for path, _ in log) == sorted(SCANNED)
    assert res.report.not_modified == len(SCANNED) and res.report.errors == []


def test_kept_pages_and_scripts_are_scanned_under_the_same_flags(server, tmp_path):
    """A 304 page or script is re-parsed as a fetched one is (htsback.c:4437-4494), so -j
    and -%P apply to kept copies too, and turning them off stops those links."""
    base, script, seen = server
    log = []
    vsite(script, {"/": page(extra='<script src="app.js"></script>'
                                   '<script>img.src = "a.html";</script>'),
                   "/app.js": ({"content-type": "text/javascript"}, b'x.src = "c.html";'),
                   "/a.html": page(), "/c.html": page()}, log)

    def run(out, previous=None, **kw):
        policy = build_policy(retries=0, **kw)
        return mirror_site(f"{base}/", str(out), policy, "html,js", fetcher=Spy(policy),
                           previous=previous)

    first = run(tmp_path)
    assert rel(first, tmp_path) == ["a.html", "app.js", "c.html", "index.html"]
    previous = build_manifest(f"{base}/", str(tmp_path), first.urls, records=first.records)
    seen.clear()
    res = run(tmp_path, previous)
    assert {"/a.html", "/c.html"} <= set(seen) and res.report.not_modified == 4
    seen.clear()
    run(tmp_path, previous, parse_scripts=False, extended_parsing=False)
    assert "/a.html" not in seen and "/c.html" not in seen


def test_second_download_revalidates_and_leaves_the_mirror_as_it_was(server, tmp_path):
    base, script, _ = server
    log = []
    words = " ".join(["documentation"] * 40)
    vsite(script, {"/docs/": page("a.html", extra=f"<h1>Home</h1><p>{words}</p>"),
                   "/docs/a.html": page("./", extra=f"<h1>A</h1><p>{words}</p>")}, log)
    out = tmp_path / "mirror"
    args = ["download", f"{base}/docs/", "-o", str(out), "--downloader", "httrack"]
    first = CliRunner().invoke(cli, args)
    assert first.exit_code == 0, first.output
    manifest = out / ".dograpper-manifest.json"
    before = json.loads(manifest.read_text())["files"]
    assert {e["status"] for e in before.values()} == {200}
    files = {p: open(p, "rb").read() for p in (str(out / e["local_path"]) for e in before.values())}
    log.clear()
    second = CliRunner().invoke(cli, args)
    assert second.exit_code == 0, second.output
    assert sorted(log) == [("/docs/", '"/docs/"'), ("/docs/a.html", '"/docs/a.html"')]
    assert "Files downloaded: 0" in second.output and "Files skipped:    2 (cached)" in second.output
    assert "Not modified (304): 2" in second.output
    assert {p: open(p, "rb").read() for p in files} == files
    after = json.loads(manifest.read_text())["files"]
    fields = ("url", "status", "content_type", "etag", "last_modified", "redirected", "content_hash")
    assert {k: [e[f] for f in fields] for k, e in after.items()} == {
        k: [e[f] for f in fields] for k, e in before.items()}


def test_scripts_are_scanned_for_links_as_httrack_does(server, tmp_path):
    # -j: inline scripts and a fetched script (a JavaScript type, htslib.h:893-897) are
    # scanned; a script's links take the base of the page that loaded it
    # (htsparse.c:1280-1285) and carry no fetch metadata (htsparse.c:819-820); -%P adds the
    # strings of other attributes (htsparse.c:2160-2276)
    base, script, _ = server
    site(script, {"/": page(extra='<script src="static/app.js"></script>'
                                  '<script>img.src = "a.html";</script><div data-p="b.html">'),
                  "/static/app.js": ({"content-type": "text/javascript"}, b'x.src = "c.html";'),
                  "/a.html": page(), "/b.html": page(), "/c.html": page()})
    res, spy = crawl(f"{base}/", tmp_path, exts="html,js")
    assert rel(res, tmp_path) == ["a.html", "b.html", "c.html", "index.html", "static/app.js"]
    calls = {u: kw for u, kw in spy.calls if not u.endswith("/robots.txt")}
    assert calls[f"{base}/c.html"]["referer"] == f"{base}/static/app.js"
    assert calls[f"{base}/c.html"]["meta"] == FetchMeta("", "no-cors", False)
    res, _ = crawl(f"{base}/", tmp_path / "off", exts="html,js", parse_scripts=False,
                   extended_parsing=False)
    assert rel(res, tmp_path / "off") == ["index.html", "static/app.js"]
