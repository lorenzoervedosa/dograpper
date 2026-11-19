"""Navigator: the httrack profile's side of the Playwright crawl (spec 7, PR 4).

The real Fetcher talks to the local `server`; only Playwright's Route/Request are doubles
(CI downloads no browser).
"""

import calendar
import os
import sys
import threading
from unittest.mock import MagicMock, patch

import pytest

from dograpper.lib.httrack.browser import Navigator
from dograpper.lib.httrack.fetcher import Fetcher
from dograpper.lib.httrack.policy import build_policy
from dograpper.lib.playwright_crawl import run_playwright_crawl
from dograpper.lib.url_filter import UrlFilters

HTML = {"content-type": "text/html"}
LM = "Wed, 18 Nov 2026 10:00:00 GMT"


class FakeTime:
    def __init__(self):
        self.now = 1000.0
        self.lock = threading.Lock()

    def clock(self):
        return self.now

    def sleep(self, s):
        with self.lock:
            self.now += s


class Frame:
    pass


class Request:
    def __init__(self, url, frame, nav=True):
        self.url, self.frame, self._nav = url, frame, nav

    def is_navigation_request(self):
        return self._nav


class Route:
    def __init__(self, request):
        self.request, self.calls = request, []

    def fulfill(self, **kw):
        self.calls.append(("fulfill", kw))

    def abort(self, error_code=None):
        self.calls.append(("abort", error_code))

    def continue_(self):
        self.calls.append(("continue",))


class Context:
    def route(self, pattern, handler):
        self.pattern, self.handler = pattern, handler


class Page:
    def __init__(self):
        self.main_frame = Frame()


def navigator(base, out, exts="html", filters=None, seeded=False, **kw):
    policy = build_policy(retries=0, **kw)
    ft = FakeTime()
    nav = Navigator(Fetcher(policy, clock=ft.clock, sleep=ft.sleep), str(out), base + "/docs/",
                    exts, filters=filters, seeded=seeded)
    ctx, page = Context(), Page()
    nav.attach(ctx, page)
    return nav, ctx, page


def navigate(ctx, page, url, frame=None, nav=True):
    """What the browser does for one request: hand it to the route the navigator set."""
    route = Route(Request(url, frame or page.main_frame, nav))
    ctx.handler(route)
    return route.calls


def test_navigation_is_fetched_by_the_profile_and_fulfilled(server, tmp_path):
    base, script, seen = server
    script["/robots.txt"] = (404, {}, b"")
    script["/docs/"] = (200, {**HTML, "x-y": "1"}, b"<p>shell</p>")
    nav, ctx, page = navigator(base, tmp_path)
    assert ctx.pattern == "**/*"
    assert nav.prepare(base + "/docs/") == base + "/docs/"
    (call,) = navigate(ctx, page, base + "/docs/")
    assert call[0] == "fulfill"
    assert call[1]["status"] == 200 and call[1]["body"] == b"<p>shell</p>"
    assert call[1]["headers"]["x-y"] == "1"
    assert seen == ["/robots.txt", "/docs/"]  # one GET, by the profile's Fetcher


def test_challenge_is_aborted_before_it_renders(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/docs/"] = (403, {**HTML, "cf-mitigated": "challenge"},
                        b"<script>solve()</script>")
    nav, ctx, page = navigator(base, tmp_path)
    assert nav.prepare(base + "/docs/") is None
    assert nav.report.challenged == [base + "/docs/"]
    # had the browser asked anyway, nothing would reach it
    assert navigate(ctx, page, base + "/docs/") == [("abort", "blockedbyclient")]


def test_redirect_is_resolved_by_the_policy_before_the_browser_opens_it(server, tmp_path):
    """Chromium follows a fulfilled 3xx without routing the next hop, so the chain is
    fetched here and the browser opens where it ends."""
    base, script, seen = server
    script["/robots.txt"] = (200, {}, b"User-agent: *\nDisallow: /docs/private/\n")
    script["/docs/a"] = (301, {"location": "/docs/b"}, b"")
    script["/docs/b"] = (200, HTML, b"<p>b</p>")
    script["/docs/c"] = (302, {"location": "/docs/private/x"}, b"")
    script["/docs/d"] = (302, {"location": "http://other.invalid/x"}, b"")
    nav, ctx, page = navigator(base, tmp_path)
    assert nav.prepare(base + "/docs/a") == base + "/docs/b"
    assert navigate(ctx, page, base + "/docs/b")[0][1]["body"] == b"<p>b</p>"
    assert nav.prepare(base + "/docs/c") is None  # robots.txt checked on the hop
    assert nav.report.robots_blocked == [base + "/docs/private/x"]
    assert nav.prepare(base + "/docs/d") is None  # never leaves the host
    assert nav.report.out_of_scope == ["http://other.invalid/x"]
    assert seen == ["/robots.txt", "/docs/a", "/docs/b", "/docs/c", "/docs/d"]


