"""Integration tests for the 4-layer download cascade.

Scenarios (v2 plan § I test plan):
  1. layer-1 (llms.txt) wins → run_wget_urls is called, run_wget_mirror is not
  2. layer-2 (sitemap) wins → run_wget_urls called with sitemap URLs
  3. layer-3 (wget --mirror) wins when layers 1+2 come up empty
  4. layer-4 (playwright) fallback on SPA after layer 3
  5. layer-1 below threshold falls through to layer 2
  6. all layers fail gracefully (headless with 0 URLs → direct playwright)
"""

import json
import os
import shutil
import tempfile
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.commands.download import (
    MIN_URLS_TO_CONSIDER_DISCOVERED,
    download,
)
from dograpper.lib.playwright_crawl import CrawlResult
from dograpper.lib.wget_mirror import WgetResult
from dograpper.utils.dep_resolver import resolve_wget


def _make_outdir(d, files):
    for rel in files:
        full = os.path.join(d, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, "w", encoding="utf-8") as f:
            f.write("<html><body><p>" + "A" * 300 + "</p></body></html>")
    return [os.path.join(d, r) for r in files]


def test_cascade_layer1_llms_txt_wins():
    runner = CliRunner()
    discovered = [f"http://example.com/p{i}" for i in range(5)]

    with tempfile.TemporaryDirectory() as d:
        files = _make_outdir(d, [f"example.com/p{i}.html" for i in range(5)])
        with patch("dograpper.commands.download.fetch_llms_txt", return_value=discovered), \
             patch("dograpper.commands.download.fetch_sitemap") as mock_sitemap, \
             patch("dograpper.commands.download.run_wget_urls") as mock_wget_urls, \
             patch("dograpper.commands.download.run_wget_mirror") as mock_wget_mirror, \
             patch("dograpper.commands.download.run_playwright_crawl") as mock_pw, \
             patch("dograpper.commands.download.is_spa", return_value=False):

            mock_wget_urls.return_value = WgetResult(True, d, files, [], 0)
            res = runner.invoke(download, ["http://example.com", "-o", d])

            assert res.exit_code == 0, res.output
            assert mock_wget_urls.called
            mock_wget_mirror.assert_not_called()
            mock_sitemap.assert_not_called()  # layer-1 short-circuits layer-2
            mock_pw.assert_not_called()


def test_cascade_layer2_sitemap_wins_when_llms_empty():
    runner = CliRunner()
    sitemap_urls = [f"http://example.com/docs/p{i}" for i in range(4)]

    with tempfile.TemporaryDirectory() as d:
        files = _make_outdir(d, [f"example.com/docs/p{i}.html" for i in range(4)])
        with patch("dograpper.commands.download.fetch_llms_txt", return_value=[]), \
             patch("dograpper.commands.download.fetch_sitemap", return_value=sitemap_urls), \
             patch("dograpper.commands.download.run_wget_urls") as mock_wget_urls, \
             patch("dograpper.commands.download.run_wget_mirror") as mock_wget_mirror, \
             patch("dograpper.commands.download.is_spa", return_value=False):

            mock_wget_urls.return_value = WgetResult(True, d, files, [], 0)
            res = runner.invoke(download, ["http://example.com", "-o", d])

            assert res.exit_code == 0, res.output
            assert mock_wget_urls.called
            passed_urls = mock_wget_urls.call_args[0][0]
            assert set(passed_urls) == set(sitemap_urls)
            mock_wget_mirror.assert_not_called()


def test_cascade_layer3_wget_mirror_when_layers12_empty():
    runner = CliRunner()

    with tempfile.TemporaryDirectory() as d:
        files = _make_outdir(d, [
            "example.com/index.html",
            "example.com/a.html",
            "example.com/b.html",
        ])
        with patch("dograpper.commands.download.fetch_llms_txt", return_value=[]), \
             patch("dograpper.commands.download.fetch_sitemap", return_value=[]), \
             patch("dograpper.commands.download.run_wget_urls") as mock_wget_urls, \
             patch("dograpper.commands.download.run_wget_mirror") as mock_wget_mirror, \
             patch("dograpper.commands.download.run_playwright_crawl") as mock_pw, \
             patch("dograpper.commands.download.is_spa", return_value=False):

            mock_wget_mirror.return_value = WgetResult(True, d, files, [], 0)
            res = runner.invoke(download, ["http://example.com", "-o", d])

            assert res.exit_code == 0, res.output
            mock_wget_urls.assert_not_called()
            assert mock_wget_mirror.called
            mock_pw.assert_not_called()


