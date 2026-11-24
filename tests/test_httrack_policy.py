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
    FetchMeta,
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


@pytest.mark.parametrize("meta,uir,fetch", [
    # htsfetch.c hts_fetch_classify + htslib.c:1240-1297, one row per kind of destination
    (FetchMeta("iframe", "navigate", False), True, [("Sec-Fetch-Mode", "navigate"),
                                                    ("Sec-Fetch-Dest", "iframe")]),
    (FetchMeta("image", "no-cors", False), False, [("Sec-Fetch-Mode", "no-cors"),
                                                   ("Sec-Fetch-Dest", "image")]),
    (FetchMeta("font", "cors", False), False, [("Sec-Fetch-Mode", "cors"),
                                               ("Sec-Fetch-Dest", "font")]),
    (FetchMeta("", "navigate", True), False, []),  # unclassified link: no fetch metadata
])
def test_fetch_metadata_follows_the_link_destination(meta, uir, fetch):
    got = request_headers(build_policy(), "h.test", kind="linked", referer="https://h.test/",
                          scheme="https", meta=meta)
    names = _names(got)
    assert ("Upgrade-Insecure-Requests" in names) is uir
    sec = [(k, v) for k, v in got if k.startswith("Sec-Fetch-") and k != "Sec-Fetch-Site"]
    assert sec == fetch
    assert ("Sec-Fetch-Site" in names) is bool(fetch)


def test_fetch_metadata_can_fix_sec_fetch_site():
    # a redirect chain carries the site hts_fetch_through computed, whatever the Referer
    got = dict(request_headers(build_policy(), "h.test", kind="linked",
                               referer="https://h.test/latest/", scheme="https",
                               meta=FetchMeta(site="none")))
    assert got["Sec-Fetch-Site"] == "none" and got["Referer"] == "https://h.test/latest/"


@pytest.mark.parametrize("page,url,want", [
    ("https://h.test/a", "https://h.test/b", "same-origin"),
    ("https://h.test/a", "https://h.test:8443/b", "same-site"),
    ("https://h.test/a", "http://h.test/b", "cross-site"),
    (None, "https://h.test/b", "none"),
])
def test_site_of_compares_a_page_and_a_url(page, url, want):
    assert policy.site_of(page, url) == want


@pytest.mark.parametrize("page,want", [
    ("https://u:pw@h.test/a b?q=é#frag", "https://h.test/a%20b?q=%c3%a9"),
    ("https://user@h.test:8443", "https://h.test:8443/"),
    ("https://h.test/%41#", "https://h.test/%41"),
])
def test_referer_is_sent_without_userinfo_or_fragment_and_escaped(page, want):
    # htslib.c:1136-1163: scheme + escaped host past the userinfo + escaped path and query
    got = dict(request_headers(build_policy(), "h.test", kind="linked", referer=page,
                               scheme="https"))
    assert got["Referer"] == want


@pytest.mark.parametrize("page,site", [
    ("https://h.test:99999/", "same-origin"),
    ("https://h.test:x/", "same-origin"),
    ("https://h.test:0/", "same-origin"),
    ("https://docs.h.test:99999/", "same-site"),
])
def test_referer_with_unusable_port_keeps_the_scheme_default(page, site):
    # htsfetch.c origin_of: "a port out of range keeps the scheme default"; never a ValueError
    assert policy._fetch_site(page, "https", "h.test") == site
    got = dict(request_headers(build_policy(), "h.test", kind="linked", referer=page,
                               scheme="https"))
    assert got["Sec-Fetch-Site"] == site and got["Referer"] == page


@pytest.mark.parametrize("page", ["https://[bad/a", "https://h.test/\ud800"])
def test_unusable_referer_is_dropped_not_raised(page):
    got = dict(request_headers(build_policy(), "h.test", kind="linked", referer=page,
                               scheme="https"))
    assert "Referer" not in got and got["Sec-Fetch-Site"] == "none"


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


