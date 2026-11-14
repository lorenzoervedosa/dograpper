import sys
import types
import importlib.util
import json
import logging
import shutil
import socket
import ssl
import subprocess
import threading
from pathlib import Path

import pytest

from dograpper.lib.httrack import policy
from dograpper.lib.httrack.policy import (
    build_policy,
    make_ssl_context,
    request_headers,
    warn_if_old_openssl,
)

FIXDIR = Path(__file__).parent / "fixtures" / "httrack_wire"
FIXTURE = json.loads((FIXDIR / "httrack_3.51_requests.json").read_text())


@pytest.fixture(autouse=True)
def _fresh_decoder_cache():
    """Decoder resolution is cached per process; tests fake module availability."""
    policy._decoder_modname.cache_clear()
    yield
    policy._decoder_modname.cache_clear()


def test_clamps_apply_and_warn(caplog):
    with caplog.at_level(logging.WARNING, logger=policy.logger.name):
        p = build_policy(connections=20, max_conn_rate=50, max_bandwidth=10**9)
    assert (p.connections, p.max_conn_rate, p.max_bandwidth) == (8, 5.0, 10_000_000)
    assert len([r for r in caplog.records if r.levelno == logging.WARNING]) == 3


def test_disable_security_limits_lifts_clamps_not_retry_after_cap():
    p = build_policy(connections=20, max_conn_rate=50, max_bandwidth=10**9,
                     max_retry_after=99999, disable_security_limits=True)
    assert (p.connections, p.max_conn_rate, p.max_bandwidth) == (20, 50, 10**9)
    assert p.max_retry_after == 3600


def test_retry_after_cap_warns(caplog):
    with caplog.at_level(logging.WARNING, logger=policy.logger.name):
        assert build_policy(max_retry_after=3600).max_retry_after == 3600
    assert caplog.records == []
    with caplog.at_level(logging.WARNING, logger=policy.logger.name):
        p = build_policy(max_retry_after=99999, disable_security_limits=True)
    assert p.max_retry_after == 3600
    assert "max_retry_after=99999" in caplog.text and "3600" in caplog.text


@pytest.mark.parametrize("kw", [
    {"connections": 0}, {"connections": -1}, {"max_conn_rate": 0}, {"max_bandwidth": 0},
    {"timeout": 0}, {"timeout": float("nan")}, {"max_links": 0}, {"retries": -1},
    {"max_retry_after": -1}, {"delay_ms": -1},
])
def test_out_of_range_values_fail_at_build_time(kw):
    with pytest.raises(ValueError, match=next(iter(kw))):
        build_policy(**kw)


def test_zero_retries_retry_after_and_delay_are_valid():
    p = build_policy(retries=0, max_retry_after=0, delay_ms=0)
    assert (p.retries, p.max_retry_after, p.delay_ms) == (0, 0, 0)


def test_default_user_agent_has_version_and_no_url():
    ua = build_policy().user_agent
    assert ua.startswith("Mozilla/5.0 (compatible; dograpper/") and "http" not in ua
    assert build_policy(user_agent="X/1").user_agent == "X/1"


@pytest.mark.parametrize("fix_key,kind,referer", [
    ("robots", "robots", None),
    ("start", "navigate", None),
    ("linked", "linked", "https://localhost:8443/"),
])
def test_headers_match_httrack_fixture(fix_key, kind, referer):
    p = build_policy()
    expected = []
    for line in FIXTURE[fix_key]["headers"]:
        if line.startswith("User-Agent: "):
            line = "User-Agent: " + p.user_agent
        elif line.startswith("Accept-Encoding: "):
            line = "Accept-Encoding: " + policy.accept_encoding()
        expected.append(line)
    got = request_headers(p, "localhost:8443", kind=kind, referer=referer, scheme="https")
    assert [f"{k}: {v}" for k, v in got] == expected


def test_decoder_resolution_is_probed_once(monkeypatch):
    probes = []
    monkeypatch.setattr(policy, "_importable", lambda name: probes.append(name) or False)
    for _ in range(3):
        policy.accept_encoding()
        policy.decoder_module("br")
    assert sorted(probes) == ["brotli", "compression.zstd", "zstandard"]


def _names(headers):
    return [k for k, _ in headers]


SEC_FETCH = ["Sec-Fetch-Site", "Sec-Fetch-Mode", "Sec-Fetch-User", "Sec-Fetch-Dest"]


