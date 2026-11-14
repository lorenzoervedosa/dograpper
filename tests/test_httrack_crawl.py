import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

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


# Second copy of the local-server fixture in test_httrack_fetcher.py; factor it out on the third.
@pytest.fixture
def server():
    script, seen = {}, []

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            seen.append(self.path)
            status, hdrs, body = script.get(self.path, (404, {}, b"nope"))
            self.send_response(status)
            for k, v in hdrs.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}", script, seen
    srv.shutdown()
    srv.server_close()
    t.join(5)


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
