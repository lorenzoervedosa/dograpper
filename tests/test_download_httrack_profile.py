"""--downloader httrack profile on `download`: flags, fail-loud paths, precedence.

No test here touches the network: ``Fetcher`` is replaced by FakeFetcher.
"""

import json
import logging
import os
import sys
from unittest.mock import MagicMock, patch

import pytest
from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.commands._httrack_profile import PROFILE_OPTIONS, discovery_fetch
from dograpper.commands.download import _discover_urls, download
from dograpper.lib.httrack.crawl import HttrackResult
from dograpper.lib.httrack.fetcher import FetchResult
from dograpper.lib.httrack.report import RunReport
from dograpper.lib.httrack.robots import NO_RULES, RobotsRules, parse_robots
from dograpper.lib.playwright_crawl import CrawlResult
from dograpper.lib.wget_mirror import WgetResult

P = "dograpper.commands._httrack_profile"  # the httrack mode's module (patch target)
URLS = [f"http://example.com/p{i}" for i in range(5)]


class FakeFetcher:
    instances: list = []

    def __init__(self, policy, cookies=None):
        self.policy, self.cookies = policy, cookies
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
    with patch(f"{P}.Fetcher", FakeFetcher):
        yield


def _res(out, success=True, front_failed=False, challenged=(), robots_blocked=()):
    f = os.path.join(out, "p0.html")
    with open(f, "w") as fh:
        fh.write("<html><body><p>" + "A" * 300 + "</p></body></html>")
    report = RunReport()
    report.status_counts["4xx"] = 5
    report.challenged, report.robots_blocked = list(challenged), list(robots_blocked)
    return HttrackResult(success, [f], 0, report, front_failed)


@pytest.fixture
def ht(tmp_path):
    """Patch discovery (layer 1 wins) + fetch_url_list + is_spa; yield mocks."""
    out = str(tmp_path / "out")
    os.makedirs(out)
    with patch("dograpper.commands.download.fetch_llms_txt", return_value=URLS), \
         patch(f"{P}.fetch_url_list") as fu, \
         patch(f"{P}.is_spa", return_value=False), \
         patch(f"{P}.warn_if_old_openssl") as warn:
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
         patch(f"{P}.fetch_url_list") as fu, \
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


def test_profile_options_tuple_matches_download_and_sync():
    from dograpper.commands.sync import sync
    tagged = {p.name for p in download.params
              if (getattr(p, "help", None) or "").startswith("[httrack, fire-engine]")}
    assert tagged == set(PROFILE_OPTIONS)
    assert set(PROFILE_OPTIONS) <= {p.name for p in sync.params}


@pytest.mark.parametrize("flag", ["--no-robots", "--connections=2", "--user-agent=x",
                                  "--retries=2", "--no-parse-scripts",
                                  "--no-extended-parsing", "--cache=2",
                                  "--updatehack", "--do-not-recatch",
                                  "--changes"])  # explicit, even at its default
def test_httrack_flag_with_wget_is_usage_error(tmp_path, flag):
    res = run(str(tmp_path / "o"), flag)
    assert res.exit_code == 2
    assert f"{flag.split('=')[0]} requires --downloader httrack or fire-engine" in res.output


@pytest.mark.parametrize("downloader", ["wget", "fire-engine"])
@pytest.mark.parametrize("config", [False, True])
@pytest.mark.parametrize("flag, key, value", [("--cookies", "cookies", "c.txt")])
def test_httrack_only_flag_under_another_downloader_is_usage_error(tmp_path, downloader,
                                                                   config, flag, key, value):
    """#169: the [httrack] flags have no fire-engine counterpart (#152) nor a wget one."""
    if config:
        res = run(str(tmp_path / "o"), "--downloader", downloader,
                  config=_config(tmp_path, **{key: value}))
    else:
        res = run(str(tmp_path / "o"), "--downloader", downloader, f"{flag}={value}")
    assert res.exit_code == 2
    assert f"{flag} requires --downloader httrack" in res.output
    assert not os.path.exists(tmp_path / value)


def test_httrack_only_options_tuple_matches_download_and_sync():
    from dograpper.commands._httrack_profile import HTTRACK_OPTIONS
    from dograpper.commands.sync import sync
    tagged = {p.name for p in download.params
              if (getattr(p, "help", None) or "").startswith("[httrack] ")}
    assert tagged == set(HTTRACK_OPTIONS)
    assert set(HTTRACK_OPTIONS) <= {p.name for p in sync.params}


def test_httrack_flag_in_config_with_wget_is_usage_error(tmp_path):
    res = run(str(tmp_path / "o"), config=_config(tmp_path, **{"max-links": 5}))
    assert res.exit_code == 2
    assert "--max-links requires --downloader httrack or fire-engine" in res.output


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


