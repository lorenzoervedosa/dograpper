"""mirror_site(): the httrack profile's recursive crawl, against the local `server` fixture."""

import json
import logging
import os
import random
import re
import threading
import time

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
