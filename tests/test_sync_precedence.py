"""Tests for config precedence across sync's ctx.invoke boundary (issue #32).

sync forwards pack/download flags via ctx.invoke, which strips click's
parameter sources. These tests pin the contract: explicit sync CLI flags
must beat .dograpper.json, which must still beat sync's own defaults.
"""

import json
import os

import click
import pytest
from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.lib.config_loader import load_config


captured_download_ctx = {}


@pytest.fixture
def stub_download(monkeypatch):
    """Replace the download command with a no-op that records the
    forwarded-explicit set visible to its config merge."""
    @click.command()
    def fake_download(**kwargs):
        ctx = click.get_current_context()
        captured_download_ctx["explicit"] = set(
            (ctx.obj or {}).get("CLI_EXPLICIT_PARAMS", ()))

    captured_download_ctx.clear()
    monkeypatch.setattr("dograpper.commands.sync._download_cmd", fake_download)
    return captured_download_ctx


def _make_docs():
    os.makedirs("docs", exist_ok=True)
    with open("docs/page.html", "w", encoding="utf-8") as f:
        f.write("<html><body><main><h1>Title</h1>"
                "<p>Some documentation content here.</p></main></body></html>")


def _write_config(pack_section):
    with open(".dograpper.json", "w", encoding="utf-8") as f:
        json.dump({"pack": pack_section}, f)


# ---------------------------------------------------------------------------
# End-to-end through sync (download stubbed)
# ---------------------------------------------------------------------------

def test_sync_explicit_flag_beats_config(stub_download):
    runner = CliRunner()
    with runner.isolated_filesystem():
        _make_docs()
        _write_config({"format": "jsonl"})
        result = runner.invoke(
            cli, ["sync", "https://docs.example.com", "-o", "docs",
                  "--format", "md"])
        assert result.exit_code == 0, result.output
        files = os.listdir("docs/chunks")
        assert any(f.endswith(".md") for f in files), files
        assert not any(f.endswith(".jsonl") for f in files), files


def test_sync_config_still_beats_sync_defaults(stub_download):
    runner = CliRunner()
    with runner.isolated_filesystem():
        _make_docs()
        _write_config({"format": "jsonl"})
        result = runner.invoke(
            cli, ["sync", "https://docs.example.com", "-o", "docs"])
        assert result.exit_code == 0, result.output
        files = os.listdir("docs/chunks")
        assert any(f.endswith(".jsonl") for f in files), files


def test_sync_delta_cannot_be_disabled_by_config(stub_download):
    runner = CliRunner()
    with runner.isolated_filesystem():
        _make_docs()
        _write_config({"delta": False})
        result = runner.invoke(
            cli, ["sync", "https://docs.example.com", "-o", "docs"])
        assert result.exit_code == 0, result.output
        # delta stays forced on: pack writes the delta manifest
        assert os.path.exists("docs/chunks/delta_manifest.json")


def test_sync_chunks_dir_not_overridden_by_config_output(stub_download):
    runner = CliRunner()
    with runner.isolated_filesystem():
        _make_docs()
        _write_config({"output": "elsewhere"})
        result = runner.invoke(
            cli, ["sync", "https://docs.example.com", "-o", "docs"])
        assert result.exit_code == 0, result.output
        assert os.path.isdir("docs/chunks")
        assert not os.path.exists("elsewhere")


def test_sync_forwards_explicit_download_flags(stub_download):
    runner = CliRunner()
    with runner.isolated_filesystem():
        _make_docs()
        result = runner.invoke(
            cli, ["sync", "https://docs.example.com", "-o", "docs", "-d", "2"])
        assert result.exit_code == 0, result.output
        assert "depth" in stub_download["explicit"]
        assert "output" in stub_download["explicit"]


def test_sync_does_not_mark_defaulted_download_flags_explicit(stub_download):
    runner = CliRunner()
    with runner.isolated_filesystem():
        _make_docs()
        result = runner.invoke(
            cli, ["sync", "https://docs.example.com", "-o", "docs"])
        assert result.exit_code == 0, result.output
        assert "depth" not in stub_download["explicit"]