def test_httrack_filter_scopes_discovered_urls_and_reaches_the_fetch(ht):
    out, fu, _ = ht
    res = run(out, "--downloader", "httrack", "--filter", "-*/p1",
              "--filter", "-*/p2", "--filter", "+*/p2")  # any order works off wget
    assert res.exit_code == 0, res.output
    assert fu.call_args.args[0] == [u for u in URLS if not u.endswith("/p1")]
    assert [r[1] for r in fu.call_args.kwargs["filters"].rules] == ["*/p1", "*/p2", "*/p2"]
    assert "Filtered by --filter: 1" in res.output


def test_httrack_manifest_records_the_urls_fetched(ht):
    out, fu, _ = ht

    def fetched(urls, o, *a, **k):
        res = _res(o)
        res.urls = {res.files_downloaded[0]: "http://example.com/p0?lang=en"}
        return res
    fu.side_effect = fetched
    res = run(out, "--downloader", "httrack")
    assert res.exit_code == 0, res.output
    manifest = json.loads(open(out + ".manifest.json").read())
    assert {e["local_path"]: e["url"] for e in manifest["files"].values()} == {
        "p0.html": "http://example.com/p0?lang=en"}


def test_httrack_one_fetcher_shared_by_discovery_and_fetch(ht):
    out, fu, _ = ht

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
    fu.side_effect = lambda urls, o, *a, **k: _res(
        o, success=False, front_failed=True, challenged=URLS[:1], robots_blocked=URLS[1:])
    res = run(out, "--downloader", "httrack")
    assert res.exit_code == 1
    assert "bot protection" in res.output
    assert "Downloader profiles" in res.output
    assert "browser-login" not in res.output
    assert "Responses:" in res.output  # report printed before the error


def test_httrack_all_seeds_refused_without_challenge_names_robots(ht):
    out, fu, _ = ht
    fu.side_effect = lambda urls, o, *a, **k: _res(
        o, success=False, front_failed=True, robots_blocked=URLS)
    res = run(out, "--downloader", "httrack")
    assert res.exit_code == 1
    error = [ln for ln in res.output.splitlines() if ln.startswith("Error:")]
    assert len(error) == 1 and "bot protection" not in error[0]
    assert "blocked by robots.txt" in error[0]
    assert "Downloader profiles" in error[0]


def test_httrack_fetch_failure_prints_report(ht):
    out, fu, _ = ht
    fu.side_effect = lambda urls, o, *a, **k: _res(o, success=False)
    res = run(out, "--downloader", "httrack")
    assert res.exit_code == 1
    assert "httrack fetch failed" in res.output
    assert "Responses:" in res.output


def _crawled(out, names=("index.html", "a.html"), **kw):
    files = []
    for name in names:
        files.append(os.path.join(out, name))
        with open(files[-1], "w") as fh:
            fh.write("<html><body><p>" + "A" * 300 + "</p></body></html>")
    return HttrackResult(bool(files), files, 0, RunReport(**kw), False,
                         {f: "http://example.com/" + os.path.basename(f) for f in files})


@pytest.fixture
def crawl(tmp_path):
    """Nothing discovered (layers 1+2 empty): patch mirror_site; yield (out, mock)."""
    out = str(tmp_path / "out")
    os.makedirs(out)
    with patch("dograpper.commands.download.fetch_llms_txt", return_value=[]), \
         patch("dograpper.commands.download.fetch_sitemap", return_value=[]), \
         patch(f"{P}.mirror_site") as ms, patch(f"{P}.warn_if_old_openssl"):
        ms.side_effect = lambda u, o, *a, **k: _crawled(o)
        yield out, ms


def test_httrack_no_discovery_runs_the_recursive_crawl(crawl):
    out, ms = crawl
    res = run(out, "--downloader", "httrack", "-d", "3", "--filter", "-*/private/*")
    assert res.exit_code == 0, res.output
    (url, o, policy, exts), kw = ms.call_args
    assert (url, o, exts, kw["depth"]) == ("http://example.com", out, "html,md,txt", 3)
    assert kw["fetcher"] is FakeFetcher.instances[0] and kw["fetcher"].policy is policy
    assert [r[1] for r in kw["filters"].rules] == ["*/private/*"]
    assert "Files downloaded: 2" in res.output and "Responses:" in res.output
    manifest = json.loads(open(out + ".manifest.json").read())
    assert {e["local_path"]: e["url"] for e in manifest["files"].values()} == {
        "index.html": "http://example.com/index.html", "a.html": "http://example.com/a.html"}


