"""Tests for the init wizard: preset generation, overwrite guard, CLI modes."""

import json
import os

import pytest
from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.commands.init import build_preset_config, TARGETS


# ---------------------------------------------------------------------------
# build_preset_config
# ---------------------------------------------------------------------------

def test_targets_registry_contains_expected_presets():
    assert set(TARGETS) == {"notebooklm", "rag", "claude-project"}


def test_preset_notebooklm_config():
    config = build_preset_config("notebooklm")
    pack = config["pack"]
    assert pack["bundle"] == "notebooklm"
    assert pack["max-chunks"] == 50
    assert pack["max-words-per-chunk"] <= 500000
    assert pack["strategy"] == "semantic"
    assert pack["format"] == "md"
    assert pack["context-header"] is True
    assert pack["score"] is True


def test_preset_rag_config():
    config = build_preset_config("rag")
    pack = config["pack"]
    assert pack["format"] == "jsonl"
    assert pack["context-header"] is True
    assert pack["cross-refs"] is True
    assert pack["score"] is True


def test_preset_claude_project_config():
    config = build_preset_config("claude-project")
    pack = config["pack"]
    assert pack["format"] == "md"
    assert pack["context-header"] is True
    assert pack["max-words-per-chunk"] <= 200000


def test_preset_unknown_target_raises():
    with pytest.raises(KeyError):
        build_preset_config("does-not-exist")


def test_presets_never_set_output():
    # `pack --output` is a required CLI flag; a config value would be dead.
    for target in TARGETS:
        assert "output" not in build_preset_config(target).get("pack", {})


def test_presets_include_download_section():
    for target in TARGETS:
        config = build_preset_config(target)
        assert "download" in config
        assert config["download"]["depth"] >= 1


# ---------------------------------------------------------------------------
# CLI — non-interactive mode
# ---------------------------------------------------------------------------

def test_init_non_interactive_creates_config():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init", "--target", "notebooklm", "--yes"])
        assert result.exit_code == 0
        assert os.path.exists(".dograpper.json")
        with open(".dograpper.json", encoding="utf-8") as f:
            config = json.load(f)
        assert config["pack"]["bundle"] == "notebooklm"


def test_init_non_interactive_requires_target():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init", "--yes"])
        assert result.exit_code != 0
        assert "--target" in result.output


def test_init_invalid_target_rejected():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init", "--target", "bogus", "--yes"])
        assert result.exit_code != 0


def test_init_refuses_overwrite_without_force():
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open(".dograpper.json", "w", encoding="utf-8") as f:
            f.write('{"pack": {"strategy": "size"}}')
        result = runner.invoke(cli, ["init", "--target", "rag", "--yes"])
        assert result.exit_code != 0
        # Existing file must be untouched
        with open(".dograpper.json", encoding="utf-8") as f:
            assert json.load(f)["pack"]["strategy"] == "size"


def test_init_force_overwrites():
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open(".dograpper.json", "w", encoding="utf-8") as f:
            f.write('{"pack": {"strategy": "size"}}')
        result = runner.invoke(cli, ["init", "--target", "rag", "--yes", "--force"])
        assert result.exit_code == 0
        with open(".dograpper.json", encoding="utf-8") as f:
            assert json.load(f)["pack"]["format"] == "jsonl"


def test_init_custom_output_path_hints_config_flag():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli, ["init", "--target", "rag", "--yes", "-o", "custom.json"])
        assert result.exit_code == 0
        assert os.path.exists("custom.json")
        with open("custom.json", encoding="utf-8") as f:
            assert json.load(f)["pack"]["format"] == "jsonl"
        # A non-default path is only consumed via --config; the user is told
        assert "--config custom.json" in result.output


def test_init_output_in_nonexistent_subdirectory():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli, ["init", "--target", "rag", "--yes", "-o", "sub/dir/cfg.json"])
        assert result.exit_code == 0, result.output
        assert os.path.exists("sub/dir/cfg.json")


def test_init_defaults_to_global_config_path():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli, ["--config", "custom.json", "init", "--target", "rag", "--yes"])
        assert result.exit_code == 0, result.output
        assert os.path.exists("custom.json")
        assert not os.path.exists(".dograpper.json")


