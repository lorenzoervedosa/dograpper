"""fire-engine downloader (ADR-0011): curl_cffi transport.

The real curl_cffi is an optional native dependency: most tests inject a fake
session so they run without it, and the smoke tests at the end run the real
library against the local `server` fixture, skipped when the extra is absent.
No test touches the network.
"""
import base64
import gzip
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.lib.fire_engine import fetcher as fire_fetcher
from dograpper.lib.fire_engine.fetcher import (CurlCffiFetcher, _MISSING,
                                               _default_session_factory, split_proxy)
from dograpper.lib.httrack import fetcher as httrack_fetcher
from dograpper.lib.httrack.policy import build_policy, decoder_module


LM = "Mon, 01 Jan 2024 00:00:00 GMT"


class FakeResp:
    def __init__(self, status=200, headers=None, content=b"<html>ok</html>", chunks=None):
        self.status_code = status
        self.headers = headers or {}
        self.chunks = chunks if chunks is not None else [content]


class FakeCurlError(Exception):
    pass


class FakeSession:
    """curl's side of a transfer: each chunk goes to the writer (content_callback), and a
    writer that does not take the whole chunk aborts it, as libcurl does (error 23)."""

    def __init__(self, resp):
        self.resp = resp
        self.calls = []
        self.delivered = 0

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        for chunk in self.resp.chunks:
            self.delivered += 1
            if kw["content_callback"](chunk) != len(chunk):
                raise FakeCurlError("curl: (23) Failure writing output to destination")
        return self.resp


def make_fetcher(resp, *, proxy=None, impersonate="chrome124"):
    session = FakeSession(resp)
    captured = {}

    def factory(imp, timeout):
        captured["impersonate"], captured["timeout"] = imp, timeout
        return session

    fetcher = CurlCffiFetcher(
        build_policy(), proxy=proxy, impersonate=impersonate,
        session_factory=factory, sleep=lambda _s: None,
    )
    return fetcher, session, captured


def test_get_returns_decoded_body_and_passes_impersonate():
    resp = FakeResp(content=b"<html>hello</html>")
    fetcher, session, captured = make_fetcher(resp)

    res = fetcher.get("https://example.com/docs/", kind="navigate")

    assert res.status == 200
    assert res.body == b"<html>hello</html>"
    assert res.challenged is False
    assert captured["impersonate"] == "chrome124"
    method, url, _kw = session.calls[0]
    assert method == "GET"
    assert url == "https://example.com/docs/"


def test_proxy_is_forwarded_to_the_session_with_its_credentials_apart():
    """The credentials leave the proxy URL for curl's proxy username/password options:
    curl quotes a proxy URL it cannot use in its errors, which reach the run report."""
    fetcher, session, _ = make_fetcher(FakeResp(), proxy="http://user:pw@proxy:8080")

    fetcher.get("https://example.com/", kind="navigate")

    _m, _u, kw = session.calls[0]
    assert kw["proxies"] == {"http": "http://proxy:8080", "https": "http://proxy:8080"}
    assert kw["proxy_auth"] == ("user", "pw")


@pytest.mark.parametrize("proxy,url,auth", [
    ("http://proxy:8080", "http://proxy:8080", None),
    ("socks5h://u:p@proxy:1080", "socks5h://proxy:1080", ("u", "p")),
    ("user:s3cret@proxy:8080", "proxy:8080", ("user", "s3cret")),  # no scheme: curl's http
    ("http://user:s3cret@proxy:8080/p@th?q=@#@", "http://proxy:8080/p@th?q=@#@",
     ("user", "s3cret")),  # an @ past the authority is not userinfo
    ("http://us%3Aer:s3%40cr%3Aet@proxy:8080", "http://proxy:8080", ("us:er", "s3@cr:et")),
    ("http://us@er:s3cret@proxy:8080", "http://proxy:8080", ("us@er", "s3cret")),
    ("http://user@proxy:8080", "http://proxy:8080", ("user", "")),
    ("http://@proxy:8080", "http://proxy:8080", None),
])
def test_split_proxy_reads_the_authority_as_curl_does(proxy, url, auth):
    assert split_proxy(proxy) == (url, auth)