def test_direct_pack_precedence_unchanged():
    # Regression guard: the fix must not disturb the direct-CLI path.
    runner = CliRunner()
    with runner.isolated_filesystem():
        _make_docs()
        _write_config({"format": "jsonl"})
        result = runner.invoke(
            cli, ["pack", "docs", "-o", "chunks", "--format", "md"])
        assert result.exit_code == 0, result.output
        files = os.listdir("chunks")
        assert any(f.endswith(".md") for f in files), files


def test_passthrough_tuples_cover_every_sync_flag():
    # Drift guard: a new sync passthrough option MUST be added to
    # _DOWNLOAD_PASSTHROUGH or _PACK_PASSTHROUGH, or issue #32 silently
    # returns for that flag.
    from dograpper.commands.sync import (
        sync, _DOWNLOAD_PASSTHROUGH, _PACK_PASSTHROUGH)

    own_params = {"url", "output", "chunks_dir", "help"}
    all_flags = {p.name for p in sync.params} - own_params
    covered = set(_DOWNLOAD_PASSTHROUGH) | set(_PACK_PASSTHROUGH)
    assert all_flags == covered, (
        f"sync flags not covered by passthrough tuples: "
        f"{sorted(all_flags - covered)}; stale tuple entries: "
        f"{sorted(covered - all_flags)}")


def test_explicit_set_cleaned_up_when_download_raises(monkeypatch):
    import click as _click

    @_click.command()
    def failing_download(**kwargs):
        raise _click.ClickException("download blew up")

    monkeypatch.setattr(
        "dograpper.commands.sync._download_cmd", failing_download)
    runner = CliRunner()
    with runner.isolated_filesystem():
        _make_docs()
        captured = {}

        result = runner.invoke(
            cli, ["sync", "https://docs.example.com", "-o", "docs"],
            obj=captured)
        assert result.exit_code != 0
        assert "CLI_EXPLICIT_PARAMS" not in captured


# ---------------------------------------------------------------------------
# Unit: config_loader honors forwarded-explicit params
# ---------------------------------------------------------------------------

def _bare_ctx(params, obj):
    ctx = click.Context(click.Command("pack"))
    ctx.params = dict(params)
    ctx.obj = obj
    return ctx