@pytest.mark.parametrize("challenged,cause", [
    (["http://example.com/"], "the site challenged the start URL (likely bot protection)"),
    ([], "the start URL was blocked by robots.txt, redirected out of scope or failed"),
])
def test_httrack_crawl_front_failure_exits_1(crawl, challenged, cause):
    out, ms = crawl
    ms.side_effect = lambda u, o, *a, **k: HttrackResult(
        False, [], 0, RunReport(challenged=list(challenged)), True)
    res = run(out, "--downloader", "httrack")
    assert res.exit_code == 1
    assert cause in res.output and "Downloader profiles" in res.output
    assert "Responses:" in res.output  # report printed before the error


def _rendered(out, names=("index.html",), challenged=()):
    """What run_playwright_crawl returns under the profile: the files its navigator saved,
    the navigator's report filled as the policy refused pages."""
    def crawl(url, o, depth, delay, exts, manifest_data, *, seed_urls, filters, navigator):
        navigator.report.challenged.extend(challenged)
        files = []
        for name in names:
            files.append(os.path.join(o, name))
            with open(files[-1], "w") as fh:
                fh.write("<html><body><p>" + "R" * 300 + "</p></body></html>")
            navigator.records[files[-1]] = {"status": 200, "content_type": "text/html",
                                            "etag": '"r"', "last_modified": None,
                                            "redirected": False}
        return CrawlResult(True, o, files, [], 0, {f: "http://example.com/" +
                                                   os.path.basename(f) for f in files})
    return crawl


def test_httrack_crawl_of_one_page_falls_back_to_playwright_under_the_policy(crawl):
    out, ms = crawl
    ms.side_effect = lambda u, o, *a, **k: _crawled(o, names=("index.html",))
    with patch(f"{P}.run_playwright_crawl", side_effect=_rendered(out, ("index.html", "b.html"))
               ) as pw:
        res = run(out, "--downloader", "httrack", "-d", "2", "--delay", "300")
    assert res.exit_code == 0, res.output
    (url, o, depth, delay, exts, manifest_data), kw = pw.call_args
    # pacing is the Fetcher's (policy.delay_ms), the cache is the engine's: none of the crawl's
    assert (url, o, depth, delay, exts, manifest_data) == (
        "http://example.com", out, 2, 0, "html,md,txt", None)
    assert kw["seed_urls"] is None  # nothing discovered: the browser crawls from the start URL
    nav = kw["navigator"]
    assert nav.fetcher is FakeFetcher.instances[0] and nav.fetcher.policy.delay_ms == 300
    assert "Files downloaded: 2" in res.output and "Responses:" in res.output
    manifest = json.loads(open(out + ".manifest.json").read())
    assert {e["local_path"]: e["etag"] for e in manifest["files"].values()} == {
        "index.html": '"r"', "b.html": '"r"'}


def test_httrack_headless_front_failure_exits_1(ht):
    out, _, _ = ht
    with patch(f"{P}.run_playwright_crawl",
               side_effect=_rendered(out, (), challenged=URLS)):
        res = run(out, "--downloader", "httrack", "--headless")
    assert res.exit_code == 1
    assert "the site refused or challenged every seed URL (likely bot protection)" in res.output
    assert "Challenged: 5" in res.output  # report printed before the error


def test_httrack_fallback_that_saves_nothing_keeps_the_engine_result(crawl):
    """The run's start URL was fetched by the engine: no front error (spec 5.8)."""
    out, ms = crawl
    ms.side_effect = lambda u, o, *a, **k: _crawled(o, names=("index.html",))
    with patch(f"{P}.run_playwright_crawl",
               side_effect=_rendered(out, (), challenged=["http://example.com/"])):
        res = run(out, "--downloader", "httrack")
    assert res.exit_code == 0, res.output
    assert "Files downloaded: 1" in res.output
    assert "Playwright pass:" in res.output and "    Challenged: 1" in res.output
    manifest = json.loads(open(out + ".manifest.json").read())
    assert [e["local_path"] for e in manifest["files"].values()] == ["index.html"]


def test_httrack_shallow_crawl_explained_by_challenges_is_no_browser_trigger(crawl):
    """Spec 5.4: the too-shallow fallback is never triggered by a challenge."""
    out, ms = crawl
    ms.side_effect = lambda u, o, *a, **k: _crawled(
        o, names=("index.html",), challenged=["http://example.com/a"])
    with patch(f"{P}.run_playwright_crawl") as pw:
        res = run(out, "--downloader", "httrack")
    assert res.exit_code == 0, res.output
    pw.assert_not_called()
    assert "Challenged: 1" in res.output


def _updated(out, written=(), kept=("index.html", "a.html")):
    """An update crawl: `kept` left as they were (304), `written` saved again."""
    res = _crawled(out, names=(*written, *kept))
    res.files_downloaded = [f for f in res.files_downloaded
                            if os.path.basename(f) in written]
    res.kept = sorted(set(res.urls) - set(res.files_downloaded))
    res.files_skipped, res.success = len(res.kept), True
    res.records = {f: {"status": 200, "content_type": "text/html", "etag": '"e"',
                       "last_modified": None, "redirected": False} for f in res.urls}
    return res