def test_no_proxy_means_no_proxies_kwarg_value():
    fetcher, session, _ = make_fetcher(FakeResp())

    fetcher.get("https://example.com/", kind="navigate")

    _m, _u, kw = session.calls[0]
    assert kw["proxies"] is None


def test_only_the_referer_and_the_validators_reach_curl():
    """The impersonated browser sends its own identity (User-Agent, Accept*, Sec-Fetch-*);
    of the httrack header set only what is specific to this request goes to curl."""
    fetcher, session, _ = make_fetcher(FakeResp(status=304, content=b""))
    validators = (("If-None-Match", '"v1"'), ("If-Modified-Since", LM))

    res = fetcher.get("https://example.com/a", kind="linked", referer="https://example.com/",
                      validators=validators)

    assert res.status == 304
    _m, _u, kw = session.calls[0]
    assert kw["headers"] == {"If-None-Match": '"v1"', "If-Modified-Since": LM,
                             "Referer": "https://example.com/"}


def test_cloudflare_challenge_is_detected_from_header():
    resp = FakeResp(status=403, headers={"cf-mitigated": "challenge"},
                    content=b"<html><title>Just a moment...</title></html>")
    fetcher, _session, _ = make_fetcher(resp)

    res = fetcher.get("https://example.com/", kind="navigate")

    assert res.challenged is True


def test_the_raw_body_is_decoded_by_the_bounded_httrack_decoder():
    """curl's decoding is off (the default factory sets HTTP_CONTENT_DECODING 0): the
    encoded body and its Content-Encoding reach Fetcher.get, which decodes within
    MAX_BODY_BYTES and the zstd window cap, as on the stdlib path."""
    resp = FakeResp(headers={"Content-Encoding": "gzip"}, content=gzip.compress(b"plain text"))
    fetcher, _session, _ = make_fetcher(resp)

    res = fetcher.get("https://example.com/", kind="navigate")

    assert (res.body, res.headers["content-encoding"]) == (b"plain text", "gzip")


def test_a_body_over_the_cap_aborts_the_transfer_at_curls_writer(monkeypatch):
    """The cap holds where curl hands bytes over: the chunk past it is refused and curl
    stops, so nothing past the cap is buffered or charged to the bandwidth."""
    monkeypatch.setattr("dograpper.lib.fire_engine.fetcher.MAX_BODY_BYTES", 10)
    resp = FakeResp(chunks=[b"x" * 8, b"y" * 8, b"z" * 8])
    fetcher, session, _ = make_fetcher(resp)
    charged = []
    fetcher._charge_bandwidth = charged.append

    res = fetcher.get("https://example.com/", kind="navigate")

    assert (res.status, res.error) == (None, "body too large")
    assert session.delivered == 2  # the third chunk never came: the transfer was aborted
    assert charged == [8]
    assert res.attempts == 1  # an oversized body is not retried


def test_the_policy_timeout_reaches_the_session_factory():
    fetcher, _session, captured = make_fetcher(FakeResp())

    fetcher.get("https://example.com/", kind="navigate")

    assert captured["timeout"] == 120.0


def test_userinfo_is_stripped_from_the_url_sent_to_curl():
    fetcher, session, _ = make_fetcher(FakeResp())

    fetcher.get("https://user:pass@example.com/docs?q=1", kind="navigate")

    _m, url, _kw = session.calls[0]
    assert url == "https://example.com/docs?q=1"


def test_an_explicit_port_reaches_curl_once():
    fetcher, session, _ = make_fetcher(FakeResp())

    fetcher.get("http://u:p@127.0.0.1:8080/docs?q=1", kind="navigate")

    _m, url, _kw = session.calls[0]
    assert url == "http://127.0.0.1:8080/docs?q=1"


def test_default_factory_without_curl_cffi_raises_friendly_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "curl_cffi", None)  # forces ImportError
    with pytest.raises(RuntimeError) as exc:
        _default_session_factory("chrome124", 1.0)
    assert "fire-engine" in str(exc.value)
    assert str(exc.value) == _MISSING


