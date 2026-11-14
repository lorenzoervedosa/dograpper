"""--downloader httrack profile on `download`: flags, fail-loud paths, precedence.

No test here touches the network: ``Fetcher`` is replaced by FakeFetcher.
"""

import json
import logging
import os
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.commands.download import _discover_urls, download
from dograpper.lib.httrack.crawl import HttrackResult
from dograpper.lib.httrack.fetcher import FetchResult
from dograpper.lib.httrack.report import RunReport
from dograpper.lib.httrack.robots import NO_RULES, RobotsRules
from dograpper.lib.wget_mirror import WgetResult

URLS = [f"http://example.com/p{i}" for i in range(5)]


class FakeFetcher:
    instances: list = []

    def __init__(self, policy):
        self.policy = policy
        self.gets: list = []
        self.robots_calls: list = []
        FakeFetcher.instances.append(self)

    def get(self, url, *, kind, referer=None):
        self.gets.append(url)
        return FetchResult(url, status=404)

    def robots_for(self, origin):
        self.robots_calls.append(origin)
        return NO_RULES


@pytest.fixture(autouse=True)
def fake_fetcher():
    FakeFetcher.instances = []
    with patch("dograpper.commands.download.Fetcher", FakeFetcher):
        yield


def _res(out, success=True, front_failed=False):
    f = os.path.join(out, "p0.html")
    with open(f, "w") as fh:
        fh.write("<html><body><p>" + "A" * 300 + "</p></body></html>")
    report = RunReport()
    report.status_counts["4xx"] = 5
    return HttrackResult(success, [f], 0, report, front_failed)


@pytest.fixture
def ht(tmp_path):
    """Patch discovery (layer 1 wins) + fetch_url_list + is_spa; yield mocks."""
    out = str(tmp_path / "out")
    os.makedirs(out)
    with patch("dograpper.commands.download.fetch_llms_txt", return_value=URLS), \
         patch("dograpper.commands.download.fetch_url_list") as fu, \
         patch("dograpper.commands.download.is_spa", return_value=False), \
         patch("dograpper.commands.download.warn_if_old_openssl") as warn:
        fu.side_effect = lambda urls, o, *a, **k: _res(o)
        yield out, fu, warn


def run(out, *args, config=None):
    """Invoke `download` with an isolated manifest (never the repo root)."""
    pre = ["--config", str(config)] if config else []
    return CliRunner().invoke(
        cli, [*pre, "download", "http://example.com", "-o", out,
              "--manifest", out + ".manifest.json", *args])


def _config(tmp_path, **kv):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"download": kv}))
    return cfg


def test_default_downloader_is_wget_unchanged(tmp_path):
    out = str(tmp_path)
    with patch("dograpper.commands.download.fetch_llms_txt", return_value=URLS) as llms, \
         patch("dograpper.commands.download.fetch_sitemap") as sm, \
         patch("dograpper.commands.download.run_wget_urls") as wu, \
         patch("dograpper.commands.download.fetch_url_list") as fu, \
         patch("dograpper.commands.download.is_spa", return_value=False):
        wu.return_value = WgetResult(True, out, [], [], 0)
        res = CliRunner().invoke(download, ["http://example.com", "-o", out,
                                            "--manifest", out + ".m.json"])
    assert res.exit_code == 0, res.output
    llms.assert_called_once_with("http://example.com")
    sm.assert_not_called()
    wu.assert_called_once_with(URLS, out, 0, "html,md,txt")
    fu.assert_not_called()
    assert FakeFetcher.instances == []


@pytest.mark.parametrize("flag", ["--no-robots", "--connections=2", "--user-agent=x"])
def test_httrack_flag_with_wget_is_usage_error(tmp_path, flag):
    res = run(str(tmp_path / "o"), flag)
    assert res.exit_code == 2
    assert flag.split("=")[0] in res.output


def test_httrack_flag_in_config_with_wget_is_usage_error(tmp_path):
    res = run(str(tmp_path / "o"), config=_config(tmp_path, **{"max-links": 5}))
    assert res.exit_code == 2
    assert "--max-links" in res.output