# -- update mode: validators (htslib.c:1632-1653) and conditional headers (htsback.c:2575-2601) --

LONG = "x" * 64  # HTTrack keeps a value only under 64 characters


@pytest.mark.parametrize("headers,want", [
    ({"etag": '"v1"', "last-modified": "Mon, 01 Jan 2024 00:00:00 GMT"},
     ('"v1"', "Mon, 01 Jan 2024 00:00:00 GMT")),
    ({"etag": 'W/"v1"', "date": "Tue, 02 Jan 2024 00:00:00 GMT"},
     ('W/"v1"', "Tue, 02 Jan 2024 00:00:00 GMT")),  # Date stands for Last-Modified
    ({"last-modified": LONG, "date": "Tue, 02 Jan 2024 00:00:00 GMT"},
     (None, "Tue, 02 Jan 2024 00:00:00 GMT")),
    ({"etag": LONG, "last-modified": "Mon, 01 Jan 2024 00:00:00 GMT",
      "date": "Tue, 02 Jan 2024 00:00:00 GMT"}, (None, "Mon, 01 Jan 2024 00:00:00 GMT")),
    ({"etag": "", "date": LONG}, (None, None)),
    ({}, (None, None)),
])
def test_response_validators_are_recorded_as_httrack_records_them(headers, want):
    assert policy.response_validators(headers) == want


@pytest.mark.parametrize("etag,lm,want", [
    ('"v1"', "Mon", [("If-None-Match", '"v1"'), ("If-Modified-Since", "Mon")]),
    ('"v1"', None, [("If-None-Match", '"v1"')]),
    (None, "Mon", [("If-Modified-Since", "Mon")]),
    (None, None, []),
    ('"a"\r\nX-Injected: 1', LONG, []),  # an edited manifest never reaches the wire
    (7, "café", []),
])
def test_conditional_headers_follow_htsback_c(etag, lm, want):
    assert list(policy.conditional_headers(etag, lm)) == want


def test_conditional_headers_go_first_and_leave_the_rest_identical():
    """htslib.c:1113-1115: the conditional lines (xsend) follow the request line, before
    the Referer; Accept-Encoding is unchanged, the identity of htsback.c:2606 being wiped by
    hts_init_htsblk (htsback.c:2723, 2754)."""
    p = build_policy()
    v = policy.conditional_headers('"v1"', "Mon, 01 Jan 2024 00:00:00 GMT")
    plain = request_headers(p, "localhost:8443", kind="linked", referer="https://localhost:8443/",
                            scheme="https")
    got = request_headers(p, "localhost:8443", kind="linked", referer="https://localhost:8443/",
                          scheme="https", validators=v)
    assert got == [*v, *plain]


def test_cache_mode_defaults_as_in_httrack():
    """-C: None is HTTrack's default, 2 over a finished mirror, else 1
    (htscoremain.c:1263-1285); a mode HTTrack has not is refused."""
    assert build_policy().cache is None and build_policy(cache=0).cache == 0
    with pytest.raises(ValueError, match="cache"):
        build_policy(cache=3)


def test_update_hacks_are_off_by_default_as_in_httrack():
    """-%s, -%n and -%d (opt->sizehack, norecatch, changes = HTS_FALSE, htslib.c:5427,
    5429, 5441)."""
    p = build_policy()
    assert (p.updatehack, p.do_not_recatch, p.changes) == (False, False, False)


# -- --browser-headers (#170, HTTrack -%Q): the headers of the browser --user-agent names.
# Expected values: HTTrack's own test vectors at the pinned commit (tests/597, 602, 603).

CHROME = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "Chrome/141.0.0.0 Safari/537.36")
EDGE = CHROME + " Edg/141.0.0.0"
FIREFOX = "Mozilla/5.0 (X11; Linux x86_64; rv:158.0) Gecko/20100101 Firefox/158.0"
C_NAV = ("text/html,application/xhtml+xml,application/xml;q=0.9,image/jxl,image/avif,"
         "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7")
