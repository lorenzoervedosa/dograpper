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
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.lib.fire_engine.fetcher import (CurlCffiFetcher, _MISSING,
                                               _default_session_factory)
from dograpper.lib.httrack.policy import build_policy


LM = "Mon, 01 Jan 2024 00:00:00 GMT"


class FakeResp:
    def __init__(self, status=200, headers=None, content=b"<html>ok</html>", chunks=None):
        self.status_code = status
        self.headers = headers or {}
        self._chunks = chunks if chunks is not None else [content]
        self.closed = False

    def iter_content(self, chunk_size=65536):
        yield from self._chunks

    def close(self):
        self.closed = True


class FakeSession:
    def __init__(self, resp):
        self.resp = resp
        self.calls = []

    def request(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.resp


def make_fetcher(resp, *, proxy=None, impersonate="chrome124"):
    session = FakeSession(resp)
    captured = {}

    def factory(imp):
        captured["impersonate"] = imp
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


def test_proxy_is_forwarded_to_the_session():
    fetcher, session, _ = make_fetcher(FakeResp(), proxy="http://user:pw@proxy:8080")

    fetcher.get("https://example.com/", kind="navigate")

    _m, _u, kw = session.calls[0]
    assert kw["proxies"] == {"http": "http://user:pw@proxy:8080",
                             "https": "http://user:pw@proxy:8080"}


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


def test_content_encoding_header_is_dropped_so_body_is_not_double_decoded():
    # curl_cffi already decompresses; a lingering content-encoding must not make
    # the inherited get() try to decode plain bytes again.
    resp = FakeResp(headers={"content-encoding": "gzip"}, content=b"plain text")
    fetcher, _session, _ = make_fetcher(resp)

    res = fetcher.get("https://example.com/", kind="navigate")

    assert res.body == b"plain text"


def test_body_over_the_cap_is_rejected_mid_stream(monkeypatch):
    # curl decompresses on the fly; a bomb must be stopped while streaming, not
    # after the whole thing is in memory.
    monkeypatch.setattr("dograpper.lib.fire_engine.fetcher.MAX_BODY_BYTES", 10)
    resp = FakeResp(chunks=[b"x" * 8, b"y" * 8])  # 16 bytes > cap of 10
    fetcher, _session, _ = make_fetcher(resp)

    res = fetcher.get("https://example.com/", kind="navigate")

    assert res.status is None
    assert res.error == "body too large"
    assert resp.closed is True


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
        _default_session_factory("chrome124")
    assert "fire-engine" in str(exc.value)
    assert str(exc.value) == _MISSING


def test_missing_curl_cffi_surfaces_before_any_request():
    """The first GET (robots.txt, in run_fire_engine) must raise the friendly error,
    not have it wrapped as a transport OSError that the run retries and reports."""
    def factory(_imp):
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
        cli, ["download", f"{base}/docs/", "-o", str(out), "--downloader", "fire-engine"])

    assert result.exit_code == 0, result.output
    assert "Files downloaded: 2" in result.output
    files = json.loads((out / ".dograpper-manifest.json").read_text())["files"]
    assert sorted(e["url"] for e in files.values()) == [f"{base}/docs/", f"{base}/docs/a.html"]


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
    args = ["download", f"{base}/docs/", "-o", str(out), "--downloader", "fire-engine"]
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
