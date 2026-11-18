"""fire-engine downloader (ADR-0011): curl_cffi transport, mocked.

The real curl_cffi is an optional native dependency; these tests inject a fake
session so they run without it (and without network).
"""
import sys
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.lib.fire_engine.fetcher import (CurlCffiFetcher, _MISSING,
                                               _default_session_factory)
from dograpper.lib.httrack.policy import build_policy


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


def test_fire_engine_dispatch_forwards_proxy_and_impersonate(tmp_path):
    with patch("dograpper.commands.download.run_fire_engine",
               return_value=(2, 0, [], {})) as stub:
        result = CliRunner().invoke(
            cli, ["download", "http://example.com/", "-o", str(tmp_path / "o"),
                  "--downloader", "fire-engine",
                  "--proxy", "http://p:1", "--impersonate", "chrome124"])
    assert result.exit_code == 0, result.output
    assert stub.call_count == 1
    assert stub.call_args.kwargs["proxy"] == "http://p:1"
    assert stub.call_args.kwargs["impersonate"] == "chrome124"