def test_missing_curl_cffi_surfaces_before_any_request():
    """The first GET (robots.txt, in run_fire_engine) must raise the friendly error,
    not have it wrapped as a transport OSError that the run retries and reports."""
    def factory(_imp, _timeout):
        raise RuntimeError(_MISSING)

    fetcher = CurlCffiFetcher(build_policy(), session_factory=factory, sleep=lambda _s: None)
    with pytest.raises(RuntimeError, match="uv sync --extra fire-engine"):
        fetcher.robots_for("https://example.com")


@pytest.mark.parametrize("extra", [[], ["--no-robots"]])
def test_missing_curl_cffi_is_a_friendly_cli_error(tmp_path, monkeypatch, extra):
    """Without robots.txt the first session opens in discovery, not in robots_for: the
    install hint must still be the error, never a traceback. No request is made."""
    monkeypatch.setitem(sys.modules, "curl_cffi", None)
    out = str(tmp_path / "o")
    result = CliRunner().invoke(
        cli, ["download", "http://127.0.0.1:9/", "-o", out, "--manifest", out + ".json",
              "--downloader", "fire-engine", *extra])
    assert result.exit_code == 1, result.output
    assert _MISSING in result.output


# -- CLI wiring (no network: run_fire_engine is stubbed) --------------------

def test_proxy_without_fire_engine_is_a_usage_error(tmp_path):
    result = CliRunner().invoke(
        cli, ["download", "http://example.com/", "-o", str(tmp_path / "o"),
              "--proxy", "http://p:8080"])
    assert result.exit_code != 0
    assert "--proxy requires --downloader fire-engine" in result.output


def test_impersonate_without_fire_engine_is_a_usage_error(tmp_path):
    result = CliRunner().invoke(
        cli, ["download", "http://example.com/", "-o", str(tmp_path / "o"),
              "--downloader", "httrack", "--impersonate", "chrome124"])
    assert result.exit_code != 0
    assert "--impersonate requires --downloader fire-engine" in result.output


def test_fire_engine_dispatch_forwards_proxy_impersonate_and_the_previous_manifest(tmp_path):
    with patch("dograpper.commands.download.run_fire_engine",
               return_value=(2, 0, [], {}, {})) as stub:
        result = CliRunner().invoke(
            cli, ["download", "http://example.com/", "-o", str(tmp_path / "o"),
                  "--downloader", "fire-engine",
                  "--proxy", "http://p:1", "--impersonate", "chrome124"])
    assert result.exit_code == 0, result.output
    assert stub.call_count == 1
    assert stub.call_args.kwargs["proxy"] == "http://p:1"
    assert stub.call_args.kwargs["impersonate"] == "chrome124"
    assert stub.call_args.kwargs["previous"] is None  # first run: no manifest yet


# -- smoke tests over the real curl_cffi (skipped without the fire-engine extra) --
# The `server` fixture (conftest.py) stands in for the site, and for the proxy.

class _Clock:
    """Pacing without real sleeps: each sleep advances the clock it reads."""
    def __init__(self):
        self.now = 0.0

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def real_fetcher(**kw):
    pytest.importorskip("curl_cffi")
    clock = _Clock()
    return CurlCffiFetcher(build_policy(retries=0), clock=clock.clock, sleep=clock.sleep, **kw)


def recorded(log, reply):
    def answer(headers):
        log.append(headers)
        return reply
    return answer


def test_real_get_sends_the_impersonated_browser_identity(server):
    base, script, _ = server
    log = []
    script["/p"] = recorded(log, (200, {"Content-Type": "text/html"}, b"<html>hi</html>"))

    res = real_fetcher().get(base + "/p", kind="linked", referer=base + "/")

    assert (res.status, res.body, res.error) == (200, b"<html>hi</html>", None)
    assert res.headers["content-type"] == "text/html"
    assert "Chrome/" in log[0]["User-Agent"] and "dograpper" not in log[0]["User-Agent"]
    assert log[0]["Referer"] == base + "/"