def test_load_config_forwarded_param_beats_json(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text('{"pack": {"format": "jsonl"}}', encoding="utf-8")
    ctx = _bare_ctx({"format": "md"}, {"CLI_EXPLICIT_PARAMS": {"format"}})
    merged = load_config(str(config), "pack", {"format": "md"}, ctx)
    assert merged["format"] == "md"


def test_load_config_unforwarded_param_still_takes_json(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text('{"pack": {"format": "jsonl"}}', encoding="utf-8")
    ctx = _bare_ctx({"format": "md"}, {"CLI_EXPLICIT_PARAMS": set()})
    merged = load_config(str(config), "pack", {"format": "md"}, ctx)
    assert merged["format"] == "jsonl"


def test_load_config_without_obj_unaffected(tmp_path):
    config = tmp_path / "cfg.json"
    config.write_text('{"pack": {"format": "jsonl"}}', encoding="utf-8")
    ctx = _bare_ctx({"format": "md"}, None)
    merged = load_config(str(config), "pack", {"format": "md"}, ctx)
    assert merged["format"] == "jsonl"


def test_sync_for_queries_explicit_beats_config(stub_download):
    runner = CliRunner()
    with runner.isolated_filesystem():
        _make_docs()
        with open("cli-queries.txt", "w", encoding="utf-8") as f:
            f.write("documentation content\n")
        # Config points to a missing file: if JSON won, pack would fail.
        _write_config({"for-queries": "missing.txt"})
        result = runner.invoke(
            cli, ["sync", "https://docs.example.com", "-o", "docs",
                  "--for-queries", "cli-queries.txt"])
        assert result.exit_code == 0, result.output
        assert "Query packing:" in result.output


def test_sync_for_queries_config_beats_defaults(stub_download):
    runner = CliRunner()
    with runner.isolated_filesystem():
        _make_docs()
        with open("queries.txt", "w", encoding="utf-8") as f:
            f.write("documentation content\n")
        _write_config({"for-queries": "queries.txt"})
        result = runner.invoke(
            cli, ["sync", "https://docs.example.com", "-o", "docs"])
        assert result.exit_code == 0, result.output
        assert "Query packing:" in result.output


def _sync_httrack(runner, args):
    """Run sync against the real download command with the httrack run stubbed."""
    from unittest.mock import patch
    seen = {}

    def fake_run(url, output, depth, delay, ext, headless, verbose, policy_kw,
                 from_config, discover, filters, previous=None, **session):
        seen["policy_kw"] = policy_kw
        seen["from_config"] = from_config
        seen["session"] = session
        return 0, 0, [], {}, {}

    with patch("dograpper.commands.download.run_httrack", fake_run):
        result = runner.invoke(
            cli, ["sync", "https://docs.example.com", "-o", "docs"] + args)
    return result, seen


def test_sync_httrack_precedence_cli_over_json():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _make_docs()
        with open(".dograpper.json", "w", encoding="utf-8") as f:
            json.dump({"download": {"downloader": "httrack",
                                    "connections": 2, "timeout": 30}}, f)
        result, seen = _sync_httrack(runner, ["--connections", "6"])
        assert result.exit_code == 0, result.output
        assert seen["policy_kw"]["connections"] == 6   # CLI beats JSON
        assert seen["policy_kw"]["timeout"] == 30      # JSON beats default
        assert "connections" not in seen["from_config"]
        assert "timeout" in seen["from_config"]


@pytest.mark.parametrize("config_delay, expect_label", [(None, False), (-5, True)])
def test_sync_policy_error_label_follows_value_source(config_delay, expect_label):
    runner = CliRunner()
    with runner.isolated_filesystem():
        args = ["--downloader", "httrack"]
        if config_delay is None:
            args += ["--delay", "-5"]
        else:
            with open(".dograpper.json", "w", encoding="utf-8") as f:
                json.dump({"download": {"delay": config_delay}}, f)
        result = runner.invoke(
            cli, ["sync", "https://docs.example.com", "-o", "docs"] + args)
        assert result.exit_code != 0
        assert "--delay must not be negative" in result.output
        assert ("(from .dograpper.json)" in result.output) is expect_label


def test_sync_header_cli_list_replaces_the_json_one():
    """#136: sync forwards --header; the CLI list wins over the config list (contract 6)."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        _make_docs()
        with open(".dograpper.json", "w", encoding="utf-8") as f:
            json.dump({"download": {"downloader": "httrack", "header": ["X-Json: 1"]}}, f)
        result, seen = _sync_httrack(runner, [])
        assert result.exit_code == 0, result.output
        assert seen["policy_kw"]["headers"] == (("X-Json", "1"),)
        result, seen = _sync_httrack(runner, ["--header", "X-Cli: 2"])
        assert result.exit_code == 0, result.output
        assert seen["policy_kw"]["headers"] == (("X-Cli", "2"),)
        assert "header" not in seen["from_config"]


def test_sync_forwards_cookies_from_the_cli_over_the_json():
    """#169: --cookies is an [httrack] flag sync forwards; the CLI beats the config."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        _make_docs()
        with open(".dograpper.json", "w", encoding="utf-8") as f:
            json.dump({"download": {"downloader": "httrack", "cookies": "json.txt"}}, f)
        result, seen = _sync_httrack(runner, [])
        assert result.exit_code == 0, result.output
        assert seen["session"]["cookies"] == "json.txt" and "cookies" in seen["from_config"]
        result, seen = _sync_httrack(runner, ["--cookies", "cli.txt"])
        assert result.exit_code == 0, result.output
        assert seen["session"]["cookies"] == "cli.txt"


def test_sync_forwards_no_browser_headers_into_the_policy():
    """#170: --no-browser-headers is an [httrack] flag sync forwards to the policy."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        _make_docs()
        result, seen = _sync_httrack(runner, ["--downloader", "httrack",
                                              "--no-browser-headers"])
        assert result.exit_code == 0, result.output
        assert seen["policy_kw"]["browser_headers"] is False and seen["session"] == {
            "cookies": None, "browser_login": False}


def test_sync_forwards_browser_login_from_the_json():
    """#171: --browser-login has a .dograpper.json key and sync forwards it."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        _make_docs()
        with open(".dograpper.json", "w", encoding="utf-8") as f:
            json.dump({"download": {"downloader": "httrack", "browser-login": True}}, f)
        result, seen = _sync_httrack(runner, [])
        assert result.exit_code == 0, result.output
        assert seen["session"]["browser_login"] is True
        assert seen["policy_kw"]["user_agent"] is None  # the browser's, once logged in