def test_start_redirect_out_of_the_directory_rebases_the_scope(server, tmp_path):
    """As mirror_site (spec 5.5 deviation): the crawl follows the start URL's move."""
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/docs/"] = (301, {"location": "/v2/docs/"}, b"")
    script["/v2/docs/"] = (200, HTML, b"<p>v2</p>")
    nav, _, _ = navigator(base, tmp_path)
    page = base + "/v2/docs/"
    assert not nav.follows(base + "/v2/docs/guide", page)
    assert nav.prepare(base + "/docs/") == base + "/v2/docs/"
    assert nav.follows(base + "/v2/docs/guide", page)
    assert not nav.follows(base + "/docs/guide", page)


def test_route_scope_of_requests_that_are_no_crawl_navigation(server, tmp_path):
    base, script, seen = server
    script["/robots.txt"] = (404, {}, b"")
    script["/docs/"] = (200, HTML, b"<p>page</p>")
    nav, ctx, page = navigator(base, tmp_path)
    assert nav.prepare(base + "/docs/") == base + "/docs/"
    # a script or stylesheet: the browser fetches it itself (spec 7 routes navigations)
    assert navigate(ctx, page, base + "/app.js", nav=False) == [("continue",)]
    # /cdn-cgi/ is never requested (spec 5.4), not even by a script of the page
    assert navigate(ctx, page, base + "/cdn-cgi/challenge-platform/h/b/orchestrate/jsd/v1",
                    nav=False) == [("abort", "blockedbyclient")]
    # an iframe or a popup: page.content() never holds it, so it is never fetched
    assert navigate(ctx, page, base + "/docs/frame", frame=Frame()) == [
        ("abort", "blockedbyclient")]
    # the crawled page still gets its armed answer
    assert navigate(ctx, page, base + "/docs/")[0][0] == "fulfill"
    # and a navigation the page starts itself (meta refresh, script) is not followed
    assert navigate(ctx, page, base + "/docs/next") == [("abort", "blockedbyclient")]
    assert seen == ["/robots.txt", "/docs/"]