def test_cascade_layer4_playwright_fallback_after_mirror_spa(caplog):
    """Layer 3 succeeds but is_spa is True → layer 4 playwright kicks in."""
    import logging
    caplog.set_level(logging.INFO)

    runner = CliRunner()
    with tempfile.TemporaryDirectory() as d:
        mirror_files = _make_outdir(d, ["example.com/index.html"])
        pw_files = _make_outdir(d, ["example.com/fresh.html"])
        with patch("dograpper.commands.download.fetch_llms_txt", return_value=[]), \
             patch("dograpper.commands.download.fetch_sitemap", return_value=[]), \
             patch("dograpper.commands.download.run_wget_mirror") as mock_wget_mirror, \
             patch("dograpper.commands.download.run_playwright_crawl") as mock_pw, \
             patch("dograpper.commands.download.is_spa", return_value=True):

            mock_wget_mirror.return_value = WgetResult(True, d, mirror_files, [], 0)
            mock_pw.return_value = CrawlResult(True, d, pw_files, [], 0)
            res = runner.invoke(download, ["http://example.com", "-o", d])

            assert res.exit_code == 0, res.output
            assert mock_pw.called
            assert "SPA detected, falling back to playwright" in caplog.text


def test_cascade_layer3_shallow_mirror_forces_playwright(caplog):
    """wget --mirror producing <=1 HTML → force playwright.

    Covers the Mintlify-class case where is_spa() misses a lone SPA shell
    (total_files < SMALL_SAMPLE_N with only 1 file, no standard SPA id,
    but recursion obviously failed to follow any link).
    """
    import logging
    caplog.set_level(logging.INFO)

    runner = CliRunner()
    with tempfile.TemporaryDirectory() as d:
        mirror_files = _make_outdir(d, ["example.com/index.html"])
        pw_files = _make_outdir(
            d, [f"example.com/p{i}.html" for i in range(5)]
        )
        with patch("dograpper.commands.download.fetch_llms_txt", return_value=[]), \
             patch("dograpper.commands.download.fetch_sitemap", return_value=[]), \
             patch("dograpper.commands.download.run_wget_mirror") as mock_wget_mirror, \
             patch("dograpper.commands.download.run_playwright_crawl") as mock_pw, \
             patch("dograpper.commands.download.is_spa", return_value=False):

            mock_wget_mirror.return_value = WgetResult(True, d, mirror_files, [], 0)
            mock_pw.return_value = CrawlResult(True, d, pw_files, [], 0)
            res = runner.invoke(download, ["http://example.com", "-o", d])

            assert res.exit_code == 0, res.output
            assert mock_pw.called, "playwright must rescue the shallow mirror"
            assert "yielded only 1 HTML" in caplog.text


def test_cascade_layer1_below_threshold_falls_through():
    """2-URL llms.txt stub below MIN_URLS must fall through to layer 2."""
    assert MIN_URLS_TO_CONSIDER_DISCOVERED >= 3  # contract

    runner = CliRunner()
    stub = ["http://example.com/stub1", "http://example.com/stub2"]  # < 3
    sitemap_urls = [f"http://example.com/p{i}" for i in range(4)]

    with tempfile.TemporaryDirectory() as d:
        files = _make_outdir(d, [f"example.com/p{i}.html" for i in range(4)])
        with patch("dograpper.commands.download.fetch_llms_txt", return_value=stub), \
             patch("dograpper.commands.download.fetch_sitemap", return_value=sitemap_urls) as mock_sm, \
             patch("dograpper.commands.download.run_wget_urls") as mock_wget_urls, \
             patch("dograpper.commands.download.is_spa", return_value=False):

            mock_wget_urls.return_value = WgetResult(True, d, files, [], 0)
            res = runner.invoke(download, ["http://example.com", "-o", d])

            assert res.exit_code == 0, res.output
            assert mock_sm.called  # layer-2 actually reached
            passed_urls = mock_wget_urls.call_args[0][0]
            assert set(passed_urls) == set(sitemap_urls)


