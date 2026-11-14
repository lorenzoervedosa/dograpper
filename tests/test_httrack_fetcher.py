import gzip
import time
import logging
import threading
import zlib
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from dograpper.lib.httrack.challenge import is_challenge
from dograpper.lib.httrack import fetcher as fetcher_mod, policy as policy_mod
from dograpper.lib.httrack.fetcher import Fetcher
from dograpper.lib.httrack.policy import build_policy, request_headers
from dograpper.lib.httrack.robots import NO_RULES


class FakeTime:
    def __init__(self):
        self.now = 1000.0
        self.sleeps = []
        self.lock = threading.Lock()
        self.on_sleep = None

    def clock(self):
        return self.now

    def sleep(self, s):
        if self.on_sleep:
            self.on_sleep(s)
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
            if status is None:  # drop the connection without answering
                self.close_connection = True
                return
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


def test_is_challenge_is_linear_on_hostile_bodies():
    t0 = time.perf_counter()
    assert not is_challenge(200, {}, b"<title" * 25000)
    assert not is_challenge(200, {}, b"<title>" * 25000)
    assert time.perf_counter() - t0 < 1.0


def test_decompression_bomb_and_oversize_body_rejected(server, monkeypatch):
    base, script, _ = server
    monkeypatch.setattr(fetcher_mod, "MAX_BODY_BYTES", 1000)
    script["/bomb"] = [(200, {"Content-Encoding": "gzip"}, gzip.compress(b"a" * 100000))]
    script["/raw"] = [(200, {}, b"x" * 2000)]
    f, _ = make()
    for p in ("/bomb", "/raw"):
        r = f.get(base + p, kind="navigate")
        assert r.error == "body too large" or "body too large" in r.error
        assert r.body == b""


def test_truncated_and_stacked_encodings(server):
    base, script, _ = server
    script["/t"] = [(200, {"Content-Encoding": "gzip"}, gzip.compress(b"hello" * 100)[:-10])]
    script["/3"] = [(200, {"Content-Encoding": "gzip, gzip, gzip"}, gzip.compress(b"x"))]
    script["/2"] = [(200, {"Content-Encoding": "gzip, gzip"}, gzip.compress(gzip.compress(b"hi")))]
    f, _ = make()
    assert "truncated" in f.get(base + "/t", kind="navigate").error
    assert "too many" in f.get(base + "/3", kind="navigate").error
    assert f.get(base + "/2", kind="navigate").body == b"hi"


def test_undecodable_encoding_when_decoder_missing(server, monkeypatch):
    base, script, _ = server
    monkeypatch.setattr(policy_mod, "_importable", lambda name: False)
    script["/br"] = [(200, {"Content-Encoding": "br"}, b"zz")]
    f, _ = make()
    r = f.get(base + "/br", kind="navigate")
    assert r.error and r.body == b""


def test_gate_set_while_worker_waits_is_honoured(server):
    base, script, _ = server
    script["/a"] = [(200, {}, b"")]
    script["/b"] = [(200, {}, b"")]
    f, ft = make(delay_ms=10000)
    f.get(base + "/a", kind="navigate")
    entered, release = threading.Event(), threading.Event()

    def hook(_s):
        if threading.current_thread() is not threading.main_thread() and not entered.is_set():
            entered.set()
            release.wait(5)

    ft.on_sleep = hook
    out = []
    t = threading.Thread(target=lambda: out.append(f.get(base + "/b", kind="navigate")))
    t.start()
    assert entered.wait(5)
    f._set_gate(base + "/x", 50)
    release.set()
    t.join(10)
    assert out[0].status == 200
    assert ft.now >= 1050  # the waiter re-checked the gate after its own sleep


def test_dropped_connection_is_retried_as_oserror(server):
    base, script, seen = server
    script["/d"] = [(None, {}, b""), (200, {}, b"ok")]
    f, _ = make(retries=1)
    r = f.get(base + "/d", kind="navigate")
    assert (r.status, r.attempts) == (200, 2)
    script["/e"] = [(None, {}, b"")]
    f0, _ = make(retries=0)
    r = f0.get(base + "/e", kind="navigate")
    assert r.status is None and r.error