def test_unknown_downloader_in_config_is_usage_error(tmp_path):
    res = run(str(tmp_path / "o"), config=_config(tmp_path, downloader="HTTrack"))
    assert res.exit_code == 2
    assert "HTTrack" in res.output
    assert "wget" in res.output and "httrack" in res.output


def test_httrack_seeded_fetch_happy_path(ht):
    out, fu, warn = ht
    res = run(out, "--downloader", "httrack")
    assert res.exit_code == 0, res.output
    warn.assert_called_once()
    assert fu.call_args.args[0] == URLS
    assert "Files downloaded: 1" in res.output
    assert "Responses:" in res.output


def test_httrack_one_fetcher_shared_by_discovery_and_fetch(ht):
    out, fu, _ = ht
    seen = {}

    def llms(base, fetch=None):
        fetch("http://example.com/llms.txt")
        return URLS

    with patch("dograpper.commands.download.fetch_llms_txt", side_effect=llms):
        res = run(out, "--downloader", "httrack")
    assert res.exit_code == 0, res.output
    assert len(FakeFetcher.instances) == 1
    shared = FakeFetcher.instances[0]
    assert fu.call_args.kwargs["fetcher"] is shared
    assert fu.call_args.args[2] is shared.policy
    assert "http://example.com/llms.txt" in shared.gets  # discovery used it too


def test_httrack_all_seeds_challenged_exits_1(ht):
    out, fu, _ = ht
    fu.side_effect = lambda urls, o, *a, **k: _res(o, success=False, front_failed=True)
    res = run(out, "--downloader", "httrack")
    assert res.exit_code == 1
    assert "bot protection" in res.output
    assert "Downloader profiles" in res.output
    assert "browser-login" not in res.output
    assert "Responses:" in res.output  # report printed before the error


def test_httrack_fetch_failure_prints_report(ht):
    out, fu, _ = ht
    fu.side_effect = lambda urls, o, *a, **k: _res(o, success=False)
    res = run(out, "--downloader", "httrack")
    assert res.exit_code == 1
    assert "httrack fetch failed" in res.output
    assert "Responses:" in res.output


def test_httrack_no_discovery_fails_loud_recursive_crawl(tmp_path):
    out = str(tmp_path / "o")
    with patch("dograpper.commands.download.fetch_llms_txt", return_value=[]), \
         patch("dograpper.commands.download.fetch_sitemap", return_value=[]), \
         patch("dograpper.commands.download.warn_if_old_openssl"):
        res = run(out, "--downloader", "httrack")
    assert res.exit_code == 1
    assert "recursive crawl is not implemented yet" in res.output


def test_httrack_headless_fails_loud_playwright(ht):
    out, fu, _ = ht
    res = run(out, "--downloader", "httrack", "--headless")
    assert res.exit_code == 1
    assert "Playwright fallback is not implemented yet" in res.output
    fu.assert_not_called()


def test_httrack_spa_fails_loud_playwright(ht):
    out, _, _ = ht
    with patch("dograpper.commands.download.is_spa", return_value=True):
        res = run(out, "--downloader", "httrack")
    assert res.exit_code == 1
    assert "Playwright fallback is not implemented yet" in res.output


def test_httrack_config_keys_respected_and_cli_wins(ht, tmp_path):
    out, fu, _ = ht
    cfg = _config(tmp_path, downloader="httrack", connections=3,
                  **{"max-links": 50, "no-robots": True})
    res = run(out, "--connections", "2", config=cfg)
    assert res.exit_code == 0, res.output
    policy = fu.call_args.args[2]
    assert policy.connections == 2          # CLI beats config
    assert policy.max_links == 50           # config beats default
    assert policy.obey_robots is False


def test_httrack_invalid_config_value_names_option_and_source(ht, tmp_path):
    out, _, _ = ht
    res = run(out, config=_config(tmp_path, downloader="httrack", connections=0))
    assert res.exit_code == 2
    assert "--connections" in res.output
    assert ".dograpper.json" in res.output


def test_httrack_non_numeric_config_value_is_usage_error(ht, tmp_path):
    out, _, _ = ht
    res = run(out, config=_config(tmp_path, downloader="httrack", connections="4"))
    assert res.exit_code == 2
    assert "--connections" in res.output
    assert ".dograpper.json" in res.output
    assert "Traceback" not in res.output