def test_real_get_decodes_a_gzip_body(server):
    base, script, _ = server
    body = b"<html>" + b"word " * 5000 + b"</html>"
    script["/gz"] = (200, {"Content-Encoding": "gzip"}, gzip.compress(body))

    res = real_fetcher().get(base + "/gz", kind="navigate")

    assert (res.status, res.body, res.error) == (200, body, None)


def test_real_get_goes_through_the_proxy_with_its_credentials(server):
    base, script, seen = server
    log = []
    script["http://docs.example.invalid/page"] = recorded(log, (200, {}, b"via proxy"))

    res = real_fetcher(proxy=base.replace("http://", "http://user:pw@")).get(
        "http://docs.example.invalid/page", kind="navigate")

    assert (res.status, res.body) == (200, b"via proxy")
    assert seen == ["http://docs.example.invalid/page"]  # absolute URI: a forward proxy
    assert log[0]["Proxy-Authorization"] == "Basic " + base64.b64encode(b"user:pw").decode()


FAST = ["--disable-security-limits", "--max-conn-rate", "1000"]  # local server: no pacing wait


def _docs_site(script):
    words = " ".join(["documentation"] * 40)
    script["/robots.txt"] = (404, {}, b"")
    for path, link in (("/docs/", "a.html"), ("/docs/a.html", "./")):
        script[path] = (200, {"Content-Type": "text/html"},
                        f'<html><body><h1>{path}</h1><p>{words}</p>'
                        f'<a href="{link}">{link}</a></body></html>'.encode())


def test_real_download_mirrors_the_site(server, tmp_path):
    pytest.importorskip("curl_cffi")
    base, script, _ = server
    _docs_site(script)
    out = tmp_path / "mirror"

    result = CliRunner().invoke(
        cli, ["download", f"{base}/docs/", "-o", str(out), "--downloader", "fire-engine", *FAST])

    assert result.exit_code == 0, result.output
    assert "Files downloaded: 2" in result.output
    files = json.loads((out / ".dograpper-manifest.json").read_text())["files"]
    assert sorted(e["url"] for e in files.values()) == [f"{base}/docs/", f"{base}/docs/a.html"]


def test_real_explicit_user_agent_replaces_the_impersonated_one(server):
    # Maintainer decision: an explicit --user-agent is sent (#136 aligns it with Firecrawl).
    base, script, _ = server
    log = []
    script["/p"] = recorded(log, (200, {"Content-Type": "text/html"}, b"<html>hi</html>"))

    res = real_fetcher(user_agent="MyDocsBot/1.0").get(base + "/p", kind="navigate")

    assert res.status == 200
    assert log[0]["User-Agent"] == "MyDocsBot/1.0"


def test_real_download_sends_the_user_agent_given_on_the_command_line(server, tmp_path):
    pytest.importorskip("curl_cffi")
    base, script, _ = server
    _docs_site(script)
    log = []
    script["/docs/a.html"] = recorded(log, script["/docs/a.html"])

    result = CliRunner().invoke(
        cli, ["download", f"{base}/docs/", "-o", str(tmp_path / "m"), "--downloader",
              "fire-engine", "--user-agent", "MyDocsBot/1.0", *FAST])

    assert result.exit_code == 0, result.output
    assert [h["User-Agent"] for h in log] == ["MyDocsBot/1.0"]