def test_stale_keepalive_reconnects_within_attempt(server):
    base, script, seen = server
    script["/ok"] = [(200, {}, b"")]
    script["/s"] = [(None, {}, b""), (200, {}, b"y")]
    f, _ = make(retries=0)
    f.get(base + "/ok", kind="navigate")
    r = f.get(base + "/s", kind="navigate")
    assert (r.status, r.body, r.attempts) == (200, b"y", 1)
    assert [p for p, _ in seen].count("/s") == 2


def test_robots_same_host_redirect_followed(server):
    base, script, _ = server
    script["/robots.txt"] = [(301, {"Location": "/r2"}, b"")]
    script["/r2"] = [(200, {}, b"User-agent: *\nDisallow: /x\n")]
    f, _ = make()
    assert f.robots_for(base).allowed("/x") is False


def test_robots_cross_host_or_endless_redirect_is_no_rules(server):
    base, script, seen = server
    port = base.rsplit(":", 1)[1]
    script["/robots.txt"] = [(302, {"Location": f"http://localhost:{port}/evil"}, b"")]
    script["/evil"] = [(200, {}, b"User-agent: *\nDisallow: /\n")]
    f, _ = make()
    assert f.robots_for(base) is NO_RULES
    assert "/evil" not in [p for p, _ in seen]
    script["/loop"] = [(302, {"Location": "/loop"}, b"")]
    script["/robots.txt"] = [(302, {"Location": "/loop"}, b"")]
    f2, _ = make()
    assert f2.robots_for(base) is NO_RULES
    assert len(seen) <= 1 + 1 + 6  # bounded: 5 redirects at most


def test_crawl_delay_infinite_and_huge_are_sanitised(server, caplog):
    base, script, _ = server
    script["/a"] = [(200, {}, b"")]
    script["/robots.txt"] = [(200, {}, b"User-agent: *\nCrawl-delay: inf\n")]
    f, ft = make()
    f.robots_for(base)
    f.get(base + "/a", kind="navigate")
    f.get(base + "/a", kind="navigate")
    assert max(ft.sleeps, default=0) < 0.01  # only tiny bandwidth sleeps
    script["/robots.txt"] = [(200, {}, b"User-agent: *\nCrawl-delay: 100000\n")]
    f2, ft2 = make(max_retry_after=30)
    with caplog.at_level(logging.WARNING):
        f2.robots_for(base)
    assert "Crawl-delay" in caplog.text
    f2.get(base + "/a", kind="navigate")
    f2.get(base + "/a", kind="navigate")
    assert max(ft2.sleeps) == pytest.approx(30.0)


@pytest.mark.parametrize("url", ["http://127.0.0.1:99999/", "http://127.0.0.1:abc/",
                                 "ftp://example.com/", "http:///x"])
def test_invalid_url_returns_error_not_exception(url):
    f, _ = make()
    r = f.get(url, kind="navigate")
    assert r.error and r.status is None


def test_origin_normalisation_for_robots_and_pacing(server):
    base, script, seen = server
    script["/robots.txt"] = [(200, {}, b"User-agent: *\nCrawl-delay: 2\n")]
    script["/a"] = [(200, {}, b"")]
    f, ft = make()
    spelled = base.replace("http://", "HTTP://") + "/"
    assert f.robots_for(spelled).crawl_delay == 2
    assert f.robots_for(base).crawl_delay == 2
    assert [p for p, _ in seen] == ["/robots.txt"]
    f.get(base + "/a", kind="navigate")
    f.get(base + "/a", kind="navigate")
    assert max(ft.sleeps) >= 2 - 1e-6


def test_userinfo_never_logged(server, caplog):
    base, script, _ = server
    script["/a"] = [(429, {"Retry-After": "9999"}, b"")]
    f, _ = make(retries=0, max_retry_after=30)
    with caplog.at_level(logging.DEBUG):
        f.get(base.replace("http://", "http://alice:s3cret@") + "/a", kind="navigate")
    assert "s3cret" not in caplog.text and "alice" not in caplog.text
    assert "capped" in caplog.text


