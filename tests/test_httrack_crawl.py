import os
import threading

import pytest

from dograpper.lib.httrack.crawl import fetch_url_list
from dograpper.lib.httrack.fetcher import Fetcher
from dograpper.lib.httrack.policy import build_policy
from dograpper.lib.httrack.report import RunReport, format_report

HTML = {"content-type": "text/html"}


class FakeTime:
    def __init__(self):
        self.now = 1000.0
        self.lock = threading.Lock()

    def clock(self):
        return self.now

    def sleep(self, s):
        with self.lock:
            self.now += s


def run(urls, out, exts="html", **kw):
    policy = build_policy(retries=0, **kw)
    ft = FakeTime()
    return fetch_url_list(urls, str(out), policy, exts,
                          fetcher=Fetcher(policy, clock=ft.clock, sleep=ft.sleep))


def test_writes_only_2xx_non_challenge(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/ok"] = (200, HTML, b"<p>ok</p>")
    script["/gone"] = (404, HTML, b"<p>gone</p>")
    script["/cf"] = (403, {**HTML, "cf-mitigated": "challenge"}, b"<p>x</p>")
    res = run([f"{base}/ok", f"{base}/gone", f"{base}/cf"], tmp_path)
    assert len(res.files_downloaded) == 1 and res.files_downloaded[0].endswith("ok.html")
    assert open(res.files_downloaded[0], "rb").read() == b"<p>ok</p>"
    assert res.success and not res.front_failed and res.files_skipped == 0
    assert res.report.challenged == [f"{base}/cf"]
    assert [e[:2] for e in res.report.errors] == [(f"{base}/gone", "HTTP 404")]
    assert res.report.status_counts["2xx"] == 1 and res.report.status_counts["4xx"] == 2
    assert sum(len(f) for _, _, f in os.walk(tmp_path)) == 1


def test_robots_blocked_not_fetched(server, tmp_path):
    base, script, seen = server
    script["/robots.txt"] = (200, {"content-type": "text/plain"}, b"User-agent: *\nDisallow: /private\n")
    script["/private/a"] = (200, HTML, b"secret")
    res = run([f"{base}/private/a"], tmp_path)
    assert "/private/a" not in seen
    assert res.report.robots_blocked == [f"{base}/private/a"]
    assert res.files_downloaded == [] and res.front_failed


def test_cross_host_redirect_reported_out_of_scope(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/go"] = (302, {"location": "http://example.invalid/x"}, b"")
    res = run([f"{base}/go"], tmp_path)
    assert res.report.out_of_scope == ["http://example.invalid/x"]
    assert res.files_downloaded == [] and not res.front_failed


def test_same_host_redirect_is_followed_and_final_url_named(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/old"] = (301, {"location": "/new"}, b"")
    script["/new"] = (200, HTML, b"<p>n</p>")
    res = run([f"{base}/old"], tmp_path)
    assert [os.path.basename(f) for f in res.files_downloaded] == ["new.html"]


def test_redirect_target_refused_by_filters_is_not_fetched(server, tmp_path):
    from dograpper.lib.url_filter import UrlFilters
    base, script, seen = server
    script["/robots.txt"] = (404, {}, b"")
    script["/old"] = (301, {"location": "/Special:Login"}, b"")
    script["/Special:Login"] = (200, HTML, b"<p>login</p>")
    filters = UrlFilters(["-*Special:*"])
    policy = build_policy(retries=0)
    ft = FakeTime()
    res = fetch_url_list([f"{base}/old"], str(tmp_path), policy, "html",
                         fetcher=Fetcher(policy, clock=ft.clock, sleep=ft.sleep), filters=filters)
    assert res.files_downloaded == [] and not res.front_failed
    assert "/Special:Login" not in seen
    assert filters.excluded == {f"{base}/Special:Login"}


def test_redirect_with_undecodable_body_is_followed(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/old"] = (301, {"location": "/new", "content-encoding": "gzip"}, b"not gzip")
    script["/new"] = (200, HTML, b"<p>n</p>")
    res = run([f"{base}/old"], tmp_path)
    assert [os.path.basename(f) for f in res.files_downloaded] == ["new.html"]
    assert res.report.errors == [] and res.report.status_counts["3xx"] == 1


def test_redirect_loop_is_an_error(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/a"] = (302, {"location": "/a"}, b"")
    res = run([f"{base}/a"], tmp_path)
    assert res.report.errors == [(f"{base}/a", "too many redirects", None)]


def test_front_failed_when_all_challenged(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    for p in ("/a", "/b"):
        script[p] = (403, {**HTML, "cf-mitigated": "challenge"}, b"")
    res = run([f"{base}/a", f"{base}/b"], tmp_path)
    assert res.front_failed and not res.success and res.files_downloaded == []


def test_max_links_sets_partial(server, tmp_path):
    base, script, seen = server
    script["/robots.txt"] = (404, {}, b"")
    for p in ("/a", "/b", "/c"):
        script[p] = (200, HTML, b"<p>x</p>")
    res = run([f"{base}/a", f"{base}/b", f"{base}/c"], tmp_path, max_links=2)
    assert res.report.partial and len(res.files_downloaded) == 2
    assert "/c" not in seen


def test_include_extensions_filters_written_files(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/p"] = (200, HTML, b"<p>x</p>")
    script["/i.png"] = (200, {"content-type": "image/png"}, b"\x89PNG")
    res = run([f"{base}/p", f"{base}/i.png"], tmp_path, exts="html")
    assert [os.path.basename(f) for f in res.files_downloaded] == ["p.html"]


def test_write_conflict_is_recorded_and_run_continues(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/a"] = (200, {"content-type": "text/plain"}, b"x")
    script["/a/b"] = (200, {"content-type": "text/plain"}, b"y")
    res = run([f"{base}/a", f"{base}/a/b"], tmp_path, exts="", connections=1)
    assert len(res.files_downloaded) == 1
    assert len(res.report.errors) == 1 and res.report.errors[0][1].startswith("write failed")


def test_cdn_cgi_skipped_without_request(server, tmp_path):
    base, script, seen = server
    script["/robots.txt"] = (404, {}, b"")
    res = run([f"{base}/cdn-cgi/trace"], tmp_path)
    assert "/cdn-cgi/trace" not in seen
    assert res.report.out_of_scope == [f"{base}/cdn-cgi/trace"]


def test_report_urls_are_redacted(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    url = base.replace("http://", "http://user:pw@") + "/missing"
    res = run([url], tmp_path)
    assert res.report.errors[0][0] == f"{base}/missing"


def test_format_report_truncates_errors_unless_verbose():
    r = RunReport(errors=[(f"http://h/{i:02d}", "HTTP 500", None) for i in range(15)])
    short = "\n".join(format_report(r, verbose=False))
    full = "\n".join(format_report(r, verbose=True))
    assert "http://h/09" in short and "http://h/10" not in short and "5 more" in short
    assert "http://h/14" in full and "more" not in full


def test_seeds_redirecting_to_one_target_write_one_file(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/a"] = (301, {"location": "/t"}, b"")
    script["/b"] = (301, {"location": "/t"}, b"")
    script["/t"] = (200, HTML, b"<p>t</p>")
    res = run([f"{base}/a", f"{base}/b", f"{base}/t"], tmp_path)
    assert [os.path.basename(f) for f in res.files_downloaded] == ["t.html"]
    assert list(res.urls.values()) == [f"{base}/t"]  # the seed that needed no redirect


def test_seeds_redirecting_to_one_file_record_the_smallest_url(server, tmp_path):
    """Whichever thread writes first, the manifest gets the same URL."""
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/b"] = (301, {"location": "/t"}, b"")
    script["/a"] = (301, {"location": "/t"}, b"")
    script["/t"] = (200, HTML, b"<p>t</p>")
    res = run([f"{base}/b", f"{base}/a"], tmp_path)
    assert list(res.urls.values()) == [f"{base}/a"]


def test_each_written_file_maps_to_the_url_fetched(server, tmp_path):
    """#94: the manifest records these instead of rebuilding a URL from the name."""
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/wiki/Category:En"] = (200, HTML, b"<p>c</p>")
    script["/w/index.php?title=A"] = (200, HTML, b"<p>q</p>")
    script["/old"] = (301, {"location": "/new"}, b"")
    script["/new"] = (200, HTML, b"<p>n</p>")
    script["/gone"] = (404, HTML, b"<p>x</p>")
    res = run([f"{base}/wiki/Category:En", f"{base}/w/index.php?title=A", f"{base}/old",
               f"{base}/gone"], tmp_path)
    assert sorted(res.urls) == res.files_downloaded
    by_name = {os.path.basename(f): u for f, u in res.urls.items()}
    assert by_name.pop("Category_En.html") == f"{base}/wiki/Category:En"
    assert by_name.pop("new.html") == f"{base}/old"  # named after the target, URL as requested
    assert list(by_name.values()) == [f"{base}/w/index.php?title=A"]


def test_malformed_seed_is_recorded_and_run_continues(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/ok"] = (200, HTML, b"<p>ok</p>")
    res = run(["http://[x", f"{base}/ok"], tmp_path)
    assert len(res.files_downloaded) == 1
    assert res.report.errors == [("<redacted url>", "malformed URL", None)]


def test_malformed_redirect_location_is_recorded(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/r"] = (302, {"location": "http://[x"}, b"")
    res = run([f"{base}/r"], tmp_path)
    assert res.report.errors == [(f"{base}/r", "malformed redirect Location", None)]


def test_filtered_pages_are_reported(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/i.png"] = (200, {"content-type": "image/png"}, b"\x89PNG")
    res = run([f"{base}/i.png"], tmp_path, exts="html")
    assert res.report.filtered == [f"{base}/i.png"] and res.files_downloaded == []
    short = "\n".join(format_report(res.report, verbose=False))
    full = "\n".join(format_report(res.report, verbose=True))
    assert "Filtered by --include-extensions: 1" in short and "i.png" not in short
    assert f"{base}/i.png" in full


def test_control_chars_in_location_never_reach_the_report(server, tmp_path):
    base, script, _ = server
    script["/robots.txt"] = (404, {}, b"")
    script["/r"] = (302, {"location": "http://example.invalid/\x1b[31mx\x9by"}, b"")
    res = run([f"{base}/r"], tmp_path)
    out = "\n".join(format_report(res.report, verbose=True))
    assert "\x1b" not in out and "\r" not in out and "example.invalid" in out


def test_format_report_escapes_control_chars_in_reasons():
    r = RunReport(errors=[("http://h/x", "bad \x1b[31m thing\x07", "http://h/\x1b")])
    out = "\n".join(format_report(r, verbose=True))
    assert "\x1b" not in out and "\x07" not in out and "\\x1b" in out


@pytest.mark.parametrize("rule,seed,wire", [
    ("/a%20b", "/a b", "/a%20b"),
    ("/caf%C3%A9", "/caf\u00e9", "/caf%c3%a9"),
    ("/caf%c3%a9", "/caf\u00e9", "/caf%c3%a9"),
])
def test_robots_matches_escaped_wire_target(server, tmp_path, rule, seed, wire):
    base, script, seen = server
    script["/robots.txt"] = (200, {"content-type": "text/plain"},
                             f"User-agent: *\nDisallow: {rule}\n".encode())
    script[wire] = (200, HTML, b"x")
    res = run([base + seed], tmp_path)
    assert wire not in seen and len(res.report.robots_blocked) == 1


def test_robots_allows_other_encoded_path(server, tmp_path):
    base, script, seen = server
    script["/robots.txt"] = (200, {"content-type": "text/plain"},
                             b"User-agent: *\nDisallow: /a%20b\n")
    script["/c%20d"] = (200, HTML, b"x")
    res = run([f"{base}/c d"], tmp_path)
    assert "/c%20d" in seen and res.report.robots_blocked == []