def test_real_second_download_revalidates_and_leaves_the_mirror_as_it_was(server, tmp_path):
    """The update mode of the httrack profile (HTTrack -C2), over curl: the validators the
    first run recorded go on the wire, and a 304 keeps each file byte-identical."""
    pytest.importorskip("curl_cffi")
    base, script, _ = server
    _docs_site(script)
    log = []
    for path in ("/docs/", "/docs/a.html"):
        _status, hdrs, body = script[path]
        etag = f'"{path}"'

        def reply(h, etag=etag, hdrs=hdrs, body=body, path=path):
            log.append((path, h.get("If-None-Match"), h.get("If-Modified-Since")))
            if h.get("If-None-Match") == etag:
                return 304, {"ETag": etag}, b""
            return 200, {**hdrs, "ETag": etag, "Last-Modified": LM}, body
        script[path] = reply
    out = tmp_path / "mirror"
    args = ["download", f"{base}/docs/", "-o", str(out), "--downloader", "fire-engine", *FAST]
    first = CliRunner().invoke(cli, args)
    assert first.exit_code == 0, first.output
    manifest = out / ".dograpper-manifest.json"
    before = json.loads(manifest.read_text())["files"]
    assert {(e["status"], e["etag"], e["last_modified"]) for e in before.values()} == {
        (200, '"/docs/"', LM), (200, '"/docs/a.html"', LM)}
    files = {p: open(p, "rb").read() for p in (str(out / e["local_path"]) for e in before.values())}
    log.clear()

    second = CliRunner().invoke(cli, args)

    assert second.exit_code == 0, second.output
    assert sorted(log) == [("/docs/", '"/docs/"', LM), ("/docs/a.html", '"/docs/a.html"', LM)]
    assert "Files downloaded: 0" in second.output and "Files skipped:    2 (cached)" in second.output
    assert "Not modified (304): 2" in second.output
    assert {p: open(p, "rb").read() for p in files} == files
    assert json.loads(manifest.read_text())["files"] == before


def test_real_cache_and_update_flags_act_under_fire_engine(server, tmp_path):
    """fire-engine's updates run on the httrack engine (run_profile, #130), so --cache 1,
    --updatehack and --do-not-recatch act there as under httrack (#132)."""
    pytest.importorskip("curl_cffi")
    base, script, seen = server
    words = " ".join(["documentation"] * 40)
    txt = {"Content-Type": "text/plain", "ETag": '"t"'}
    script["/robots.txt"] = (404, {}, b"")
    script["/docs/"] = (200, {"Content-Type": "text/html"},
                        f'<html><body><p>{words}</p><a href="a.html">a</a>'
                        f'<a href="n.txt">n</a><a href="e.txt">e</a></body></html>'.encode())
    script["/docs/a.html"] = (200, {"Content-Type": "text/html"},
                              f"<html><body><p>{words}</p></body></html>".encode())
    script["/docs/n.txt"] = (200, txt, b"old!")
    script["/docs/e.txt"] = (200, txt, b"erase me")
    out = tmp_path / "mirror"
    args = ["download", f"{base}/docs/", "-o", str(out), "--downloader", "fire-engine",
            "--include-extensions", "html,txt", *FAST]
    first = CliRunner().invoke(cli, args)
    assert first.exit_code == 0, first.output
    host = out / base.split("//")[1]
    seen.clear()

    cached = CliRunner().invoke(cli, [*args, "--cache", "1"])  # HTTrack -C1

    assert cached.exit_code == 0, cached.output
    assert [p for p in seen if p.startswith("/docs/")] == []  # discovery probes aside
    assert "Loaded from cache without a request: 4" in cached.output
    script["/docs/n.txt"] = (200, txt, b"new!")  # same length; validators ignored

    hacked = CliRunner().invoke(cli, [*args, "--updatehack"])  # HTTrack -%s

    assert hacked.exit_code == 0, hacked.output
    assert "Kept on a matching size (--updatehack): 2" in hacked.output
    assert (host / "docs" / "n.txt").read_bytes() == b"old!"
    (host / "docs" / "e.txt").unlink()
    seen.clear()

    kept = CliRunner().invoke(cli, ["-v", *args, "--do-not-recatch"])  # HTTrack -%n

    assert kept.exit_code == 0, kept.output
    assert "/docs/e.txt" not in seen and (host / "docs" / "e.txt").read_bytes() == b""
    assert f"{base}/docs/e.txt: null-size file not recaught" in kept.output

    changed = CliRunner().invoke(cli, [*args, "--changes"])  # HTTrack -%d

    assert changed.exit_code == 0, changed.output
    report = json.loads((out / "hts-changes.json").read_text())
    assert report["first_crawl"] is False and sum(report["counts"].values()) == 4
    assert "Change report: " in changed.output