def test_cascade_headless_still_runs_layers_1_and_2():
    """Critic M-2: layers 1+2 must run regardless of --headless."""
    runner = CliRunner()
    discovered = [f"http://example.com/p{i}" for i in range(4)]

    with tempfile.TemporaryDirectory() as d:
        pw_files = _make_outdir(d, [f"example.com/p{i}.html" for i in range(4)])
        with patch("dograpper.commands.download.fetch_llms_txt", return_value=discovered) as mock_llms, \
             patch("dograpper.commands.download.fetch_sitemap") as mock_sm, \
             patch("dograpper.commands.download.run_wget_urls") as mock_wget_urls, \
             patch("dograpper.commands.download.run_wget_mirror") as mock_wget_mirror, \
             patch("dograpper.commands.download.run_playwright_crawl") as mock_pw:

            mock_pw.return_value = CrawlResult(True, d, pw_files, [], 0)
            res = runner.invoke(download, ["http://example.com", "-o", d, "--headless"])

            assert res.exit_code == 0, res.output
            mock_llms.assert_called()  # layer-1 ran even with --headless
            mock_wget_urls.assert_not_called()  # no wget when --headless
            mock_wget_mirror.assert_not_called()
            assert mock_pw.called

            call_kwargs = mock_pw.call_args.kwargs
            seed = call_kwargs.get("seed_urls")
            assert seed is not None
            assert set(seed) == set(discovered)


def test_cascade_post_wget_i_spa_falls_through_to_playwright(caplog):
    """Layer-1 "wins" but fetched pages are empty shells → playwright re-hydrates."""
    import logging
    caplog.set_level(logging.INFO)

    runner = CliRunner()
    discovered = [f"http://example.com/p{i}" for i in range(5)]

    with tempfile.TemporaryDirectory() as d:
        wget_files = _make_outdir(d, [f"example.com/p{i}.html" for i in range(5)])
        pw_files = _make_outdir(d, [f"example.com/p{i}-fresh.html" for i in range(5)])
        with patch("dograpper.commands.download.fetch_llms_txt", return_value=discovered), \
             patch("dograpper.commands.download.fetch_sitemap", return_value=[]), \
             patch("dograpper.commands.download.run_wget_urls") as mock_wget_urls, \
             patch("dograpper.commands.download.run_playwright_crawl") as mock_pw, \
             patch("dograpper.commands.download.is_spa", return_value=True):

            mock_wget_urls.return_value = WgetResult(True, d, wget_files, [], 0)
            mock_pw.return_value = CrawlResult(True, d, pw_files, [], 0)
            res = runner.invoke(download, ["http://example.com", "-o", d])

            assert res.exit_code == 0, res.output
            assert mock_pw.called
            seed = mock_pw.call_args.kwargs.get("seed_urls")
            assert set(seed) == set(discovered)
            assert "SPA detected" in caplog.text


def test_e2e_pack_delta_after_cascade_run():
    """Run the cascade end-to-end against a mocked layer-1 win, then pack the output.

    Ensures the downloaded layout remains compatible with `pack --delta`.
    """
    from dograpper.commands.pack import pack as pack_cmd

    runner = CliRunner()
    discovered = [f"http://example.com/docs/p{i}" for i in range(4)]

    with tempfile.TemporaryDirectory() as d:
        files = _make_outdir(d, [f"example.com/docs/p{i}.html" for i in range(4)])
        with patch("dograpper.commands.download.fetch_llms_txt", return_value=discovered), \
             patch("dograpper.commands.download.fetch_sitemap", return_value=[]), \
             patch("dograpper.commands.download.run_wget_urls") as mock_wget_urls, \
             patch("dograpper.commands.download.is_spa", return_value=False):

            mock_wget_urls.return_value = WgetResult(True, d, files, [], 0)
            dl_res = runner.invoke(download, ["http://example.com", "-o", d])
            assert dl_res.exit_code == 0, dl_res.output

        # Pack the output tree — should produce at least one chunk.
        with tempfile.TemporaryDirectory() as out_dir:
            pack_res = runner.invoke(pack_cmd, [d, "-o", out_dir, "--max-words-per-chunk", "5000"])
            assert pack_res.exit_code == 0, pack_res.output
            chunks = [f for f in os.listdir(out_dir) if f.endswith(".md")]
            assert len(chunks) >= 1