def test_httrack_second_run_is_an_update_of_the_first(crawl):
    """The manifest a run saves is what the next one revalidates (HTTrack -C2)."""
    out, ms = crawl
    assert run(out, "--downloader", "httrack").exit_code == 0
    assert ms.call_args.kwargs["previous"] is None
    ms.side_effect = lambda u, o, *a, **k: _updated(o)
    res = run(out, "--downloader", "httrack")
    assert res.exit_code == 0, res.output  # two kept pages are no one-page crawl
    previous = ms.call_args.kwargs["previous"]
    assert sorted(e.local_path for e in previous.files.values()) == ["a.html", "index.html"]
    assert "Files downloaded: 0" in res.output and "Files skipped:    2 (cached)" in res.output
    manifest = json.loads(open(out + ".manifest.json").read())
    assert {e["local_path"]: (e["status"], e["etag"]) for e in manifest["files"].values()} == {
        "index.html": (200, '"e"'), "a.html": (200, '"e"')}


def test_httrack_update_lists_the_files_it_did_not_reach(crawl):
    out, ms = crawl
    ms.side_effect = lambda u, o, *a, **k: _crawled(o, names=("index.html", "a.html", "b.html"))
    assert run(out, "--downloader", "httrack").exit_code == 0
    ms.side_effect = lambda u, o, *a, **k: _updated(o, written=("index.html",), kept=("a.html",))
    res = CliRunner().invoke(cli, ["-v", "download", "http://example.com", "-o", out,
                                   "--manifest", out + ".manifest.json", "--downloader", "httrack"])
    assert res.exit_code == 0, res.output
    assert "Not reached this run, kept on disk: 1" in res.output
    assert "    http://example.com/b.html" in res.output
    assert os.path.exists(os.path.join(out, "b.html"))  # never purged


def test_httrack_cache_flag_reaches_the_policy(ht):
    out, fu, _ = ht
    assert run(out, "--downloader", "httrack").exit_code == 0
    assert fu.call_args.args[2].cache is None  # HTTrack's default: -C2 over a mirror, else -C1
    res = run(out, "--downloader", "httrack", "--cache", "1")
    assert res.exit_code == 0, res.output
    assert fu.call_args.args[2].cache == 1
    assert run(out, "--downloader", "httrack", "--cache", "3").exit_code == 2


def test_httrack_cache_0_lists_no_unreached_file(crawl):
    """-C0 opens no new.lst, so HTTrack's purge, which the list stands for, does not run
    (htscore.c:2147)."""
    out, ms = crawl
    ms.side_effect = lambda u, o, *a, **k: _crawled(o, names=("index.html", "a.html", "b.html"))
    assert run(out, "--downloader", "httrack").exit_code == 0
    ms.side_effect = lambda u, o, *a, **k: _updated(o, written=("index.html", "a.html"), kept=())
    res = run(out, "--downloader", "httrack", "--cache", "0")
    assert res.exit_code == 0, res.output
    assert "Not reached" not in res.output


def test_httrack_headless_without_chromium_is_a_one_line_error(ht, monkeypatch):
    out, _, _ = ht
    api = MagicMock()
    api.sync_playwright.return_value.__enter__.return_value.chromium.launch.side_effect = \
        Exception("BrowserType.launch: Executable doesn't exist at /x/chrome\n+----+")
    monkeypatch.setitem(sys.modules, "playwright", MagicMock())
    monkeypatch.setitem(sys.modules, "playwright.sync_api", api)
    res = run(out, "--downloader", "httrack", "--headless")
    assert res.exit_code == 1
    assert "dograpper doctor --install" in res.output
    assert "Traceback" not in res.output and "+----+" not in res.output


def test_httrack_headless_runs_playwright_under_the_policy(ht):
    """As the wget cascade's --headless: layers 1+2 (under the profile), then the browser."""
    out, fu, _ = ht
    with patch(f"{P}.run_playwright_crawl", side_effect=_rendered(out)) as pw:
        res = run(out, "--downloader", "httrack", "--headless")
    assert res.exit_code == 0, res.output
    fu.assert_not_called()  # no engine fetch before the browser
    kw = pw.call_args.kwargs
    assert kw["seed_urls"] == URLS
    assert kw["navigator"].fetcher is FakeFetcher.instances[0]
    assert "Files downloaded: 1" in res.output


