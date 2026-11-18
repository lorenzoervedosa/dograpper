"""Tests for dograpper.lib.url_filter."""

import re

import pytest

from dograpper.lib.url_filter import UrlFilters, filter_urls


def test_filter_same_netloc_only():
    urls = [
        "https://site.io/docs/a",
        "https://other.io/docs/a",
        "http://site.io/docs/b",  # different scheme, same netloc → kept
    ]
    kept = filter_urls(urls, "https://site.io/docs/")
    assert "https://site.io/docs/a" in kept
    assert "http://site.io/docs/b" in kept
    assert "https://other.io/docs/a" not in kept


def test_filter_path_prefix_canonicalization():
    """Regression: `/docs` must NOT match `/docsextra` (v1 Critic C-3)."""
    urls = [
        "https://site.io/docs/intro",
        "https://site.io/docs/api/ref",
        "https://site.io/docsextra/should-not-match",
        "https://site.io/docs-beta/nope",
        "https://site.io/other",
    ]
    kept = filter_urls(urls, "https://site.io/docs")
    assert "https://site.io/docs/intro" in kept
    assert "https://site.io/docs/api/ref" in kept
    assert "https://site.io/docsextra/should-not-match" not in kept
    assert "https://site.io/docs-beta/nope" not in kept
    assert "https://site.io/other" not in kept


def test_filter_depth_zero_no_limit():
    urls = [
        "https://site.io/docs/a",
        "https://site.io/docs/a/b/c/d/e",
    ]
    kept = filter_urls(urls, "https://site.io/docs/", depth=0)
    assert kept == urls


def test_filter_depth_bounded():
    urls = [
        "https://site.io/docs/a",          # depth 1
        "https://site.io/docs/a/b",        # depth 2
        "https://site.io/docs/a/b/c",      # depth 3 -- rejected at depth=2
    ]
    kept = filter_urls(urls, "https://site.io/docs/", depth=2)
    assert "https://site.io/docs/a" in kept
    assert "https://site.io/docs/a/b" in kept
    assert "https://site.io/docs/a/b/c" not in kept


def test_filter_dedupes_preserves_order():
    urls = [
        "https://site.io/docs/a",
        "https://site.io/docs/a",
        "https://site.io/docs/b",
        "https://site.io/docs/a",
    ]
    kept = filter_urls(urls, "https://site.io/docs/")
    assert kept == ["https://site.io/docs/a", "https://site.io/docs/b"]


def test_filter_rejects_base_url_missing_scheme():
    assert filter_urls(["https://site.io/x"], "site.io/docs") == []


def test_filter_accepts_root_base_url():
    urls = [
        "https://site.io/",
        "https://site.io/anything",
        "https://other.io/x",
    ]
    kept = filter_urls(urls, "https://site.io/")
    assert "https://site.io/" in kept
    assert "https://site.io/anything" in kept
    assert "https://other.io/x" not in kept


# --- --filter rules (HTTrack scan-rule syntax, src/htsfilters.c strjoker) ---

def _decide(rules, url):
    return UrlFilters(rules).decide(url)


@pytest.mark.parametrize("rule, url, verdict", [
    ("+*.gif", "http://h.io/a.gif", True),
    ("+*.gif", "http://h.io/a.gif?x=1", True),        # a query may follow the pattern's end
    ("+*.gif", "http://h.io/a.gifx", None),
    ("-*/WIKI/on*", "http://h.io/wiki/OnTick", False),  # literals ignore ASCII case
    ("+h.io/x/*[a-z]", "http://h.io/x/abc", True),
    ("+h.io/x/*[a-z]", "http://h.io/x/ABC", None),     # classes do not
    ("+h.io/*[file].html", "http://h.io/a.html", True),
    ("+h.io/*[file].html", "http://h.io/d/a.html", None),  # *[file] stops at /
    ("+h.io/*[path]/x", "http://h.io/a/b/x", True),
    ("+h.io/*[path]/x", "http://h.io/a?q=/x", None),   # *[path] stops at ?
    ("+h.io/page*[param]", "http://h.io/page", True),
    ("+h.io/page*[param]", "http://h.io/page?x=1", True),
    ("+h.io/page*[param]", "http://h.io/pagex", None),
    ("+*.html*[]", "http://h.io/a.html", True),
    ("+*.html*[]", "http://h.io/a.html?page=10", None),  # *[]: nothing may follow
    ("+h.io/*[\\[,\\],^,-,\\\\]", "http://h.io/[]^-\\", True),
    ("+h.io/a-*[0-9]", "http://h.io/a-123", True),
    ("+h.io/a*", "http://h.io/abc", True),             # host/path form
    ("+http://h.io/a*", "http://h.io/abc", True),      # full form
    ("+h.io/a*", "http://u:p@h.io/abc", True),         # credentials stripped from the short form
    ("+h.io/a", "http://h.io/a#frag", True),           # the fragment is not matched
    ("+h.io/*", "http://h.io", True),                  # a bare host means its root path
])
def test_filter_rule_semantics(rule, url, verdict):
    assert _decide([rule], url) is verdict


