import pytest

from dograpper.utils.redact import (
    mask_secret_params, neutralize_controls, recordable_url, redact_url,
)


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


def test_redact_url_percent_encodes_control_characters():
    assert redact_url("http://h/a\x1b[31m\x7f\x9b\r\nb") == "http://h/a%1B[31m%7F%9B%0D%0Ab"
    assert redact_url("http://u:p@h/\x1b") == "http://h/%1B"


def test_neutralize_controls_escapes_c0_del_c1_only():
    assert neutralize_controls("a\x1b[31m\x07\x7f\x9b\té~") == "a\\x1b[31m\\x07\\x7f\\x9b\\x09é~"


@pytest.mark.parametrize("url,want", [
    ("https://h/w/index.php?title=Category:Lua&pagefrom=On%26Off&oldid=5&page=2&lang=en",
     "https://h/w/index.php?title=Category:Lua&pagefrom=On%26Off&oldid=5&page=2&lang=en"),
    ("https://h/?token=abc&title=T", "https://h/?token=REDACTED&title=T"),
    ("https://b.s3/doc?X-Amz-Credential=c&X-Amz-Signature=s&x-goog-expires=1",
     "https://b.s3/doc?X-Amz-Credential=REDACTED&X-Amz-Signature=REDACTED"
     "&x-goog-expires=REDACTED"),
    ("https://h/?client_secret=a&sessionToken=b&apiKey=c;Pass_Word=d#frag",
     "https://h/?client_secret=REDACTED&sessionToken=REDACTED&apiKey=REDACTED"
     ";Pass_Word=REDACTED#frag"),
    ("https://h/?access%5Ftoken=a==&flag", "https://h/?access%5Ftoken=REDACTED&flag"),
    ("https://h/?jwt=a&pwd=b&sid=c&Ticket=d&hmac=e&nonce=f&otp=g&code=h&zipcode=1",
     "https://h/?jwt=REDACTED&pwd=REDACTED&sid=REDACTED&Ticket=REDACTED&hmac=REDACTED"
     "&nonce=REDACTED&otp=REDACTED&code=REDACTED&zipcode=1"),
    # accepted false positives: names that merely contain a credential word
    ("https://h/?design=1&author=x&keyword=y",
     "https://h/?design=REDACTED&author=REDACTED&keyword=REDACTED"),
    ("https://h/a#token=frag-only", "https://h/a#token=frag-only"),
    ("https://example.com/x?", "https://example.com/x?"),
])
def test_mask_secret_params_masks_credential_like_values(url, want):
    assert mask_secret_params(url) == want


@pytest.mark.parametrize("url,want", [
    ("https://u:p@h/a/b.html", "https://h/a/b.html"),
    ("https://h/w/index.php?title=X&oldid=5", "https://h/w/index.php?title=X&oldid=5"),
    ("https://h/w/index.php?Title=X&PageFrom=On%26Off", "https://h/w/index.php?Title=X&PageFrom=On%26Off"),
    ("https://h/?title=X&token=abc", None),
    ("https://h/?foo=1", None),
    ("https://h/?print", None),
    ("https://h/doc?X-Amz-Signature=s", None),
    ("https://h/a#token=frag-only", "https://h/a#token=frag-only"),
])
def test_recordable_url_allows_navigation_queries_only(url, want):
    assert recordable_url(url) == want


@pytest.mark.parametrize("name", ["client_secret", "X-Amz-Credential", "sessionToken", "apiKey",
                                  "jwt"])
def test_redact_url_masks_credential_like_params_in_logs(name):
    assert redact_url(f"https://u:p@h/?title=T&{name}=pw") == f"https://h/?title=T&{name}=REDACTED"


def test_first_line_keeps_an_errors_first_line_or_names_its_type():
    """Playwright appends a call log to its errors: only the first line is shown."""
    from dograpper.utils.redact import first_line
    assert first_line(Exception("Timeout 10000ms exceeded.\n=== logs ===\n  navigating")) == \
        "Timeout 10000ms exceeded."
    assert first_line(TimeoutError()) == "TimeoutError"