def test_httrack_spa_falls_back_to_playwright_with_the_discovered_seeds(ht):
    out, fu, _ = ht
    engine = []
    fu.side_effect = lambda urls, o, *a, **k: engine.append(_res(o)) or engine[-1]
    with patch(f"{P}.is_spa", return_value=True), \
         patch(f"{P}.run_playwright_crawl", side_effect=_rendered(out, ("p0.html",))) as pw:
        res = run(out, "--downloader", "httrack")
    assert res.exit_code == 0, res.output
    assert pw.call_args.kwargs["seed_urls"] == URLS
    # the browser pass has its own report, under the engine's: nothing counted twice
    assert pw.call_args.kwargs["navigator"].report is not engine[0].report
    assert res.output.index("Responses:") < res.output.index("Playwright pass:")
    assert "Files downloaded: 1" in res.output  # the page the browser rendered over the shell


def test_httrack_browser_pass_reuses_what_the_engine_received(ht):
    out, fu, _ = ht
    seen = []
    fu.side_effect = lambda urls, o, *a, **k: seen.append(k["responses"]) or _res(o)
    with patch(f"{P}.is_spa", return_value=True), \
         patch(f"{P}.run_playwright_crawl", side_effect=_rendered(out, ("p0.html",))) as pw:
        assert run(out, "--downloader", "httrack").exit_code == 0
    assert seen[0] is not None and pw.call_args.kwargs["navigator"]._reuse is seen[0]


def test_httrack_headless_has_no_engine_responses_to_reuse(ht):
    out, fu, _ = ht
    with patch(f"{P}.run_playwright_crawl", side_effect=_rendered(out)) as pw:
        assert run(out, "--downloader", "httrack", "--headless").exit_code == 0
    assert pw.call_args.kwargs["navigator"]._reuse is None


@pytest.mark.parametrize("flag", ["--cache=1", "--updatehack", "--do-not-recatch", "--changes"])
def test_httrack_update_flags_under_headless_are_usage_errors(ht, flag):
    """They steer the engine's revalidation; under --headless no page is revalidated."""
    out, _, _ = ht
    with patch(f"{P}.run_playwright_crawl") as pw:
        res = run(out, "--downloader", "httrack", "--headless", flag)
    assert res.exit_code == 2
    assert flag.split("=")[0] in res.output and "--headless" in res.output
    pw.assert_not_called()


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


def test_httrack_script_scans_on_by_default_and_turned_off_by_flags(ht, tmp_path):
    # HTTrack -j (parsejava = HTSPARSE_DEFAULT) and -%P (parseall) default on
    # (htslib.c:5406, 5425); --no-parse-scripts is -j4, --no-extended-parsing -%P0 (or -j8)
    out, fu, _ = ht
    res = run(out, "--downloader", "httrack")
    assert res.exit_code == 0, res.output
    policy = fu.call_args.args[2]
    assert (policy.parse_scripts, policy.extended_parsing) == (True, True)
    cfg = _config(tmp_path, downloader="httrack", **{"no-parse-scripts": False})
    res = run(out, "--no-parse-scripts", "--no-extended-parsing", config=cfg)
    assert res.exit_code == 0, res.output
    policy = fu.call_args.args[2]
    assert (policy.parse_scripts, policy.extended_parsing) == (False, False)  # CLI wins


def test_httrack_invalid_config_value_names_option_and_source(ht, tmp_path):
    out, _, _ = ht
    res = run(out, config=_config(tmp_path, downloader="httrack", connections=0))
    assert res.exit_code == 2
    assert "--connections" in res.output
    assert ".dograpper.json" in res.output


def test_httrack_non_numeric_config_value_is_usage_error(ht, tmp_path):
    out, _, _ = ht
    res = run(out, config=_config(tmp_path, downloader="httrack", connections="four"))
    assert res.exit_code == 2
    assert "--connections" in res.output
    assert ".dograpper.json" in res.output
    assert "Traceback" not in res.output


@pytest.mark.parametrize("key, value, attr, expected", [
    ("no-robots", "false", "obey_robots", True),
    ("no-robots", "true", "obey_robots", False),
    ("connections", "3", "connections", 3),          # what `--connections 3` receives
    ("max-conn-rate", 2, "max_conn_rate", 2.0),
    ("no-parse-scripts", True, "parse_scripts", False),
    ("no-extended-parsing", "true", "extended_parsing", False),
    ("no-extended-parsing", "false", "extended_parsing", True),
    ("cache", "1", "cache", 1),
    ("updatehack", "true", "updatehack", True),
    ("do-not-recatch", True, "do_not_recatch", True),
    ("changes", "true", "changes", True),
    ("cache", 0, "cache", 0),
])
def test_httrack_config_value_converted_like_cli(ht, tmp_path, key, value, attr, expected):
    out, fu, _ = ht
    res = run(out, config=_config(tmp_path, downloader="httrack", **{key: value}))
    assert res.exit_code == 0, res.output
    assert getattr(fu.call_args.args[2], attr) == expected