def test_filter_last_matching_rule_wins():
    assert _decide(["+*.gif", "-*image*.gif"], "http://h.io/image1.gif") is False
    assert _decide(["+*.gif", "-*image*.gif"], "http://h.io/a.gif") is True
    assert _decide(["-*image*.gif", "+*.gif"], "http://h.io/image1.gif") is True


@pytest.mark.parametrize("rule, message", [
    ("*.gif", "must start with + or -"),
    ("+mime:text/html", "MIME rules"),
    ("-*[<10]", "size rules"),
    ("+*(a,b)", "*(...)"),
])
def test_filter_unsupported_rules_fail_loud(rule, message):
    with pytest.raises(ValueError, match=re.escape(message)):
        UrlFilters([rule])


def test_filter_records_refused_urls():
    f = UrlFilters(["-*Special:*"])
    f.decide("http://h.io/Special:Random#top")
    f.decide("http://h.io/Special:Random")
    f.decide("http://h.io/ok")
    assert f.excluded == {"http://h.io/Special:Random"}


def test_filter_urls_plus_rule_lifts_path_prefix_minus_rule_drops():
    """The MediaWiki case of #96: a seed under /w/ with members under /wiki/On*."""
    seed = "https://pzwiki.net/w/index.php?title=Category:Current_Lua_events"
    urls = [
        seed,
        "https://pzwiki.net/wiki/OnTick",
        "https://pzwiki.net/wiki/Category:En",
        "https://pzwiki.net/w/index.php?title=Special:Random",
        "https://other.io/wiki/OnTick",
    ]
    f = UrlFilters(["-*", "+pzwiki.net/wiki/On*"])
    kept = filter_urls(urls, seed, filters=f)
    assert kept == [seed, "https://pzwiki.net/wiki/OnTick"]  # the seed is always allowed
    assert f.excluded == {"https://pzwiki.net/wiki/Category:En",
                          "https://pzwiki.net/w/index.php?title=Special:Random"}


def test_filter_urls_unmatched_urls_keep_the_default_scope():
    f = UrlFilters(["-*/docs/old/*", "+site.io/blog/*"])
    urls = ["https://site.io/docs/a", "https://site.io/docs/old/b",
            "https://site.io/blog/c", "https://site.io/other"]
    assert filter_urls(urls, "https://site.io/docs/", filters=f) == [
        "https://site.io/docs/a", "https://site.io/blog/c"]
    assert f.excluded == {"https://site.io/docs/old/b"}


def test_filter_urls_plus_rule_keeps_depth_limit():
    f = UrlFilters(["+site.io/blog/*"])
    urls = ["https://site.io/blog/a", "https://site.io/blog/a/b/c"]
    assert filter_urls(urls, "https://site.io/docs/", depth=2, filters=f) == ["https://site.io/blog/a"]


def test_filter_urls_too_deep_url_is_not_a_filter_decision():
    f = UrlFilters(["-*/old*"])
    urls = ["https://site.io/docs/old", "https://site.io/docs/a/b/old"]
    assert filter_urls(urls, "https://site.io/docs/", depth=1, filters=f) == []
    assert f.excluded == {"https://site.io/docs/old"}
