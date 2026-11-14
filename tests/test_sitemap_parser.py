"""Tests for dograpper.lib.sitemap_parser."""

import gzip
from unittest.mock import MagicMock, patch

import pytest

from dograpper.lib.sitemap_parser import SITEMAP_NS, fetch_sitemap


XMLNS = 'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'


def _mock_response(status=200, body=b""):
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def _urlset(urls):
    inner = "".join(f"<url><loc>{u}</loc></url>" for u in urls)
    return f'<?xml version="1.0" encoding="UTF-8"?><urlset {XMLNS}>{inner}</urlset>'.encode()


def _sitemapindex(sub_urls):
    inner = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in sub_urls)
    return f'<?xml version="1.0" encoding="UTF-8"?><sitemapindex {XMLNS}>{inner}</sitemapindex>'.encode()


def test_namespace_constant_is_canonical():
    assert SITEMAP_NS == "{http://www.sitemaps.org/schemas/sitemap/0.9}"


def test_fetch_sitemap_plain_urlset():
    body = _urlset(["https://site.io/a", "https://site.io/b"])
    with patch("dograpper.lib.sitemap_parser.urlopen", return_value=_mock_response(200, body)):
        urls = fetch_sitemap("https://site.io/")
    assert urls == ["https://site.io/a", "https://site.io/b"]


def test_fetch_sitemap_gzip_body():
    body = gzip.compress(_urlset(["https://site.io/gz"]))
    with patch("dograpper.lib.sitemap_parser.urlopen", return_value=_mock_response(200, body)):
        urls = fetch_sitemap("https://site.io/")
    assert urls == ["https://site.io/gz"]


def test_fetch_sitemap_sitemapindex_recursion():
    """First call returns an index; nested calls return urlsets."""
    index = _sitemapindex([
        "https://site.io/sub-a.xml",
        "https://site.io/sub-b.xml",
    ])
    sub_a = _urlset(["https://site.io/a1", "https://site.io/a2"])
    sub_b = _urlset(["https://site.io/b1"])

    call_state = {"n": 0}

    def side_effect(req, timeout=15):
        call_state["n"] += 1
        url = req.full_url
        if url.endswith("sitemap.xml"):
            return _mock_response(200, index)
        if url.endswith("sub-a.xml"):
            return _mock_response(200, sub_a)
        if url.endswith("sub-b.xml"):
            return _mock_response(200, sub_b)
        return _mock_response(404, b"")

    with patch("dograpper.lib.sitemap_parser.urlopen", side_effect=side_effect):
        urls = fetch_sitemap("https://site.io/")

    assert urls == ["https://site.io/a1", "https://site.io/a2", "https://site.io/b1"]


def test_fetch_sitemap_cross_host_off_path_rejected():
    """Cross-host sub-sitemap with path OUTSIDE the base prefix is rejected."""
    index = _sitemapindex([
        "https://site.io/docs/sub-same.xml",
        "https://evil.com/other/sub-evil.xml",
    ])
    sub_same = _urlset(["https://site.io/docs/ok"])

    def side_effect(req, timeout=15):
        url = req.full_url
        if url == "https://site.io/sitemap.xml":
            return _mock_response(200, index)
        if url == "https://site.io/docs/sub-same.xml":
            return _mock_response(200, sub_same)
        raise AssertionError(f"should not have fetched {url} (out-of-scope)")

    with patch("dograpper.lib.sitemap_parser.urlopen", side_effect=side_effect):
        urls = fetch_sitemap("https://site.io/docs/")
    assert urls == ["https://site.io/docs/ok"]


def test_fetch_sitemap_cross_host_on_path_accepted():
    """Cross-host sub-sitemap whose path prefix matches the base is accepted.

    Mintlify-class hosting: canonical index on mintlify.wiki, per-project
    sub-sitemaps on www.mintlify.com/<project>/sitemap.xml.
    """
    index = _sitemapindex([
        "https://cdn.host.com/code-yg/oh-my-opencode/sitemap.xml",
    ])
    sub = _urlset([
        "https://mintlify.wiki/code-yg/oh-my-opencode/intro",
        "https://mintlify.wiki/code-yg/oh-my-opencode/advanced",
    ])

    def side_effect(req, timeout=15):
        url = req.full_url
        if url == "https://mintlify.wiki/sitemap.xml":
            return _mock_response(200, index)
        if url == "https://cdn.host.com/code-yg/oh-my-opencode/sitemap.xml":
            return _mock_response(200, sub)
        from urllib.error import HTTPError

        raise HTTPError(url, 404, "Not Found", {}, None)

    with patch("dograpper.lib.sitemap_parser.urlopen", side_effect=side_effect):
        urls = fetch_sitemap("https://mintlify.wiki/code-yg/oh-my-opencode")

    assert urls == [
        "https://mintlify.wiki/code-yg/oh-my-opencode/intro",
        "https://mintlify.wiki/code-yg/oh-my-opencode/advanced",
    ]


