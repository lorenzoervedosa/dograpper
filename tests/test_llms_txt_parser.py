"""Tests for dograpper.lib.llms_txt_parser."""

from unittest.mock import MagicMock, patch

from dograpper.lib.llms_txt_parser import (
    _parse_llms_txt,
    fetch_llms_txt,
)


def _mock_response(status=200, body=b""):
    resp = MagicMock()
    resp.status = status
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def test_parse_markdown_link_syntax():
    body = "# Docs\n\n- [Intro](https://example.com/a)\n- [Guide](https://example.com/b)\n"
    urls = _parse_llms_txt(body, "https://example.com/")
    assert urls == ["https://example.com/a", "https://example.com/b"]


def test_parse_bare_urls():
    body = "https://example.com/x\nhttps://example.com/y\n"
    urls = _parse_llms_txt(body, "https://example.com/")
    assert "https://example.com/x" in urls
    assert "https://example.com/y" in urls


def test_parse_ignores_comments_and_blank_lines():
    body = "\n# comment\n\n[A](https://example.com/a)\n\n# another\n"
    urls = _parse_llms_txt(body, "https://example.com/")
    assert urls == ["https://example.com/a"]


def test_parse_dedupes_repeated_urls():
    body = "[A](https://x.io/p)\n[B](https://x.io/p)\nhttps://x.io/p\n"
    urls = _parse_llms_txt(body, "https://x.io/")
    assert urls == ["https://x.io/p"]


def test_fetch_llms_txt_success_on_first_candidate():
    body = b"- [Intro](https://site.io/one)\n"
    with patch("dograpper.lib.llms_txt_parser.urlopen", return_value=_mock_response(200, body)) as u:
        urls = fetch_llms_txt("https://site.io/docs")
    assert urls == ["https://site.io/one"]
    called_req = u.call_args[0][0]
    assert called_req.full_url.endswith("/llms.txt")


def test_fetch_llms_txt_falls_back_to_llms_full_txt():
    """First candidate returns empty body; second returns URLs."""
    full_body = b"[A](https://site.io/a)\n"

    call_state = {"n": 0}

    def side_effect(req, timeout=10):
        call_state["n"] += 1
        if call_state["n"] == 1:
            return _mock_response(200, b"")
        return _mock_response(200, full_body)

    with patch("dograpper.lib.llms_txt_parser.urlopen", side_effect=side_effect):
        urls = fetch_llms_txt("https://site.io/docs")
    assert urls == ["https://site.io/a"]
    assert call_state["n"] == 2


def test_fetch_llms_txt_returns_empty_on_404():
    from urllib.error import HTTPError

    def side_effect(req, timeout=10):
        raise HTTPError(req.full_url, 404, "Not Found", {}, None)

    with patch("dograpper.lib.llms_txt_parser.urlopen", side_effect=side_effect):
        urls = fetch_llms_txt("https://no-llms.example.com/")
    assert urls == []


def test_fetch_llms_txt_returns_empty_on_missing_scheme():
    urls = fetch_llms_txt("site.io")
    assert urls == []


def test_fetch_llms_txt_sends_browser_ua():
    from dograpper.lib.wget_mirror import BROWSER_UA

    body = b"[A](https://site.io/a)\n"
    captured = {}

    def side_effect(req, timeout=10):
        captured["ua"] = req.headers.get("User-agent")
        return _mock_response(200, body)

    with patch("dograpper.lib.llms_txt_parser.urlopen", side_effect=side_effect):
        fetch_llms_txt("https://site.io/")

    assert captured["ua"] == BROWSER_UA


def test_fetch_llms_txt_handles_gzip_body():
    import gzip

    body = gzip.compress(b"[A](https://gz.io/a)\n")
    with patch("dograpper.lib.llms_txt_parser.urlopen", return_value=_mock_response(200, body)):
        urls = fetch_llms_txt("https://gz.io/")
    assert urls == ["https://gz.io/a"]


def test_fetch_param_used_when_given():
    calls = []

    def fetch(url):
        calls.append(url)
        return b"https://example.com/a\n" if url.endswith("/llms.txt") else None

    with patch("dograpper.lib.llms_txt_parser.urlopen", side_effect=AssertionError("no urlopen")):
        assert fetch_llms_txt("https://example.com/docs/", fetch=fetch) == ["https://example.com/a"]
    assert calls == ["https://example.com/llms.txt"]


def test_logged_urls_never_carry_raw_control_chars(caplog):
    with caplog.at_level("DEBUG"):
        urls = fetch_llms_txt("https://u:pw@si\x1bcte.io/",  # ESC c: terminal reset
                              fetch=lambda u: b"https://example.com/a\n")
    assert urls == ["https://example.com/a"]
    assert "llms.txt" in caplog.text
    assert "\x1b" not in caplog.text and "pw" not in caplog.text