def test_empty_compressed_body_is_ok_and_redirect_keeps_location(server):
    base, script, _ = server
    script["/r"] = [(301, {"Location": "/z", "Content-Encoding": "gzip"}, b"")]
    script["/e"] = [(200, {"Content-Encoding": "gzip"}, b"")]
    f, _ = make()
    r = f.get(base + "/r", kind="navigate")
    assert (r.status, r.location, r.error) == (301, "/z", None)
    r = f.get(base + "/e", kind="navigate")
    assert (r.status, r.body, r.error) == (200, b"", None)


def test_location_survives_decode_failure(server):
    base, script, _ = server
    script["/r"] = [(302, {"Location": "/z", "Content-Encoding": "gzip"}, b"not gzip")]
    f, _ = make()
    r = f.get(base + "/r", kind="navigate")
    assert r.error and r.location == "/z"


# -- optional decoders: run only where they are installed (see task report) --

class _SpyDecompressor:
    def __init__(self, real):
        self.real, self.max_out = real, 0

    def process(self, *a, **k):
        out = self.real.process(*a, **k)
        self.max_out = max(self.max_out, len(out))
        return out

    def __getattr__(self, name):
        return getattr(self.real, name)


def _br_or_skip():
    pytest.importorskip("brotli")
    mod = policy_mod.decoder_module("br")
    if mod is None:
        pytest.skip("installed brotli lacks output_buffer_limit")
    return mod


def test_brotli_decode_bomb_and_truncation(server, monkeypatch):
    mod = _br_or_skip()
    base, script, _ = server
    assert fetcher_mod._decode(mod.compress(b"hello"), "br") == b"hello"
    monkeypatch.setattr(fetcher_mod, "MAX_BODY_BYTES", 1000)
    bomb = mod.compress(b"\0" * 20_000_000, quality=1)
    spies = []

    class Proxy:
        @staticmethod
        def Decompressor():
            spies.append(_SpyDecompressor(mod.Decompressor()))
            return spies[-1]

    with pytest.raises(ValueError, match="body too large"):
        fetcher_mod._brotli(Proxy, bomb)
    assert spies[0].max_out < 1_000_000  # bounded per call, not 20 MB at once
    script["/b"] = [(200, {"Content-Encoding": "br"}, bomb)]
    f, _ = make()
    assert "body too large" in f.get(base + "/b", kind="navigate").error
    monkeypatch.setattr(fetcher_mod, "MAX_BODY_BYTES", 64 * 1024 * 1024)
    cut = mod.compress(b"hello world" * 1000)[:-4]
    with pytest.raises(ValueError, match="truncated"):
        fetcher_mod._decode(cut, "br")


def _zstd_or_skip():
    mod = policy_mod.decoder_module("zstd")
    if mod is None:
        pytest.skip("no zstd decoder installed")
    return mod


def _zstd_frames(data: bytes) -> list[bytes]:
    """Known-size and (where the package can) unknown-size frames."""
    try:
        import zstandard
    except ImportError:
        from compression import zstd
        return [zstd.compress(data)]
    c = zstandard.ZstdCompressor().compressobj()
    return [zstandard.ZstdCompressor().compress(data), c.compress(data) + c.flush()]


def test_zstd_decode_bomb_and_truncation(monkeypatch):
    _zstd_or_skip()
    payload = b"\0" * 5_000_000
    for frame in _zstd_frames(payload):
        assert fetcher_mod._decode(frame, "zstd") == payload
        with pytest.raises(ValueError, match="truncated|too large"):
            fetcher_mod._decode(frame[:-5], "zstd")
    monkeypatch.setattr(fetcher_mod, "MAX_BODY_BYTES", 1000)
    for frame in _zstd_frames(payload):
        with pytest.raises(ValueError, match="body too large"):
            fetcher_mod._decode(frame, "zstd")
    monkeypatch.setattr(fetcher_mod, "MAX_BODY_BYTES", 64 * 1024 * 1024)
    cut = _zstd_frames(b"hello world" * 1000)[-1][:-3]
    with pytest.raises(ValueError, match="truncated"):
        fetcher_mod._decode(cut, "zstd")
