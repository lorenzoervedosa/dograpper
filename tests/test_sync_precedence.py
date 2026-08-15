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
    monkeypatch.setattr("dograpper.commands.download.download", fake_download)
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
        "dograpper.commands.download.download", failing_download)
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