def test_fetch_sitemap_empty_urlset_logs_but_returns_empty(caplog):
    body = _urlset([])

    def side_effect(req, timeout=15):
        if req.full_url.endswith("sitemap.xml"):
            return _mock_response(200, body)
        return _mock_response(404, b"")

    import logging
    caplog.set_level(logging.INFO)
    with patch("dograpper.lib.sitemap_parser.urlopen", side_effect=side_effect):
        urls = fetch_sitemap("https://site.io/")
    assert urls == []
    assert any("empty urlset" in record.message for record in caplog.records)


def test_fetch_sitemap_404_falls_through():
    from urllib.error import HTTPError

    def side_effect(req, timeout=15):
        raise HTTPError(req.full_url, 404, "Not Found", {}, None)

    with patch("dograpper.lib.sitemap_parser.urlopen", side_effect=side_effect):
        urls = fetch_sitemap("https://empty.io/")
    assert urls == []


def test_fetch_sitemap_malformed_xml_returns_empty():
    def side_effect(req, timeout=15):
        return _mock_response(200, b"<not-xml><<<")

    with patch("dograpper.lib.sitemap_parser.urlopen", side_effect=side_effect):
        urls = fetch_sitemap("https://bad.io/")
    assert urls == []


def test_fetch_sitemap_dedupes_duplicate_urls():
    body = _urlset(["https://site.io/dup", "https://site.io/dup", "https://site.io/other"])
    with patch("dograpper.lib.sitemap_parser.urlopen", return_value=_mock_response(200, body)):
        urls = fetch_sitemap("https://site.io/")
    assert urls == ["https://site.io/dup", "https://site.io/other"]


def test_fetch_sitemap_sends_browser_ua():
    from dograpper.lib.wget_mirror import BROWSER_UA

    body = _urlset(["https://site.io/a"])
    captured = {}

    def side_effect(req, timeout=15):
        captured["ua"] = req.headers.get("User-agent")
        return _mock_response(200, body)

    with patch("dograpper.lib.sitemap_parser.urlopen", side_effect=side_effect):
        fetch_sitemap("https://site.io/")

    assert captured["ua"] == BROWSER_UA


def test_fetch_sitemap_missing_scheme_returns_empty():
    assert fetch_sitemap("site.io") == []


def test_fetch_param_used_when_given_including_recursion():
    pages = {
        "https://site.io/sitemap.xml": _sitemapindex(["https://site.io/sub.xml"]),
        "https://site.io/sub.xml": _urlset(["https://site.io/a"]),
    }
    calls = []

    def fetch(url):
        calls.append(url)
        return pages.get(url)

    with patch("dograpper.lib.sitemap_parser.urlopen", side_effect=AssertionError("no urlopen")):
        assert fetch_sitemap("https://site.io/", fetch=fetch) == ["https://site.io/a"]
    assert calls == ["https://site.io/sitemap.xml", "https://site.io/sub.xml"]


def test_fetch_param_gzip_body_decompressed():
    body = gzip.compress(_urlset(["https://site.io/a"]))
    assert fetch_sitemap("https://site.io/", fetch=lambda u: body) == ["https://site.io/a"]


def test_robots_sitemap_hint_tried_first():
    calls = []

    def fetch(url):
        calls.append(url)
        return _urlset(["https://site.io/a"]) if url == "https://site.io/hint.xml" else None

    urls = fetch_sitemap("https://site.io/", fetch=fetch, extra_candidates=["https://site.io/hint.xml"])
    assert urls == ["https://site.io/a"] and calls == ["https://site.io/hint.xml"]


def test_extra_candidate_cross_host_rejected():
    calls = []

    def fetch(url):
        calls.append(url)
        return None

    assert fetch_sitemap("https://site.io/", fetch=fetch,
                         extra_candidates=["https://evil.example/s.xml"]) == []
    assert "https://evil.example/s.xml" not in calls
    assert calls[0] == "https://site.io/sitemap.xml"


def test_malformed_extra_candidate_skipped_with_warning(caplog):
    calls = []

    def fetch(url):
        calls.append(url)
        return _urlset(["https://site.io/a"]) if url == "https://site.io/sitemap.xml" else None

    with caplog.at_level("WARNING"):
        urls = fetch_sitemap("https://site.io/", fetch=fetch,
                             extra_candidates=["http://[bad/s.xml"])
    assert urls == ["https://site.io/a"]
    assert calls == ["https://site.io/sitemap.xml"]
    assert any("unusable candidate" in r.getMessage() for r in caplog.records)


def test_malformed_sub_sitemap_loc_skipped():
    pages = {
        "https://site.io/sitemap.xml": _sitemapindex(["http://[bad/s.xml", "https://site.io/s.xml"]),
        "https://site.io/s.xml": _urlset(["https://site.io/a"]),
    }
    assert fetch_sitemap("https://site.io/", fetch=pages.get) == ["https://site.io/a"]


@pytest.mark.parametrize("body", [
    gzip.compress(_urlset(["https://site.io/a"]), mtime=0)[:30],         # EOFError
    b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x00\x03not deflate data at all",  # zlib.error
], ids=["truncated", "not-deflate"])
def test_corrupt_gzip_sitemap_is_skipped(body):
    with patch("dograpper.lib.sitemap_parser.urlopen", return_value=_mock_response(200, body)):
        assert fetch_sitemap("https://site.io/") == []
    assert fetch_sitemap("https://site.io/", fetch=lambda u: body) == []