# -- body bound and timeouts, over the real curl_cffi --------------------------

def bombs():
    """(encoding, body) whose decoded size is 4 MiB of zeros, for each codec installed."""
    data = b"\0" * (4 << 20)
    out = [("gzip", gzip.compress(data, 9))]
    if (br := decoder_module("br")) is not None:
        out.append(("br", br.compress(data, quality=1)))
    if (zstd := decoder_module("zstd")) is not None:
        out.append(("zstd", zstd.compress(data)))
    return out


@pytest.mark.parametrize("encoding,body", bombs(), ids=lambda v: v if isinstance(v, str) else "")
def test_real_decompression_bomb_stops_at_the_cap_and_only_wire_bytes_are_charged(
        server, monkeypatch, encoding, body):
    """curl does not decode: the few KiB on the wire are what its writer receives and the
    bandwidth is charged, and the bounded decoder stops the 4 MiB expansion at the 1 MiB
    cap. (A 1 GiB bomb, measured by hand: ~1 GiB peak RSS before #130, ~100 MiB after.)"""
    base, script, _ = server
    monkeypatch.setattr(httrack_fetcher, "MAX_BODY_BYTES", 1 << 20)
    script["/bomb"] = (200, {"Content-Encoding": encoding}, body)
    fetcher = real_fetcher()
    charged = []
    fetcher._charge_bandwidth = charged.append

    res = fetcher.get(base + "/bomb", kind="navigate")

    assert res.error == "decode failed: ValueError: body too large"
    assert sum(charged) == len(body) < 1 << 20


def test_real_zstd_frame_over_the_window_cap_is_refused(server):
    """curl's own zstd decoder takes windows up to 128 MiB; the bounded decoder keeps the
    8 MiB cap (RFC 9659) on this transport too."""
    zstd = decoder_module("zstd")
    if zstd is None:
        pytest.skip("no zstd decoder installed")
    base, script, _ = server
    data = b"x" * 10_000_000
    if zstd.__name__ == "zstandard":
        body = zstd.ZstdCompressor(compression_params=zstd.ZstdCompressionParameters.from_level(
            3, window_log=27)).compress(data)
    else:
        body = zstd.compress(data, options={zstd.CompressionParameter.window_log: 27})
    script["/wide"] = (200, {"Content-Encoding": "zstd"}, body)

    res = real_fetcher().get(base + "/wide", kind="navigate")

    assert res.status == 200 and res.body == b"" and res.error.startswith("decode failed")


def test_real_raw_body_over_the_cap_aborts_the_transfer(server, monkeypatch):
    base, script, _ = server
    monkeypatch.setattr(fire_fetcher, "MAX_BODY_BYTES", 1 << 20)
    script["/big"] = (200, {}, b"x" * (4 << 20))
    fetcher = real_fetcher()
    charged = []
    fetcher._charge_bandwidth = charged.append

    res = fetcher.get(base + "/big", kind="navigate")

    assert (res.status, res.error) == (None, "body too large")
    assert sum(charged) <= 1 << 20


