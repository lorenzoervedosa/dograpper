import gzip
import logging
import threading
import zlib
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dograpper.lib.httrack.challenge import is_challenge
from dograpper.lib.httrack.fetcher import Fetcher
from dograpper.lib.httrack.policy import build_policy, request_headers
from dograpper.lib.httrack.robots import NO_RULES


class FakeTime:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []
        self.lock = threading.Lock()

    def clock(self):
        return self.now

    def sleep(self, s):
        with self.lock:
            self.sleeps.append(s)
            self.now += s


@pytest.fixture
def server():
    script, seen = {}, []

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            seen.append((self.path, list(self.headers.items())))
            q = script.get(self.path)
            if q is None:
                status, hdrs, body = 404, {}, b"nope"
            else:
                status, hdrs, body = q.pop(0) if len(q) > 1 else q[0]
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


def make(**kw):
    ft = FakeTime()
    return Fetcher(build_policy(**kw), clock=ft.clock, sleep=ft.sleep), ft


def test_is_challenge_header():
    assert is_challenge(403, {"cf-mitigated": "challenge"}, b"")


def test_is_challenge_title():
    body = b"<html><title>\n Just a Moment... </title></html>"
    assert is_challenge(200, {}, body)
    assert not is_challenge(403, {}, body)


def test_real_page_with_jsd_beacon_is_not_challenge():
    body = (b"<title>Overview</title><script src='/cdn-cgi/challenge-platform/"
            b"scripts/jsd/main.js'></script>")
    assert is_challenge(200, {}, body) is False


def test_retries_429_then_200(server):
    base, script, _ = server
    script["/a"] = [(429, {}, b""), (200, {}, b"ok")]
    f, _ = make(retries=2)
    r = f.get(base + "/a", kind="navigate")
    assert (r.status, r.body, r.attempts, r.error) == (200, b"ok", 2, None)


@pytest.mark.parametrize("status", [403, 404])
def test_no_retry_on_403_404(server, status):
    base, script, seen = server
    script["/a"] = [(status, {}, b"x")]
    f, _ = make(retries=3)
    r = f.get(base + "/a", kind="navigate")
    assert r.status == status and r.attempts == 1 and len(seen) == 1


def test_503_without_retry_after_not_retried(server):
    base, script, _ = server
    script["/a"] = [(503, {}, b""), (200, {}, b"ok")]
    f, _ = make(retries=2)
    assert f.get(base + "/a", kind="navigate").attempts == 1
    script["/b"] = [(503, {"Retry-After": "1"}, b""), (200, {}, b"ok")]
    r = f.get(base + "/b", kind="navigate")
    assert (r.status, r.attempts) == (200, 2)


def test_retry_after_gate_blocks_all_workers(server):
    base, script, _ = server
    script["/a"] = [(429, {"Retry-After": "5"}, b"")]
    script["/b"] = [(200, {}, b"ok")]
    f, ft = make(retries=0)
    assert f.get(base + "/a", kind="navigate").status == 429
    ft.sleeps.clear()
    out = []
    t = threading.Thread(target=lambda: out.append(f.get(base + "/b", kind="navigate")))
    t.start()
    t.join(10)
    assert out[0].status == 200
    assert ft.sleeps[0] == pytest.approx(5.0)


def test_retry_after_capped_and_past_date(server, caplog):
    base, script, _ = server
    script["/a"] = [(429, {"Retry-After": "9999"}, b"")]
    past = format_datetime(datetime.now(timezone.utc) - timedelta(hours=1), usegmt=True)
    script["/p"] = [(429, {"Retry-After": past}, b"")]
    script["/ok"] = [(200, {}, b"")]
    f, ft = make(retries=0, max_retry_after=30)
    with caplog.at_level(logging.WARNING):
        f.get(base + "/a", kind="navigate")
    msg = " ".join(r.getMessage() for r in caplog.records)
    assert "/a" in msg and "9999" in msg and "30" in msg
    ft.sleeps.clear()
    f.get(base + "/ok", kind="navigate")
    assert ft.sleeps[0] == pytest.approx(30.0)
    f2, ft2 = make(retries=0)
    f2.get(base + "/p", kind="navigate")
    f2.get(base + "/ok", kind="navigate")
    assert ft2.sleeps == []


def test_gzip_and_deflate_decoded(server):
    base, script, _ = server
    script["/g"] = [(200, {"Content-Encoding": "gzip"}, gzip.compress(b"hello"))]
    script["/z"] = [(200, {"Content-Encoding": "deflate"}, zlib.compress(b"hello"))]
    raw = zlib.compressobj(wbits=-15)
    script["/r"] = [(200, {"Content-Encoding": "deflate"}, raw.compress(b"hello") + raw.flush())]
    script["/x"] = [(200, {"Content-Encoding": "weird"}, b"zz")]
    f, _ = make()
    for p in ("/g", "/z", "/r"):
        assert f.get(base + p, kind="navigate").body == b"hello"
    r = f.get(base + "/x", kind="navigate")
    assert r.error and r.body == b""


def test_challenged_flag_and_location(server):
    base, script, _ = server
    script["/c"] = [(200, {}, b"<title>Just a moment...</title>")]
    script["/l"] = [(301, {"Location": "/z"}, b"")]
    f, _ = make()
    assert f.get(base + "/c", kind="navigate").challenged
    r = f.get(base + "/l", kind="navigate")
    assert (r.status, r.location) == (301, "/z")


def test_crawl_delay_paces_same_host(server):
    base, script, _ = server
    script["/robots.txt"] = [(200, {}, b"User-agent: *\nCrawl-delay: 2\n")]
    script["/a"] = [(200, {}, b"")]
    f, ft = make()
    assert f.robots_for(base).crawl_delay == 2
    stamps = []
    for _ in range(3):
        f.get(base + "/a", kind="navigate")
        stamps.append(ft.now)
    assert stamps[1] - stamps[0] >= 2 and stamps[2] - stamps[1] >= 2


def test_conn_rate_and_bandwidth_buckets(server):
    base, script, _ = server
    script["/c"] = [(200, {"Connection": "close"}, b"")]
    f, ft = make(max_conn_rate=2.0)
    for _ in range(3):
        f.get(base + "/c", kind="navigate")
    assert sum(ft.sleeps) >= 1.0 - 1e-6  # 3 new connections at 2/s
    script["/big"] = [(200, {}, b"x" * 2000)]
    f, ft = make(max_bandwidth=1000)
    f.get(base + "/big", kind="navigate")
    assert sum(ft.sleeps) >= 2.0 - 1e-6


def test_robots_non_200_is_no_rules(server):
    base, script, seen = server
    f, _ = make()
    assert f.robots_for(base) is NO_RULES
    f.robots_for(base)
    assert len(seen) == 1  # cached
    f2, _ = make(obey_robots=False)
    assert f2.robots_for(base) is NO_RULES
    assert len(seen) == 1


def test_request_headers_sent_in_order(server):
    base, script, seen = server
    script["/p?q=1"] = [(200, {}, b"")]
    f, _ = make()
    f.get(base + "/p?q=1", kind="linked", referer=base + "/")
    host = base.split("//")[1]
    assert seen[0][1] == request_headers(f.policy, host, kind="linked", referer=base + "/")
    f.get(base + "/p?q=1", kind="navigate")
    assert len(seen) == 2  # persistent connection reused