def test_plain_http_sends_no_fetch_metadata_nor_br_zstd(monkeypatch):
    monkeypatch.setattr(policy, "_importable", lambda name: True)
    got = request_headers(build_policy(), "example.com", kind="linked",
                          referer="http://example.com/", scheme="http")
    assert _names(got) == ["Referer", "Connection", "Host", "User-Agent", "Accept",
                           "Accept-Language", "Accept-Encoding"]
    assert dict(got)["Accept-Encoding"] == "gzip, deflate, identity;q=0.9"
    assert "br" in policy.accept_encoding()  # the TLS variant still advertises them


@pytest.mark.parametrize("host", ["127.0.0.1:8080", "127.5.6.7", "localhost:8080",
                                  "a.localhost", "[::1]:8080"])
def test_plain_http_to_trustworthy_origin_sends_fetch_metadata_without_uir(host):
    got = request_headers(build_policy(), host, kind="navigate", referer=None, scheme="http")
    assert _names(got) == ["Connection", "Host", "User-Agent", "Accept", *SEC_FETCH,
                           "Accept-Language", "Accept-Encoding"]
    assert dict(got)["Sec-Fetch-Site"] == "none"
    assert dict(got)["Accept-Encoding"] == "gzip, deflate, identity;q=0.9"


@pytest.mark.parametrize("ua", ["X/1", "Mozilla/5.0", "mozilla/5.0 (x)", "Mozilla/4.0 (x)"])
def test_non_browser_user_agent_sends_no_fetch_metadata(ua):
    got = request_headers(build_policy(user_agent=ua), "example.com", kind="navigate",
                          referer=None, scheme="https")
    assert _names(got) == ["Connection", "Host", "User-Agent", "Accept",
                           "Accept-Language", "Accept-Encoding"]


def test_linked_without_referer_is_not_same_origin():
    got = dict(request_headers(build_policy(), "example.com", kind="linked", referer=None, scheme="https"))
    assert got["Sec-Fetch-Site"] == "none" and "Referer" not in got


@pytest.mark.parametrize("referer,scheme,host,site", [
    ("https://example.com/a", "https", "example.com", "same-origin"),
    ("https://example.com:443/a", "https", "example.com", "same-origin"),
    ("https://example.com:8443/a", "https", "example.com", "same-site"),
    ("https://docs.example.com/a", "https", "example.com", "same-site"),
    ("https://example.org/a", "https", "example.com", "cross-site"),
    ("http://example.com/a", "https", "example.com", "cross-site"),
    ("https://example.com/a", "http", "localhost", "cross-site"),
    ("http://127.0.0.1:1/a", "http", "127.0.0.2:1", "cross-site"),  # IP literals key on themselves
])
def test_sec_fetch_site_follows_the_referer(referer, scheme, host, site):
    got = dict(request_headers(build_policy(), host, kind="linked", referer=referer,
                               scheme=scheme))
    assert got["Sec-Fetch-Site"] == site


def test_https_referer_never_sent_to_http():
    got = dict(request_headers(build_policy(), "localhost", kind="linked",
                               referer="https://localhost/a", scheme="http"))
    assert "Referer" not in got and got["Sec-Fetch-Site"] == "cross-site"
    got = dict(request_headers(build_policy(), "localhost", kind="linked",
                               referer="http://localhost/a", scheme="https"))
    assert got["Referer"] == "http://localhost/a"


@pytest.mark.parametrize("br,zstd,want", [
    (False, False, "gzip, deflate, identity;q=0.9"),
    (True, False, "gzip, deflate, br, identity;q=0.9"),
    (False, True, "gzip, deflate, zstd, identity;q=0.9"),
    (True, True, "gzip, deflate, br, zstd, identity;q=0.9"),
])
def test_accept_encoding_variants(monkeypatch, br, zstd, want):
    avail = {"brotli": br, "zstandard": zstd, "compression.zstd": False}
    monkeypatch.setattr(policy, "_importable", lambda name: avail[name])
    assert policy.accept_encoding() == want


def test_ssl_context_config():
    ctx = make_ssl_context()
    assert ctx.minimum_version == ssl.TLSVersion.TLSv1_2
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.options & ssl.OP_ALL == ssl.OP_ALL