def test_httrack_negative_delay_names_cli_option(ht):
    out, _, _ = ht
    res = run(out, "--downloader", "httrack", "--delay", "-1")
    assert res.exit_code == 2
    assert "--delay" in res.output
    assert "delay_ms" not in res.output


def test_invalid_cli_bound_is_usage_error(tmp_path):
    res = run(str(tmp_path / "o"), "--connections", "0")
    assert res.exit_code == 2


def _fetcher_with(rules, status=200, **result_kw):
    calls = []

    class F:
        def get(self, url, *, kind, referer=None):
            calls.append((url, kind, referer))
            return FetchResult(url, status=status, body=b"x", **result_kw)

        def robots_for(self, origin):
            return rules

    return F(), calls


def test_discovery_checks_robots_before_fetching_and_uses_robots_kind():
    rules = RobotsRules((("disallow", "/blocked"),), None, ("http://example.com/sm.xml",))
    f, calls = _fetcher_with(rules)
    seen = {}

    def llms(base, fetch=None):
        seen["ok"] = fetch("http://example.com/llms.txt")
        seen["blocked"] = fetch("http://example.com/blocked")
        return []

    def sm(base, fetch=None, extra_candidates=()):
        seen["extra"] = tuple(extra_candidates)
        return []

    with patch("dograpper.commands.download.fetch_llms_txt", side_effect=llms), \
         patch("dograpper.commands.download.fetch_sitemap", side_effect=sm):
        assert _discover_urls("http://example.com", 0, f) == ([], "none")
    assert seen["ok"] == b"x" and seen["blocked"] is None
    assert seen["extra"] == ("http://example.com/sm.xml",)
    assert [u for u, _, _ in calls] == ["http://example.com/llms.txt"]  # no GET for /blocked
    assert all(k == "robots" and r is None for _, k, r in calls)


def test_discovery_warns_on_robots_blocked_challenged_and_redirected(caplog):
    blocked = RobotsRules((("disallow", "/"),), None, ())
    probes = {
        "blocked": (blocked, 200, {}),
        "challenged": (NO_RULES, 403, {"challenged": True}),
        "redirected": (NO_RULES, 301, {}),
    }
    for name, (rules, status, kw) in probes.items():
        f, _ = _fetcher_with(rules, status=status, **kw)

        def llms(base, fetch=None):
            assert fetch("http://example.com/llms.txt") is None
            return []

        caplog.clear()
        with caplog.at_level(logging.WARNING), \
             patch("dograpper.commands.download.fetch_llms_txt", side_effect=llms), \
             patch("dograpper.commands.download.fetch_sitemap", return_value=[]):
            _discover_urls("http://example.com", 0, f)
        assert any(r.levelno == logging.WARNING and name[:7] in r.getMessage()
                   for r in caplog.records), (name, caplog.records)


def test_forwarded_explicit_value_not_labeled_as_config():
    """A policy error on a value a wrapper forwarded as explicit must not say
    "(from .dograpper.json)"; an unforwarded value (config-sourced) must."""
    import click

    @click.command()
    @click.pass_context
    def wrapper(ctx):
        ctx.obj = {'CLI_EXPLICIT_PARAMS': {'delay'}}
        ctx.invoke(download, url="http://example.com", output="out", delay=-5,
                   downloader="httrack")

    runner = CliRunner()
    with runner.isolated_filesystem():
        r = runner.invoke(wrapper)
        assert "--delay must not be negative" in r.output
        assert "(from .dograpper.json)" not in r.output
        with open(".dograpper.json", "w", encoding="utf-8") as f:
            json.dump({"download": {"delay": -5}}, f)

        @click.command()
        @click.pass_context
        def wrapper2(ctx):
            ctx.obj = {}
            ctx.invoke(download, url="http://example.com", output="out",
                       delay=0, downloader="httrack")

        r = runner.invoke(wrapper2)
        assert "--delay must not be negative" in r.output
        assert "(from .dograpper.json)" in r.output
