import logging
import time

from dograpper.lib.httrack.robots import NO_RULES, RobotsRules, parse_robots


def test_specific_group_beats_star():
    r = parse_robots("User-agent: dograpper\nDisallow: /x\n\nUser-agent: *\nDisallow: /\n")
    assert r.allowed("/y") is True
    assert r.allowed("/x") is False


def test_star_group_used_without_specific():
    r = parse_robots("User-agent: *\nDisallow: /\n")
    assert r.allowed("/y") is False


def test_consecutive_user_agents_share_group():
    r = parse_robots("User-agent: foo\nUser-agent: dograpper\nDisallow: /z\n")
    assert r.allowed("/z") is False
    assert r.allowed("/ok") is True


def test_longest_match_wins():
    r = parse_robots("User-agent: *\nDisallow: /a\nAllow: /a/b\n")
    assert r.allowed("/a/b/c") is True
    assert r.allowed("/a/x") is False


def test_allow_wins_tie():
    r = parse_robots("User-agent: *\nAllow: /p\nDisallow: /p\n")
    assert r.allowed("/p") is True
    r = parse_robots("User-agent: *\nDisallow: /p\nAllow: /p\n")
    assert r.allowed("/p") is True


def test_empty_disallow_ignored():
    assert parse_robots("User-agent: *\nDisallow:\n").allowed("/x") is True


def test_robots_txt_always_allowed():
    assert parse_robots("User-agent: *\nDisallow: /\n").allowed("/robots.txt") is True


def test_wildcard_and_end_anchor():
    r = parse_robots("User-agent: *\nDisallow: /*.pdf$\n")
    assert r.allowed("/x.pdf") is False
    assert r.allowed("/x.pdf?y") is True


def test_crawl_delay_from_selected_group_only():
    text = "User-agent: other\nCrawl-delay: 9\n\nUser-agent: *\nCrawl-delay: 2.5\n"
    assert parse_robots(text).crawl_delay == 2.5
    text2 = "User-agent: dograpper\nCrawl-delay: 1\n\nUser-agent: *\nCrawl-delay: 7\n"
    assert parse_robots(text2).crawl_delay == 1.0
    assert parse_robots("User-agent: other\nCrawl-delay: 9\n").crawl_delay is None


def test_sitemaps_collected_globally():
    text = (
        "Sitemap: https://a/s1.xml\nUser-agent: other\nDisallow: /\n"
        "Sitemap: https://a/s2.xml\n"
    )
    assert parse_robots(text).sitemaps == ("https://a/s1.xml", "https://a/s2.xml")


def test_html_soft404_body_yields_no_rules():
    html = "<!DOCTYPE html><html><head><title>Not found</title></head><body><p>Disallow: nothing</p></body></html>"
    r = parse_robots(html)
    assert r.allowed("/anything") is True
    assert r.crawl_delay is None


def test_no_rules_allows_everything():
    assert NO_RULES.allowed("/x") is True
    assert NO_RULES.crawl_delay is None
    assert isinstance(NO_RULES, RobotsRules)


def test_oversized_rules_truncated_with_warning(caplog):
    long_path = "/" + "a" * 2000
    text = f"User-agent: *\nAllow: {long_path}\nDisallow: {long_path}\n"
    with caplog.at_level(logging.WARNING):
        r = parse_robots(text)
    assert caplog.records
    # Allow dropped, truncated Disallow kept (as a 1024-byte prefix rule).
    assert r.allowed(long_path) is False
    assert len(r.groups_rules) == 1
    assert r.groups_rules[0][0] == "disallow"


def test_text_capped_at_500kib(caplog):
    text = "User-agent: *\n" + "# c\n" * 200_000 + "Disallow: /late\n"
    with caplog.at_level(logging.WARNING):
        r = parse_robots(text)
    assert r.allowed("/late") is True
    assert caplog.records


def test_many_wildcards_is_linear():
    r = parse_robots("User-agent: *\nDisallow: /" + "*a" * 200 + "b\n")
    start = time.perf_counter()
    assert r.allowed("/" + "a" * 5000) is True
    assert time.perf_counter() - start < 1.0


def test_multi_star_anchored_suffix():
    r = parse_robots("User-agent: *\nDisallow: /a*b*c$\n")
    assert r.allowed("/axbyc") is False
    assert r.allowed("/axbycz") is True
    assert r.allowed("/abc") is False
    assert r.allowed("/ac") is True


def test_star_in_middle_unanchored():
    r = parse_robots("User-agent: *\nDisallow: /*x*y\n")
    assert r.allowed("/zzxzzy") is False
    assert r.allowed("/zzyzzx") is True


def test_percent_escape_hex_case_insensitive():
    r = parse_robots("User-agent: *\nDisallow: /caf%c3%a9\nDisallow: /x%2Fy\n")
    assert not r.allowed("/caf%C3%A9") and not r.allowed("/caf%c3%a9")
    assert not r.allowed("/x%2fy")
    assert r.allowed("/cafe")


def test_truncated_sitemap_line_discarded():
    long = "http://h/" + "a" * 1100 + ".xml"
    r = parse_robots(f"Sitemap: {long}\nSitemap: http://h/ok.xml\n")
    assert r.sitemaps == ("http://h/ok.xml",)
