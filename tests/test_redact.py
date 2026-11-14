import pytest

from dograpper.utils.redact import redact_url


@pytest.mark.parametrize("url,want", [
    ("https://u:p@example.com:8080/a?b=1#c", "https://example.com:8080/a?b=1#c"),
    ("http://user@example.com/", "http://example.com/"),
    ("http://example.com/a@b", "http://example.com/a@b"),
    ("https://example.com/x?", "https://example.com/x?"),
    ("http://u:p@[::1]:80/", "http://[::1]:80/"),
])
def test_redact_url(url, want):
    assert redact_url(url) == want


def test_redact_url_invalid_fails_closed():
    assert redact_url("http://secret:pw@[bad/") == "<redacted url>"


@pytest.mark.parametrize("url", ["https://us\ter:pa\tss@host/x", "https://us\ner:pa\rss@host/x"])
def test_redact_url_userinfo_with_control_chars(url):
    out = redact_url(url)
    assert out == "https://host/x"