C_IMG = "image/jxl,image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8"
F_NAV = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
F_IMG = "image/avif,image/jxl,image/webp,image/png,image/svg+xml,image/*;q=0.8,*/*;q=0.5"
CSS = "text/css,*/*;q=0.1"


@pytest.mark.parametrize("ua,want", [
    (CHROME.replace("141.0.0.0", "108.0.0.0"),
     ('"Not?A_Brand";v="8", "Chromium";v="108", "Google Chrome";v="108"', False, '"Windows"')),
    (CHROME.replace("141.0.0.0", "138.0.0.0"),
     ('"Not)A;Brand";v="8", "Chromium";v="138", "Google Chrome";v="138"', False, '"Windows"')),
    ("Mozilla/5.0 (Linux; Android 10; K) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/140.0.0.0 Mobile Safari/537.36",
     ('"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"', True, '"Android"')),
    (CHROME, ('"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"', False,
              '"Windows"')),
    (EDGE, ('"Microsoft Edge";v="141", "Not?A_Brand";v="8", "Chromium";v="141"', False,
            '"Windows"')),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/139.0.0.0 Safari/537.36",
     ('"Not;A=Brand";v="99", "Google Chrome";v="139", "Chromium";v="139"', False, '"macOS"')),
    ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/142.0.0.0 Safari/537.36",
     ('"Chromium";v="142", "Google Chrome";v="142", "Not_A Brand";v="99"', False, '"Linux"')),
    ("Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) "
     "Chrome/143.0.0.0 Safari/537.36",
     ('"Google Chrome";v="143", "Chromium";v="143", "Not A(Brand";v="24"', False,
      '"Chrome OS"')),
    (CHROME.replace("Windows NT 10.0; Win64; x64", "Windows"),
     ('"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"', False, '"Windows"')),
])
def test_client_hints_are_chromiums_for_the_user_agent(ua, want):
    """htslib.c:728-811 hts_client_hints_of: Chromium's GREASE brand, seeded by the major."""
    assert policy.client_hints(ua) == want


@pytest.mark.parametrize("ua", [
    FIREFOX,
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/18.0 Safari/605.1.15",
    "Mozilla/5.0 (compatible; HTTrack/3.x; +https://www.httrack.com/)",
    CHROME + " OPR/125.0.0.0", CHROME.replace("Chrome", "HeadlessChrome"),
    CHROME.replace("141.0.0.0", "107.0.0.0"), CHROME.replace("141.0.0.0", "50.0.0.0"),
    CHROME.replace("141.0.0.0", ""), CHROME.replace("141.0.0.0", "141abc"),
    CHROME.replace("141.0.0.0", "0141.0.0.0"), CHROME + " Edg/", CHROME + " Edg/140.0.0.0",
    CHROME.replace("141.0.0.0", "1410000000"),
    CHROME.replace("Windows NT 10.0; Win64; x64", "Plan9"),
    CHROME[len("Mozilla/5.0 "):],
    CHROME.replace("Windows NT 10.0; Win64; x64", "X11; FreeBSD amd64"),
    CHROME[:CHROME.rindex(")")], "", "Mozilla/5.0 (X11)\tChrome/141.0.0.0",
])
def test_no_client_hints_for_any_other_user_agent(ua):
    assert policy.client_hints(ua) is None