def test_cascade_emits_observability_log_lines(caplog):
    import logging
    caplog.set_level(logging.INFO)

    runner = CliRunner()
    with tempfile.TemporaryDirectory() as d:
        files = _make_outdir(d, ["example.com/index.html"])
        with patch("dograpper.commands.download.fetch_llms_txt", return_value=[]), \
             patch("dograpper.commands.download.fetch_sitemap", return_value=[]), \
             patch("dograpper.commands.download.run_wget_mirror") as mock_wget_mirror, \
             patch("dograpper.commands.download.is_spa", return_value=False):
            mock_wget_mirror.return_value = WgetResult(True, d, files, [], 0)
            runner.invoke(download, ["http://example.com", "-o", d])

    text = caplog.text
    assert "[cascade] layer-1 llms.txt: probing" in text
    assert "[cascade] layer-2 sitemap.xml: probing" in text
    assert "[cascade] layer-3 wget --mirror" in text


# --- --filter (#96) ---

def _filter_run(d, *args, config=None, llms=()):
    """`download` through the top-level cli, layers mocked; return (result, wget -i, wget --mirror)."""
    pre = ["--config", str(config)] if config else []
    files = _make_outdir(d, ["example.com/docs/p0.html"])
    with patch("dograpper.commands.download.fetch_llms_txt", return_value=list(llms)), \
         patch("dograpper.commands.download.fetch_sitemap", return_value=[]), \
         patch("dograpper.commands.download.run_wget_urls") as mock_wget_urls, \
         patch("dograpper.commands.download.run_wget_mirror") as mock_wget_mirror, \
         patch("dograpper.commands.download.is_spa", return_value=False):
        mock_wget_urls.return_value = WgetResult(True, d, files, [], 0)
        mock_wget_mirror.return_value = WgetResult(True, d, files * 2, [], 0)
        res = CliRunner().invoke(cli, [*pre, "download", "http://example.com/docs/", "-o", d,
                                       "--manifest", d + ".manifest.json", *args])
    return res, mock_wget_urls, mock_wget_mirror


LLMS = [f"http://example.com/docs/p{i}" for i in range(4)] + ["http://example.com/docs/old/x"]


def test_filter_scopes_discovered_urls_and_counts_them():
    with tempfile.TemporaryDirectory() as d:
        res, wget_urls, _ = _filter_run(d, "--filter", "-*/old/*", "--filter", "-*/p3",
                                        llms=LLMS)
    assert res.exit_code == 0, res.output
    assert wget_urls.call_args[0][0] == LLMS[:3]
    assert "Filtered by --filter: 2" in res.output


def test_no_filter_prints_no_filter_line():
    with tempfile.TemporaryDirectory() as d:
        res, _, _ = _filter_run(d, llms=LLMS)
    assert res.exit_code == 0, res.output
    assert "Filtered by --filter" not in res.output


def test_filter_config_key_and_cli_precedence(tmp_path):
    cfg = tmp_path / "c.json"
    cfg.write_text(json.dumps({"download": {"filter": ["-*/old/*"]}}))
    d = str(tmp_path / "o")
    os.makedirs(d)
    res, wget_urls, _ = _filter_run(d, config=cfg, llms=LLMS)
    assert res.exit_code == 0, res.output
    assert wget_urls.call_args[0][0] == LLMS[:4]           # JSON beats the default
    res, wget_urls, _ = _filter_run(d, "--filter", "-*/p0", config=cfg, llms=LLMS)
    assert res.exit_code == 0, res.output
    assert wget_urls.call_args[0][0] == LLMS[1:]            # CLI replaces the JSON list