def test_rendered_pages_are_named_recorded_and_relinked_like_the_engine(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/docs/"] = (200, {**HTML, "etag": '"e1"', "last-modified": LM}, b"<div id=app></div>")
    script["/docs/guide?v=2"] = (200, HTML, b"<div id=app></div>")
    script["/docs/old"] = (301, {"location": "/docs/new"}, b"")
    script["/docs/new"] = (200, HTML, b"<div id=app></div>")
    script["/docs/old2"] = (301, {"location": "/docs/new"}, b"")
    script["/docs/notes.txt"] = (200, {"content-type": "text/plain"}, b"raw notes")
    nav, ctx, page = navigator(base, tmp_path, exts="html,txt")
    host = base.split("//")[1]

    def render(url, html):
        final = nav.prepare(url)
        navigate(ctx, page, final)
        return nav.save(url, html)

    index = render(base + "/docs/", f'<a href="{base}/docs/guide?v=2">g</a>')
    guide = render(base + "/docs/guide?v=2", f'<a href="{base}/docs/">i</a> '
                                             f'<a href="{base}/elsewhere">e</a> '
                                             f'<a href="{base}/docs/old2">o</a>')
    new = render(base + "/docs/old", "<p>moved</p>")
    # another redirect to a saved page: the crawl does not open it again, its links lead there
    assert nav.prepare(base + "/docs/old2") == base + "/docs/new"
    notes = render(base + "/docs/notes.txt", "<pre>raw notes</pre>")
    nav.finish()
    # the engine's names: <host>/<path>, index.html, 4 hex of the query's MD5, final URL
    assert index == str(tmp_path / host / "docs" / "index.html")
    assert os.path.basename(guide) == "guide5e1f.html"
    assert new == str(tmp_path / host / "docs" / "new.html")
    # what the browser rendered, links rewritten as -K0 does (saved: relative; else absolute)
    assert open(index).read() == '<a href="guide5e1f.html">g</a>'
    assert open(guide).read() == (f'<a href="index.html">i</a> <a href="{base}/elsewhere">e</a> '
                                  '<a href="new.html">o</a>')
    assert open(notes, "rb").read() == b"raw notes"  # no page: saved as it came
    assert nav.records[index] == {"status": 200, "content_type": "text/html", "etag": '"e1"',
                                  "last_modified": LM, "redirected": False,
                                  "payload_md5": "46033274d150beac5e7a3d0c22111507"}
    assert nav.records[new]["redirected"] is True
    # its time is the response's Last-Modified (spec 5.6), set after the relink
    assert os.path.getmtime(index) == calendar.timegm((2026, 11, 18, 10, 0, 0))


def test_browser_context_carries_the_profile_identity(server, tmp_path):
    base, _, _ = server
    nav, _, _ = navigator(base, tmp_path, user_agent="Probe/1.0")
    # a service worker would answer navigations past the route
    assert nav.context_options() == {"user_agent": "Probe/1.0", "service_workers": "block"}


def test_max_links_ends_the_browser_crawl_as_partial(server, tmp_path):
    base, script, seen = server
    script["/robots.txt"] = (404, {}, b"")
    script["/docs/a"] = (200, HTML, b"a")
    nav, _, _ = navigator(base, tmp_path, max_links=1)
    assert nav.prepare(base + "/docs/a") == base + "/docs/a"
    assert nav.prepare(base + "/docs/b") is None and nav.report.partial
    assert seen == ["/robots.txt", "/docs/a"]


def test_browser_failure_is_an_error_of_the_report(server, tmp_path):
    base, _, _ = server
    nav, _, _ = navigator(base, tmp_path)
    nav.error("http://u:p@example.com/x", Exception("Timeout 10000ms exceeded.\n=== logs ==="))
    assert nav.report.errors == [("http://example.com/x", "browser: Timeout 10000ms exceeded.",
                                  None)]


@pytest.fixture
def browser():
    """A mocked Playwright (CI downloads no browser): the crawl's page, context and browser."""
    sync_api = MagicMock()
    pw = sync_api.sync_playwright.return_value.__enter__.return_value
    b = pw.chromium.launch.return_value
    ctx = b.new_context.return_value
    page = ctx.new_page.return_value
    page.content.return_value = "<p>rendered</p>"
    page.evaluate.return_value = []
    with patch.dict(sys.modules, {"playwright": MagicMock(), "playwright.sync_api": sync_api}):
        yield b, ctx, page


def crawl_with(base, out, filters=None, exts="html", **kw):
    policy = build_policy(retries=0, user_agent="Probe/1.0")
    ft = FakeTime()
    nav = Navigator(Fetcher(policy, clock=ft.clock, sleep=ft.sleep), str(out), base + "/docs/",
                    exts, filters=filters, seeded="seed_urls" in kw)
    return nav, run_playwright_crawl(base + "/docs/", str(out), navigator=nav,
                                     filters=filters, **kw)


def test_crawl_opens_only_what_the_policy_let_through(server, tmp_path, browser):
    base, script, seen = server
    b, ctx, page = browser
    script["/robots.txt"] = (404, {}, b"")
    script["/docs/old"] = (301, {"location": "/docs/new"}, b"")
    script["/docs/new"] = (200, HTML, b"shell")
    script["/docs/cf"] = (403, {**HTML, "cf-mitigated": "challenge"}, b"<script>x</script>")
    script["/docs/again"] = (302, {"location": "/docs/new"}, b"")
    script["/docs/n.txt"] = (200, {"content-type": "text/plain"}, b"raw notes")
    seeds = [base + u for u in ("/docs/old", "/docs/cf", "/docs/again", "/docs/n.txt")]
    nav, res = crawl_with(base, tmp_path, exts="html,txt", seed_urls=seeds)
    b.new_context.assert_called_once_with(user_agent="Probe/1.0", service_workers="block")
    assert ctx.route.call_args.args[0] == "**/*"
    # each page from a blank one (the last page starts no navigation meanwhile), opened
    # where the policy's redirect chain ended; never opened: the challenge, a page already
    # opened that a redirect leads back to, and an answer that is no HTML page
    assert [c.args[0] for c in page.goto.call_args_list] == [
        "about:blank", base + "/docs/new", "about:blank", "about:blank", "about:blank"]
    assert nav.report.challenged == [base + "/docs/cf"]
    host = tmp_path / base.split("//")[1] / "docs"
    assert res.files_downloaded == [str(host / "new.html"), str(host / "n.txt")]
    assert res.urls == {str(host / "new.html"): base + "/docs/old",  # the URLs requested
                        str(host / "n.txt"): base + "/docs/n.txt"}
    assert open(host / "new.html").read() == "<p>rendered</p>"
    assert open(host / "n.txt", "rb").read() == b"raw notes"
    # a seeded run is its seeds alone, as the profile's seeded fetch: no start URL
    assert seen == ["/robots.txt", "/docs/old", "/docs/new", "/docs/cf", "/docs/again",
                    "/docs/new", "/docs/n.txt"]


def test_crawl_follows_links_within_the_profile_scope(server, tmp_path, browser):
    base, script, seen = server
    _, _, page = browser
    script["/robots.txt"] = (404, {}, b"")
    script["/docs/"] = (200, HTML, b"shell")
    script["/docs/a"] = (200, HTML, b"shell")
    page.evaluate.side_effect = [[base + "/docs/a", base + "/blog/x", "http://other.invalid/"],
                                 []]
    crawl_with(base, tmp_path)
    assert seen == ["/robots.txt", "/docs/", "/docs/a"]  # the start URL's directory only


def test_crawl_follows_links_as_the_engine_requests_them(server, tmp_path, browser):
    """A followed link carries its page as Referer; a known non-page type that
    --include-extensions leaves out is never requested (mirror's pre-filter)."""
    base, script, seen = server
    _, _, page = browser
    referers = []
    script["/robots.txt"] = (404, {}, b"")
    script["/docs/"] = (200, HTML, b"shell")
    script["/docs/a"] = lambda h: referers.append(h.get("Referer")) or (200, HTML, b"shell")
    page.evaluate.side_effect = [[base + "/docs/a", base + "/docs/f.pdf", base + "/docs/i.png"],
                                 []]
    crawl_with(base, tmp_path)
    assert seen == ["/robots.txt", "/docs/", "/docs/a"]
    assert referers == [base + "/docs/"]


def test_crawl_link_past_depth_is_no_filter_decision(server, tmp_path, browser):
    """As the crawl without a navigator: a link it drops for --depth is not --filter's."""
    base, script, seen = server
    _, _, page = browser
    script["/robots.txt"] = (404, {}, b"")
    script["/docs/"] = (200, HTML, b"shell")
    script["/docs/a"] = (200, HTML, b"shell")
    page.evaluate.side_effect = [[base + "/docs/a", base + "/docs/no-1"], [base + "/docs/no-2"]]
    filters = UrlFilters(["-*/no-*"])
    crawl_with(base, tmp_path, filters=filters, depth=1)
    assert seen == ["/robots.txt", "/docs/", "/docs/a"]
    assert filters.excluded == {base + "/docs/no-1"}


def test_crawl_page_the_browser_fails_on_is_a_report_error(server, tmp_path, browser):
    base, script, _ = server
    _, _, page = browser
    script["/robots.txt"] = (404, {}, b"")
    script["/docs/"] = (200, HTML, b"shell")

    def goto(u, **_):
        if u != "about:blank":
            raise Exception("Timeout 10000ms exceeded.\nCall log: ...")
    page.goto.side_effect = goto
    nav, res = crawl_with(base, tmp_path)
    assert res.files_downloaded == []
    assert nav.report.errors == [(base + "/docs/", "browser: Timeout 10000ms exceeded.", None)]


def test_write_failure_is_recorded_as_the_engine_records_it(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/docs/a"] = (200, HTML, b"a")
    nav, ctx, page = navigator(base, tmp_path)
    (tmp_path / base.split("//")[1] / "docs" / "a.html").mkdir(parents=True)  # a dir in the way
    final = nav.prepare(base + "/docs/a")
    navigate(ctx, page, final)
    assert nav.save(base + "/docs/a", "<p>a</p>") is None
    ((url, why, via),) = nav.report.errors
    assert (url, via) == (base + "/docs/a", None) and why.startswith("write failed: ")


def test_raw_file_gets_its_last_modified_time_too(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/docs/n.txt"] = (200, {"content-type": "text/plain", "last-modified": LM}, b"n")
    nav, ctx, page = navigator(base, tmp_path, exts="txt")
    navigate(ctx, page, nav.prepare(base + "/docs/n.txt"))
    path = nav.save(base + "/docs/n.txt", "<pre>n</pre>")
    nav.finish()
    assert os.path.getmtime(path) == calendar.timegm((2026, 11, 18, 10, 0, 0))