def test_preset_keys_match_real_command_params():
    # Guards against silent-ignore drift: every generated key must map to a
    # real click parameter of the corresponding command (config_loader
    # normalizes hyphens to underscores).
    from dograpper.commands.pack import pack as pack_cmd
    from dograpper.commands.download import download as download_cmd

    known = {
        "pack": {p.name for p in pack_cmd.params},
        "download": {p.name for p in download_cmd.params},
    }
    for target in TARGETS:
        config = build_preset_config(target)
        for section, keys in config.items():
            assert section in known, f"{target}: unknown section {section}"
            for key in keys:
                param = key.replace("-", "_")
                assert param in known[section], (
                    f"{target}: {section}.{key} does not match any "
                    f"{section} CLI parameter")


# ---------------------------------------------------------------------------
# CLI — interactive mode
# ---------------------------------------------------------------------------

def test_init_interactive_flow_creates_config():
    runner = CliRunner()
    with runner.isolated_filesystem():
        # target choice "rag", then confirm write
        result = runner.invoke(cli, ["init"], input="rag\ny\n")
        assert result.exit_code == 0
        assert os.path.exists(".dograpper.json")
        with open(".dograpper.json", encoding="utf-8") as f:
            assert json.load(f)["pack"]["format"] == "jsonl"


def test_init_interactive_shows_preview_before_confirm():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init"], input="notebooklm\ny\n")
        assert result.exit_code == 0
        # The generated JSON is previewed before the confirm prompt
        assert '"bundle": "notebooklm"' in result.output


def test_init_interactive_abort_writes_nothing():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init"], input="rag\nn\n")
        assert not os.path.exists(".dograpper.json")
        assert result.exit_code != 0


def test_init_interactive_eof_at_target_prompt_writes_nothing():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init"], input="")
        assert result.exit_code != 0
        assert not os.path.exists(".dograpper.json")


def test_init_interactive_overwrite_confirmed():
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open(".dograpper.json", "w", encoding="utf-8") as f:
            f.write('{"pack": {"strategy": "size"}}')
        # overwrite? y → target rag → write? y
        result = runner.invoke(cli, ["init"], input="y\nrag\ny\n")
        assert result.exit_code == 0, result.output
        with open(".dograpper.json", encoding="utf-8") as f:
            assert json.load(f)["pack"]["format"] == "jsonl"


def test_init_interactive_overwrite_declined_keeps_file():
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open(".dograpper.json", "w", encoding="utf-8") as f:
            f.write('{"pack": {"strategy": "size"}}')
        result = runner.invoke(cli, ["init"], input="n\n")
        assert result.exit_code != 0
        with open(".dograpper.json", encoding="utf-8") as f:
            assert json.load(f)["pack"]["strategy"] == "size"


# ---------------------------------------------------------------------------
# Integration — generated config drives pack via config precedence
# ---------------------------------------------------------------------------

def test_generated_config_is_consumed_by_pack():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init", "--target", "rag", "--yes"])
        assert result.exit_code == 0

        os.makedirs("docs", exist_ok=True)
        with open("docs/page.html", "w", encoding="utf-8") as f:
            f.write("<html><body><main><h1>Title</h1>"
                    "<p>Some documentation content here.</p></main></body></html>")

        result = runner.invoke(cli, ["pack", "docs", "-o", "chunks"])
        assert result.exit_code == 0, result.output
        # rag preset sets format jsonl via config precedence
        files = os.listdir("chunks")
        assert any(f.endswith(".jsonl") for f in files), files


def test_explicit_cli_flag_still_beats_generated_config():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init", "--target", "rag", "--yes"])
        assert result.exit_code == 0

        os.makedirs("docs", exist_ok=True)
        with open("docs/page.html", "w", encoding="utf-8") as f:
            f.write("<html><body><main><h1>Title</h1>"
                    "<p>Some documentation content here.</p></main></body></html>")

        # Precedence: explicit CLI flag > generated JSON (format jsonl)
        result = runner.invoke(
            cli, ["pack", "docs", "-o", "chunks", "--format", "md"])
        assert result.exit_code == 0, result.output
        files = os.listdir("chunks")
        assert any(f.endswith(".md") for f in files), files
        assert not any(f.endswith(".jsonl") for f in files), files