@pytest.mark.parametrize("ua,family", [
    (CHROME, "chrome"), (EDGE, "chrome"), (FIREFOX, "firefox"),
    ("Mozilla/5.0 (Android 14; Mobile; rv:131.0) Gecko/131.0 Firefox/131.0", "firefox"),
    (FIREFOX.replace("158.0", "89.0"), None), (FIREFOX.replace("158.0", "90.0"), "firefox"),
    (FIREFOX[len("Mozilla/5.0 "):], None), (FIREFOX.replace(" Gecko/20100101", ""), None),
    ("Mozilla/5.0 Gecko/20100101 Firefox/158.0 (X11", None),
    (FIREFOX + " SeaMonkey/2.53.20", None),
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 "
     "(KHTML, like Gecko) FxiOS/131.0 Mobile/15E148 Safari/605.1.15", None),
    (CHROME + " OPR/125.0.0.0", None),
    ("Mozilla/5.0 (compatible; HTTrack/3.x; +https://www.httrack.com/)", None),
])
def test_browser_family_is_httracks(ua, family):
    """htslib.c:820-866 hts_browser_family_of (tests/602)."""
    assert policy.browser_family(ua) == family


PAGE = FetchMeta("document", "navigate", True)
STYLE, SCRIPT, IMAGE = (FetchMeta(d, "no-cors", False) for d in ("style", "script", "image"))
HINTS = [("sec-ch-ua", '"Google Chrome";v="141", "Not?A_Brand";v="8", "Chromium";v="141"'),
         ("sec-ch-ua-mobile", "?0"), ("sec-ch-ua-platform", '"Windows"')]


def _sent(ua, meta, **kw):
    return request_headers(build_policy(user_agent=ua, **kw), "h.test", kind="linked",
                           referer="https://h.test/", scheme="https", meta=meta)


def _browser(ua, accept, *, user=False, hints=(), uir=False, dest):
    """The header values a browser sends for a same-origin https link from /."""
    h = dict(hints)
    h.update({"Host": "h.test", "Connection": "keep-alive", "User-Agent": ua, "Accept": accept,
              "Accept-Language": "en-US,en;q=0.9", "Sec-Fetch-Site": "same-origin",
              "Sec-Fetch-Mode": "navigate" if uir else "no-cors", "Sec-Fetch-Dest": dest,
              "Referer": "https://h.test/", "Accept-Encoding": policy.accept_encoding()})
    if uir:
        h["Upgrade-Insecure-Requests"] = "1"
    if user:
        h["Sec-Fetch-User"] = "?1"
    return h


# tests/602 order_c_nav, order_c_sub and order_f, without the headers no request here sends
C_NAV_ORDER = ["Host", "Connection", "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
               "Accept-Language", "Upgrade-Insecure-Requests", "User-Agent", "Accept",
               "Sec-Fetch-Site", "Sec-Fetch-Mode", "Sec-Fetch-User", "Sec-Fetch-Dest", "Referer",
               "Accept-Encoding"]
C_SUB_ORDER = ["Host", "Connection", "sec-ch-ua-platform", "Accept-Language", "sec-ch-ua",
               "User-Agent", "sec-ch-ua-mobile", "Accept", "Sec-Fetch-Site", "Sec-Fetch-Mode",
               "Sec-Fetch-Dest", "Referer", "Accept-Encoding"]
F_PAGE_ORDER = ["Host", "User-Agent", "Accept", "Accept-Language", "Accept-Encoding",
                "Connection", "Referer", "Upgrade-Insecure-Requests", "Sec-Fetch-Dest",
                "Sec-Fetch-Mode", "Sec-Fetch-Site", "Sec-Fetch-User"]
F_SUB_ORDER = [n for n in F_PAGE_ORDER if n not in ("Upgrade-Insecure-Requests",
                                                    "Sec-Fetch-User")]
EDGE_HINTS = [("sec-ch-ua", '"Microsoft Edge";v="141", "Not?A_Brand";v="8", "Chromium";v="141"'),
              *HINTS[1:]]