def test_warn_if_old_openssl(monkeypatch, caplog):
    monkeypatch.setattr(ssl, "OPENSSL_VERSION_INFO", (3, 0, 13, 0, 0))
    with caplog.at_level(logging.WARNING, logger=policy.logger.name):
        assert warn_if_old_openssl() is True
    assert "Downloader profiles" in caplog.text
    monkeypatch.setattr(ssl, "OPENSSL_VERSION_INFO", (3, 5, 3, 0, 0))
    assert warn_if_old_openssl() is False


def _load_capture():
    spec = importlib.util.spec_from_file_location("httrack_capture", FIXDIR / "capture.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _normalize(hello):
    # Spec 5.1: ec_point_formats contents and the SNI length legitimately differ.
    hello = json.loads(json.dumps(hello))
    for ext in hello["extensions"]:
        if ext["name"] == "ec_point_formats":
            ext.clear()
            ext["name"] = "ec_point_formats"
        elif ext["name"] == "server_name":
            ext.pop("len", None)
    return hello


@pytest.mark.skipif(ssl.OPENSSL_VERSION_INFO < (3, 5), reason="needs OpenSSL >= 3.5")
@pytest.mark.skipif(shutil.which("openssl") is None, reason="openssl CLI absent")
def test_client_hello_matches_httrack_fixture(tmp_path):
    cert, key, out = tmp_path / "cert.pem", tmp_path / "key.pem", tmp_path / "out.jsonl"
    subprocess.run(
        ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key),
         "-out", str(cert), "-days", "2", "-subj", "/CN=localhost",
         "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"],
        check=True, capture_output=True)
    cap = _load_capture()
    srv = cap.Server(("127.0.0.1", 0), cap.Handler)
    srv.ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    srv.ctx.load_cert_chain(str(cert), str(key))
    srv.out = str(out)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        ctx = make_ssl_context()
        ctx.load_verify_locations(str(cert))
        with socket.create_connection(("127.0.0.1", srv.server_address[1]), timeout=10) as s:
            with ctx.wrap_socket(s, server_hostname="localhost") as tls:
                tls.sendall(b"GET / HTTP/1.1\r\nHost: localhost\r\n\r\n")
                tls.recv(65536)
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)
    rec = json.loads(out.read_text().splitlines()[0])
    assert "client_hello_error" not in rec and "tls_error" not in rec
    assert _normalize(rec["client_hello"]) == _normalize(FIXTURE["start"]["client_hello"])


def _fake(monkeypatch, name, **attrs):
    mod = types.ModuleType(name)
    for k, v in attrs.items():
        setattr(mod, k, v)
    monkeypatch.setitem(sys.modules, name, mod)


class _OldBrotli:
    def process(self, data):
        return b""


class _NewBrotli:
    def process(self, data, output_buffer_limit=None):
        return b""


def test_brotli_without_bounded_api_is_refused(monkeypatch):
    _fake(monkeypatch, "brotli", Decompressor=_OldBrotli)
    assert "br" not in policy.accept_encoding()
    assert policy.decoder_module("br") is None
    _fake(monkeypatch, "brotli", Decompressor=_NewBrotli)
    policy._decoder_modname.cache_clear()
    assert "br" in policy.accept_encoding()
    assert policy.decoder_module("br") is not None


class _NoWindowZstd:
    def __init__(self):
        pass


class _WindowZstd:
    def __init__(self, max_window_size=0):
        pass

    def decompressobj(self):
        return types.SimpleNamespace(eof=False, unused_data=b"")


def test_zstandard_without_window_cap_is_refused(monkeypatch):
    monkeypatch.setitem(sys.modules, "compression.zstd", None)  # force ImportError
    _fake(monkeypatch, "zstandard", ZstdDecompressor=_NoWindowZstd)
    assert "zstd" not in policy.accept_encoding()
    assert policy.decoder_module("zstd") is None
    _fake(monkeypatch, "zstandard", ZstdDecompressor=_WindowZstd)
    policy._decoder_modname.cache_clear()
    assert "zstd" in policy.accept_encoding()


@pytest.mark.parametrize("missing", ["eof", "unused_data"])
def test_zstandard_without_frame_end_api_is_refused(monkeypatch, missing):
    attrs = {"eof": False, "unused_data": b""}
    del attrs[missing]

    class Old(_WindowZstd):
        def decompressobj(self):
            return types.SimpleNamespace(**attrs)

    monkeypatch.setitem(sys.modules, "compression.zstd", None)  # force ImportError
    _fake(monkeypatch, "zstandard", ZstdDecompressor=Old)
    assert "zstd" not in policy.accept_encoding()
    assert policy.decoder_module("zstd") is None