@pytest.fixture
def trickle():
    """A server that answers 300 bytes in three pieces 0.5 s apart, or never answers."""
    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/hang":
                time.sleep(3)
                return
            self.send_response(200)
            self.send_header("Content-Length", "300")
            self.end_headers()
            for _ in range(3):
                time.sleep(0.5)
                self.wfile.write(b"x" * 100)
                self.wfile.flush()

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    srv.daemon_threads = True
    t = threading.Thread(target=srv.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()
    srv.server_close()
    t.join(5)


def test_real_timeout_is_inactivity_like_the_stdlib_socket_timeout(trickle):
    """--timeout bounds a silence, not the transfer: a 1.5 s body that keeps arriving
    passes a 1 s timeout (the stdlib path's socket timeout), a silent server does not."""
    pytest.importorskip("curl_cffi")
    fetcher = CurlCffiFetcher(build_policy(retries=0, timeout=1))

    slow = fetcher.get(trickle + "/slow", kind="navigate")
    hung = fetcher.get(trickle + "/hang", kind="navigate")

    assert (slow.status, slow.body, slow.error) == (200, b"x" * 300, None)
    assert hung.status is None and "(28)" in hung.error


@pytest.mark.parametrize("proxy", [
    # proxies curl cannot use: it quotes the URL it was given in its error (0.17.0)
    "bogus://user:s3cret@127.0.0.1:1",
    "http://user:s3cret@[bad:1",
    "user:s3cret@[bad:1",  # no scheme
    "bogus://user:s3%40cret@127.0.0.1:1/p@th",  # percent-encoded, an @ in the path
])
def test_real_proxy_credentials_are_never_in_curls_error(server, proxy):
    base, _script, _ = server

    res = real_fetcher(proxy=proxy).get(base + "/x", kind="navigate")

    assert res.status is None and "curl: (" in res.error
    for secret in ("s3cret", "s3%40cret", "s3@cret", "user"):  # the password alone too
        assert secret not in res.error


def test_real_percent_encoded_proxy_password_is_decoded_for_the_proxy(server):
    base, script, _ = server
    log = []
    script["http://docs.example.invalid/page"] = recorded(log, (200, {}, b"via proxy"))
    proxy = base.replace("http://", "us%3Aer:p%40ss@")  # no scheme either

    res = real_fetcher(proxy=proxy).get("http://docs.example.invalid/page", kind="navigate")

    assert (res.status, res.body) == (200, b"via proxy")
    assert log[0]["Proxy-Authorization"] == "Basic " + base64.b64encode(b"us:er:p@ss").decode()


def test_real_proxy_credentials_stay_out_of_the_report(server, tmp_path):
    """A proxy curl cannot use fails every request, and the report lists the errors: the
    password must not be in what the run prints, even with --verbose."""
    pytest.importorskip("curl_cffi")
    base, script, _ = server
    _docs_site(script)
    out = str(tmp_path / "mirror")

    result = CliRunner().invoke(
        cli, ["--verbose", "download", f"{base}/docs/", "-o", out, "--downloader", "fire-engine",
              "--proxy", "bogus://user:s3cret@127.0.0.1:1", "--retries", "0", *FAST])

    assert result.exit_code == 1
    assert "Unsupported proxy scheme for 'bogus://127.0.0.1:1'" in result.output
    assert "s3cret" not in result.output


# -- --updatehack's `stop` (HTTrack -%s) at curl's writer -----------------------

def test_real_stop_aborts_at_the_first_chunk_so_the_body_is_never_read(server):
    """-%s decides at the headers and drops the connection (htsback.c:4283-4357): curl's
    writer asks `stop` at the first chunk, with the status, Content-Type and Content-Length
    curl has read, and aborts the transfer; nothing is stored or charged."""
    base, script, _ = server
    script["/big"] = (200, {"Content-Type": "text/plain"}, b"x" * (4 << 20))
    fetcher = real_fetcher()
    charged, asked = [], []
    fetcher._charge_bandwidth = charged.append

    res = fetcher.get(base + "/big", kind="navigate",
                      stop=lambda status, h: asked.append((status, h)) or True)

    assert res.stopped and (res.status, res.body, res.error) == (200, b"", None)
    assert asked == [(200, {"content-type": "text/plain", "content-length": str(4 << 20)})]
    assert charged == []
    whole = fetcher.get(base + "/big", kind="navigate", stop=lambda status, h: False)
    assert (whole.stopped, whole.body) == (False, b"x" * (4 << 20))


def test_real_stop_is_asked_once_a_transfer_with_no_body_ends(server):
    """No chunk reaches the writer: `stop` is asked with the response's headers then."""
    base, script, _ = server
    script["/empty"] = (200, {"Content-Type": "text/plain"}, b"")
    asked = []

    res = real_fetcher().get(base + "/empty", kind="navigate",
                             stop=lambda status, h: asked.append(h) or True)

    assert res.stopped and asked[0]["content-length"] == "0"