def test_httrack_config_string_false_keeps_security_limits(ht, tmp_path):
    out, fu, _ = ht
    cfg = _config(tmp_path, downloader="httrack", connections=20,
                  **{"disable-security-limits": "false"})
    res = run(out, config=cfg)
    assert res.exit_code == 0, res.output
    assert fu.call_args.args[2].connections == 8  # still clamped


@pytest.mark.parametrize("key, value", [
    ("max-links", 2.0), ("retries", 1.5), ("retries", True), ("retries", -1),
    ("max-retry-after", -5), ("timeout", 0), ("no-robots", "maybe"), ("connections", None),
    ("cache", 3), ("cache", "update"),
])
def test_httrack_bad_config_value_fails_like_cli(ht, tmp_path, key, value):
    out, fu, _ = ht
    res = run(out, config=_config(tmp_path, downloader="httrack", **{key: value}))
    assert res.exit_code == 2, res.output
    assert f"'--{key}' (from .dograpper.json)" in res.output
    assert "Traceback" not in res.output
    fu.assert_not_called()


def test_wget_accepts_config_profile_values_equal_to_default(tmp_path):
    out = str(tmp_path / "o")
    cfg = _config(tmp_path, **{"no-robots": "false", "retries": "2"})
    with patch("dograpper.commands.download.fetch_llms_txt", return_value=URLS), \
         patch("dograpper.commands.download.run_wget_urls") as wu, \
         patch("dograpper.commands.download.is_spa", return_value=False):
        wu.return_value = WgetResult(True, out, [], [], 0)
        res = run(out, config=cfg)
    assert res.exit_code == 0, res.output


def test_httrack_negative_delay_names_cli_option(ht):
    out, _, _ = ht
    res = run(out, "--downloader", "httrack", "--delay", "-1")
    assert res.exit_code == 2
    assert "--delay" in res.output
    assert "delay_ms" not in res.output


def test_invalid_cli_bound_is_usage_error(tmp_path):
    res = run(str(tmp_path / "o"), "--connections", "0")
    assert res.exit_code == 2


def _no_crawl(*a, **k):
    """mirror_site stub for discovery tests: the start URL failed."""
    return HttrackResult(False, [], 0, RunReport(), True)


def _fetcher_with(rules, status=200, **result_kw):
    calls = []

    class F:
        def get(self, url, *, kind, referer=None):
            calls.append((url, kind, referer))
            return FetchResult(url, status=status, body=b"x", **result_kw)

        def robots_for(self, origin):
            return rules

    return F(), calls


def test_discovery_checks_robots_before_fetching_and_uses_robots_kind(tmp_path):
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

    with patch(f"{P}.Fetcher", lambda policy, cookies=None: f), patch(f"{P}.warn_if_old_openssl"), \
         patch("dograpper.commands.download.fetch_llms_txt", side_effect=llms), \
         patch("dograpper.commands.download.fetch_sitemap", side_effect=sm), \
         patch(f"{P}.mirror_site", side_effect=_no_crawl) as ms:
        res = run(str(tmp_path / "o"), "--downloader", "httrack")
    assert res.exit_code == 1 and ms.called  # nothing discovered: the crawl (stubbed) ran
    assert seen["ok"] == b"x" and seen["blocked"] is None
    assert seen["extra"] == ("http://example.com/sm.xml",)
    assert [u for u, _, _ in calls] == ["http://example.com/llms.txt"]  # no GET for /blocked
    assert all(k == "robots" and r is None for _, k, r in calls)