@pytest.mark.parametrize("source, value, message", [
    ("cli", "-*[<10]", "size rules"),
    ("config", ["*.gif"], "must start with + or -"),
    ("config", "-*", "must be a list of rules"),
])
def test_filter_bad_value_is_usage_error(tmp_path, source, value, message):
    d = str(tmp_path / "o")
    os.makedirs(d)
    if source == "cli":
        res, wget_urls, _ = _filter_run(d, "--filter", value, llms=LLMS)
    else:
        cfg = tmp_path / "c.json"
        cfg.write_text(json.dumps({"download": {"filter": value}}))
        res, wget_urls, _ = _filter_run(d, config=cfg, llms=LLMS)
    assert res.exit_code == 2, res.output
    assert message in res.output
    assert ("(from .dograpper.json)" in res.output) is (source == "config")
    wget_urls.assert_not_called()


def test_filter_order_wget_cannot_express_fails_before_any_fetch():
    with tempfile.TemporaryDirectory() as d, \
         patch("dograpper.commands.download.fetch_llms_txt") as llms:
        res = CliRunner().invoke(download, ["http://example.com", "-o", d,
                                            "--manifest", d + ".m.json",
                                            "--filter", "-*Special:*", "--filter", "+*/wiki/*"])
    assert res.exit_code == 2, res.output
    assert "'+*/wiki/*' follows '-*Special:*'" in res.output
    llms.assert_not_called()


def test_filter_reaches_wget_mirror():
    with tempfile.TemporaryDirectory() as d:
        res, _, wget_mirror = _filter_run(d, "--filter", "-*/old/*")
    assert res.exit_code == 0, res.output
    assert [r[1] for r in wget_mirror.call_args.kwargs["filters"].rules] == ["*/old/*"]
    assert "Filtered by --filter: 0" in res.output


CATEGORY = "/w/index.php?title=Category:Lua_events"
TEXT = "<p>" + "Event documentation text. " * 20 + "</p>"


@pytest.mark.skipif(shutil.which(resolve_wget()) is None, reason="wget not installed")
def test_filter_mediawiki_category_members_with_real_wget(server, tmp_path):
    """#96: a category page under /w/ whose members live under /wiki/On*. With
    "-*" and "+*/wiki/On*" wget saves the seed and the members, nothing else."""
    base, script, seen = server
    html = {"content-type": "text/html"}
    links = ["/wiki/OnTick", "/wiki/OnLoad", "/wiki/Category:En", "/w/index.php?title=Special:Random"]
    script[CATEGORY] = (200, html, (
        '<html><head><link rel="stylesheet" href="/w/load.php?modules=site"></head><body>'
        + TEXT + "".join(f'<a href="{u}">{u}</a>' for u in links) + "</body></html>").encode())
    for u in links:
        script[u] = (200, html, f'<html><body>{TEXT}<a href="{u}/deeper">x</a></body></html>'.encode())
    script["/w/load.php?modules=site"] = (200, {"content-type": "text/css"}, b"body{}")
    out = tmp_path / "m"
    res = CliRunner().invoke(cli, ["download", base + CATEGORY, "-o", str(out), "-d", "1",
                                   "--manifest", str(tmp_path / "m.json"),
                                   "--filter", "-*", "--filter", "+*/wiki/On*"])
    assert res.exit_code == 0, res.output
    host = base.split("//", 1)[1]
    saved = sorted(str(p.relative_to(out / host)) for p in (out / host).rglob("*") if p.is_file())
    assert saved == ["w/index.php?title=Category:Lua_events.html",
                     "wiki/OnLoad.html", "wiki/OnTick.html"]
    assert {p for p in seen if p.startswith(("/w/", "/wiki/"))} == {
        CATEGORY, "/wiki/OnTick", "/wiki/OnLoad"}  # refused links were never requested
    assert "Filtered by --filter: 3" in res.output