@pytest.mark.parametrize("ua,meta,order,want", [
    (CHROME, PAGE, C_NAV_ORDER,
     _browser(CHROME, C_NAV, user=True, hints=HINTS, uir=True, dest="document")),
    (CHROME, STYLE, C_SUB_ORDER, _browser(CHROME, CSS, hints=HINTS, dest="style")),
    (CHROME, SCRIPT, C_SUB_ORDER, _browser(CHROME, "*/*", hints=HINTS, dest="script")),
    (CHROME, IMAGE, C_SUB_ORDER, _browser(CHROME, C_IMG, hints=HINTS, dest="image")),
    (EDGE, PAGE, C_NAV_ORDER,
     _browser(EDGE, C_NAV, user=True, hints=EDGE_HINTS, uir=True, dest="document")),
    (EDGE, STYLE, C_SUB_ORDER, _browser(EDGE, CSS, hints=EDGE_HINTS, dest="style")),
    (EDGE, SCRIPT, C_SUB_ORDER, _browser(EDGE, "*/*", hints=EDGE_HINTS, dest="script")),
    (EDGE, IMAGE, C_SUB_ORDER, _browser(EDGE, C_IMG, hints=EDGE_HINTS, dest="image")),
    (FIREFOX, PAGE, F_PAGE_ORDER,
     _browser(FIREFOX, F_NAV, user=True, uir=True, dest="document")),
    (FIREFOX, STYLE, F_SUB_ORDER, _browser(FIREFOX, CSS, dest="style")),
    (FIREFOX, SCRIPT, F_SUB_ORDER, _browser(FIREFOX, "*/*", dest="script")),
    (FIREFOX, IMAGE, F_SUB_ORDER, _browser(FIREFOX, F_IMG, dest="image")),
])
def test_a_browser_user_agent_sends_that_browsers_headers(ua, meta, order, want):
    """#170: the browser tables of HTTrack -%Q (htsfetch.c:549-578 Accept, htsfetch.h:135
    Accept-Language, htslib.c:913-946 order) for a page, a stylesheet, a script, an image."""
    got = _sent(ua, meta)
    assert [name for name, _ in got] == order
    assert dict(got) == want


def test_a_browser_table_never_reaches_plain_http_hints_nor_an_unclassified_link():
    """Client hints over https only (htslib.c:1213-1216); a link with no fetch metadata
    gets no browser table: HTTrack's own Accept and order (tests/603, -%Q0 row)."""
    got = request_headers(build_policy(user_agent=CHROME), "127.0.0.1:8080", kind="linked",
                          referer="http://127.0.0.1:8080/", scheme="http", meta=IMAGE)
    assert [n for n, _ in got if n.startswith("sec-ch-ua")] == []
    assert [n for n, _ in got][:2] == ["Host", "Connection"]  # loopback: still Chrome's order
    got = _sent(CHROME, FetchMeta("", "no-cors", False))
    assert [n for n, _ in got] == ["Referer", "Connection", "Host", *[n for n, _ in HINTS],
                                   "User-Agent", "Accept", "Accept-Language", "Accept-Encoding"]
    assert dict(got)["Accept"] == policy.ACCEPT and dict(got)["Accept-Language"] == "en, *"


@pytest.mark.parametrize("ua", [CHROME, FIREFOX, None])
def test_no_browser_headers_sends_httracks_own_set(ua):
    """--no-browser-headers (HTTrack -%Q0): no Sec-Fetch-*, no Upgrade-Insecure-Requests,
    no client hints, and HTTrack's own Accept, Accept-Language and order (tests/603)."""
    got = _sent(ua, PAGE, browser_headers=False)
    assert [n for n, _ in got] == ["Referer", "Connection", "Host", "User-Agent", "Accept",
                                   "Accept-Language", "Accept-Encoding"]
    assert dict(got)["Accept"] == policy.ACCEPT and dict(got)["Accept-Language"] == "en, *"


def test_a_header_line_still_takes_the_place_of_a_browser_tables_own():
    got = _sent(CHROME, PAGE, headers=(("Accept-Language", "pt-BR"), ("sec-ch-ua", '"T";v="1"')))
    assert dict(got)["Accept-Language"] == "pt-BR" and dict(got)["sec-ch-ua"] == '"T";v="1"'
    assert [n for n, _ in got] == C_NAV_ORDER