def test_discovery_warns_on_robots_blocked_challenged_and_redirected(caplog):
    blocked = RobotsRules((("disallow", "/"),), None, ())
    probes = {
        "blocked": (blocked, 200, {}),
        "challenged": (NO_RULES, 403, {"challenged": True}),
        "redirected": (NO_RULES, 301, {"location": "http://other.example/x"}),  # off-host
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
            _discover_urls("http://example.com", 0, discovery_fetch(f))
        assert any(r.levelno == logging.WARNING and name[:7] in r.getMessage()
                   for r in caplog.records), (name, caplog.records)


def test_discovery_follows_same_host_redirects_with_robots_per_hop():
    rules = RobotsRules((("disallow", "/private"),), None, ())
    script = {
        # scheme, port and hostname case may change on the same host
        "http://example.com/sitemap.xml": dict(status=301,
                                               location="https://EXAMPLE.com:8443/sm.xml"),
        "https://EXAMPLE.com:8443/sm.xml": dict(status=200, body=b"<urlset/>"),
        "http://example.com/a": dict(status=302, location="/private/b"),
        "http://example.com/off": dict(status=307, location="http://other.example/x"),
        "http://example.com/bad": dict(status=308, location="http://[bad/x"),
        "http://example.com/loop": dict(status=301, location="/loop"),
    }
    gets, origins = [], []

    class F:
        def get(self, url, *, kind, referer=None):
            gets.append(url)
            return FetchResult(url, **script[url])

        def robots_for(self, origin):
            origins.append(origin)
            return rules

    fetch = discovery_fetch(F())
    assert fetch("http://example.com/sitemap.xml") == b"<urlset/>"
    assert "https://EXAMPLE.com:8443" in origins           # robots checked on the new origin
    assert fetch("http://example.com/a") is None           # hop disallowed by robots.txt
    assert fetch("http://example.com/off") is None         # cross-host: not followed
    assert fetch("http://example.com/bad") is None         # malformed Location: no crash
    assert fetch("http://example.com/loop") is None        # bounded
    assert "http://example.com/private/b" not in gets
    assert "http://other.example/x" not in gets
    assert gets.count("http://example.com/loop") == 6      # 5 redirects at most


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


def test_escape_sequence_in_robots_sitemap_line_never_reaches_output(tmp_path):
    rules = parse_robots("User-agent: *\n"
                         "Sitemap: http://evil.invalid/\x1b[7mINJECTED\x1b[0m.xml\n"
                         "Sitemap: http://example.com/\x1b[2Jsm.xml\n")
    f, calls = _fetcher_with(rules, status=404)
    with patch(f"{P}.Fetcher", lambda policy, cookies=None: f), patch(f"{P}.warn_if_old_openssl"), \
         patch(f"{P}.mirror_site", side_effect=_no_crawl) as ms:
        res = run(str(tmp_path / "o"), "--downloader", "httrack")
    assert res.exit_code == 1 and ms.called  # nothing discovered: the crawl (stubbed) ran
    assert "rejecting cross-host candidate" in res.output  # the hint was logged...
    assert "\x1b" not in res.output                         # ...neutralized
    assert "http://example.com/\x1b[2Jsm.xml" in [u for u, _, _ in calls]


# --- #136 --header (repeatable request header, httrack and fire-engine) ---

def test_header_with_wget_is_usage_error(tmp_path):
    res = run(str(tmp_path / "o"), "--header", "X-Test: 1")
    assert res.exit_code == 2
    assert "--header requires --downloader httrack or fire-engine" in res.output


def test_header_in_config_with_wget_is_usage_error(tmp_path):
    res = run(str(tmp_path / "o"), config=_config(tmp_path, header=["X-Test: 1"]))
    assert res.exit_code == 2
    assert "--header requires --downloader httrack or fire-engine" in res.output


@pytest.mark.parametrize("header,named", [
    ("X-Token s3cret", "#1"),            # no colon
    ("Bad Name: s3cret", "#1"),          # the name is not an RFC 9110 token
    (": s3cret", "#1"),
    ("X-Token: s3\rcret", "X-Token"),
    ("X-Token: s3\ncret", "X-Token"),
    ("X-Token: s3\x00cret", "X-Token"),
    ("Host: s3cret.example", "Host"),
    ("content-length: s3cret", "content-length"),
    ("Transfer-Encoding: s3cret", "Transfer-Encoding"),
    ("CONNECTION: s3cret", "CONNECTION"),
])
def test_invalid_header_is_usage_error_naming_it_never_its_value(ht, header, named):
    out, fu, _ = ht
    res = run(out, "--downloader", "httrack", "--header", "X-Ok: 1", "--header", header)
    assert res.exit_code == 2
    assert f"--header {named.replace('#1', '#2')}" in res.output
    assert "s3" not in res.output and "cret" not in res.output
    fu.assert_not_called()


def test_invalid_header_in_config_says_so(ht, tmp_path):
    out, fu, _ = ht
    cfg = _config(tmp_path, downloader="httrack", header=["X-Token: s3\ncret"])
    res = run(out, config=cfg)
    assert res.exit_code == 2
    assert "--header X-Token" in res.output and "(from .dograpper.json)" in res.output
    assert "cret" not in res.output


def test_header_config_value_must_be_a_list_of_strings(ht, tmp_path):
    out, _, _ = ht
    res = run(out, config=_config(tmp_path, downloader="httrack", header="X-Test: 1"))
    assert res.exit_code == 2
    assert "--header (from .dograpper.json) must be a list" in res.output


def test_headers_reach_the_policy_and_the_cli_list_replaces_the_config_one(ht, tmp_path):
    out, fu, _ = ht
    cfg = _config(tmp_path, downloader="httrack", header=["X-Config: 1"])
    assert run(out, config=cfg).exit_code == 0
    assert fu.call_args.args[2].headers == (("X-Config", "1"),)  # config beats default
    res = run(out, "--header", "X-Cli: 2", "--header", "X-Two:  b ", config=cfg)
    assert res.exit_code == 0, res.output
    assert fu.call_args.args[2].headers == (("X-Cli", "2"), ("X-Two", "b"))  # CLI wins


def test_header_user_agent_is_the_user_agent(ht):
    out, fu, _ = ht
    res = run(out, "--downloader", "httrack", "--header", "user-agent: Bot/1")
    assert res.exit_code == 0, res.output
    policy = fu.call_args.args[2]
    assert (policy.user_agent, policy.headers) == ("Bot/1", ())


@pytest.mark.parametrize("config", [False, True])
def test_user_agent_given_two_ways_is_usage_error(ht, tmp_path, config):
    out, fu, _ = ht
    args = ["--header", "User-Agent: B/2"]
    if config:
        res = run(out, *args, config=_config(tmp_path, downloader="httrack", **{"user-agent": "A/1"}))
    else:
        res = run(out, "--downloader", "httrack", "--user-agent", "A/1", *args)
    assert res.exit_code == 2
    assert "--user-agent and --header 'User-Agent: …' both set the User-Agent" in res.output
    assert "A/1" not in res.output and "B/2" not in res.output
    fu.assert_not_called()


@pytest.mark.parametrize("given", [["--user-agent", "", "--header", "User-Agent: B/2"],
                                   ["--user-agent", "A/1", "--header", "User-Agent:"],
                                   ["--user-agent", "", "--header", "User-Agent:"]])
def test_an_empty_user_agent_still_counts_as_given(ht, given):
    """#183: an empty User-Agent sends none, but it is given: two sources stay exit 2."""
    out, fu, _ = ht
    res = run(out, "--downloader", "httrack", *given)
    assert res.exit_code == 2
    assert "--user-agent and --header 'User-Agent: …' both set the User-Agent" in res.output
    fu.assert_not_called()


@pytest.mark.parametrize("config", [False, True])
@pytest.mark.parametrize("bad", ["Bot/1\r\nX-Injected: s3cret", "Bot/1\nX-Injected: s3cret",
                                 "Bot/1\x00s3cret"])
def test_user_agent_with_cr_lf_or_nul_is_usage_error(ht, tmp_path, config, bad):
    """The --user-agent value goes on the wire like a --header one, so the same check
    guards it: a line break would put a header line of its own on the wire."""
    out, fu, _ = ht
    if config:
        res = run(out, config=_config(tmp_path, downloader="httrack", **{"user-agent": bad}))
    else:
        res = run(out, "--downloader", "httrack", "--user-agent", bad)
    assert res.exit_code == 2
    assert "--user-agent: User-Agent has a CR, LF or NUL character in its value" in res.output
    assert ("(from .dograpper.json)" in res.output) is config
    assert "s3cret" not in res.output and "Bot/1" not in res.output
    fu.assert_not_called()


@pytest.mark.parametrize("first,second,named", [
    ("X-Test: 1", "x-test: 2", "x-test"),         # names compare without case
    ("User-Agent: A/1", "User-Agent: B/2", "User-Agent"),
])
def test_header_name_given_twice_is_usage_error(ht, first, second, named):
    """No silent last-one-wins: two lines for one name are refused, naming it."""
    out, fu, _ = ht
    res = run(out, "--downloader", "httrack", "--header", first, "--header", second)
    assert res.exit_code == 2
    assert f"--header {named} is given more than once" in res.output
    assert "A/1" not in res.output and "B/2" not in res.output
    fu.assert_not_called()


# --- #172: the browser pass rewrites the engine's files, so --changes writes no report ---

def _with_changes(out, *a, **k):
    res = _res(out)
    res.changes = ('{"report": "engine shell"}', "Changes: 1 new")
    return res


def test_changes_run_that_falls_back_to_the_browser_writes_no_report(ht):
    out, fu, _ = ht
    fu.side_effect = lambda urls, o, *a, **k: _with_changes(o)
    stale = os.path.join(out, "hts-changes.json")
    with open(stale, "w") as fh:
        fh.write("{}")
    with patch(f"{P}.is_spa", return_value=True), \
         patch(f"{P}.run_playwright_crawl", side_effect=_rendered(out, ("p0.html",))):
        res = run(out, "--downloader", "httrack", "--changes")
    assert res.exit_code == 0, res.output
    assert not os.path.exists(stale)
    assert "Change report skipped: the browser pass rewrote the files" in res.output
    assert "Changes: 1 new" not in res.output


def test_changes_run_that_needs_no_browser_still_writes_the_report(ht):
    out, fu, _ = ht
    fu.side_effect = lambda urls, o, *a, **k: _with_changes(o)
    res = run(out, "--downloader", "httrack", "--changes")
    assert res.exit_code == 0, res.output
    assert os.path.exists(os.path.join(out, "hts-changes.json"))
    assert "Changes: 1 new" in res.output
