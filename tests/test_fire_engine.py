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
    def __init__(self, status=200, headers=None, content=b"<html>ok</html>"):
        self.status_code = status
        self.headers = headers or {}
        self.content = content


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


def test_default_factory_without_curl_cffi_raises_friendly_error(monkeypatch):
    monkeypatch.setitem(sys.modules, "curl_cffi", None)  # forces ImportError
    with pytest.raises(RuntimeError) as exc:
        _default_session_factory("chrome124")
    assert "fire-engine" in str(exc.value)
    assert str(exc.value) == _MISSING


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
