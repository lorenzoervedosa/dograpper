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
    assert set(TARGETS) == {"notebooklm", "rag", "claude-project", "claude-code"}


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


def test_preset_claude_code_config():
    pack = build_preset_config("claude-code")["pack"]
    assert pack["layout"] == "page"
    assert pack["format"] == "md"
    assert pack["context-header"] is True
    assert pack["dedup"] == "off"  # dedup deletes per-page content (#89)
    # Nothing the page layout rejects (ADR-0010 point 5)
    from dograpper.commands._page_layout import CHUNK_ONLY_OPTIONS
    for key in pack:
        assert key.replace("-", "_") not in CHUNK_ONLY_OPTIONS + ("bundle", "for_queries"), key


def test_claude_project_description_names_claude_projects():
    assert "Claude Projects" in TARGETS["claude-project"]["description"]
    assert "Claude Code" in TARGETS["claude-code"]["description"]


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
        assert result.exit_code == 2
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


# ---------------------------------------------------------------------------
# claude-code target: skill skeleton (#93, ADR-0010 point 7)
# ---------------------------------------------------------------------------

def _read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_claude_code_writes_a_skill_stub_in_the_skill_dir():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(
            cli, ["init", "--target", "claude-code", "--yes", "--skill-dir", "refs/PZ Wiki_ref"])
        assert result.exit_code == 0, result.output
        assert json.loads(_read(".dograpper.json"))["pack"]["layout"] == "page"
        stub = _read("refs/PZ Wiki_ref/SKILL.md")
        assert stub.startswith("---\nname: pz-wiki-ref\ndescription: ")
        assert "[INDEX.md](INDEX.md)" in stub
        assert "grep" in stub and "pages/" in stub
        assert "dograpper pack ./docs -o 'refs/PZ Wiki_ref'" in result.output
        assert "~/.claude/skills/pz-wiki-ref" in result.output


def test_claude_code_skill_dir_defaults_to_docs_skill():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init", "--target", "claude-code", "--yes"])
        assert result.exit_code == 0, result.output
        assert _read("docs-skill/SKILL.md").startswith("---\nname: docs-skill\n")


def test_existing_skill_md_is_never_overwritten():
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("docs-skill")
        with open("docs-skill/SKILL.md", "w", encoding="utf-8") as f:
            f.write("---\nname: mine\ndescription: edited by hand\n---\n")
        result = runner.invoke(cli, ["init", "--target", "claude-code", "--yes", "--force"])
        assert result.exit_code == 0, result.output
        assert _read("docs-skill/SKILL.md") == "---\nname: mine\ndescription: edited by hand\n---\n"
        assert "kept" in result.output


def test_skill_dir_needs_the_claude_code_target():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init", "--target", "rag", "--yes", "--skill-dir", "x"])
        assert result.exit_code == 2
        assert not os.path.exists(".dograpper.json")
        assert not os.path.exists("x")


def test_other_targets_write_no_skill_stub():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init", "--target", "claude-project", "--yes"])
        assert result.exit_code == 0, result.output
        assert os.listdir(".") == [".dograpper.json"]


def test_wizard_lists_claude_code_and_writes_its_stub():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["init"], input="claude-code\ny\n")
        assert result.exit_code == 0, result.output
        assert "claude-code" in result.output.split("Target")[0]
        assert "docs-skill/SKILL.md" in result.output.split("Write to")[0]
        assert os.path.isfile("docs-skill/SKILL.md")


def test_init_help_lists_every_target():
    result = CliRunner().invoke(cli, ["init", "--help"])
    assert result.exit_code == 0
    assert "Claude Projects" in result.output and "Claude Code" in result.output
    assert "claude-code" in result.output


def test_claude_code_config_packs_into_a_skill_with_no_warning():
    runner = CliRunner()
    with runner.isolated_filesystem():
        assert runner.invoke(cli, ["init", "--target", "claude-code", "--yes"]).exit_code == 0
        stub = _read("docs-skill/SKILL.md")
        os.makedirs("docs/Modding", exist_ok=True)
        for rel in ("Modding.html", "Modding/vi.html"):
            with open(f"docs/{rel}", "w", encoding="utf-8") as f:
                f.write("<html><head><title>Modding - Wiki</title></head><body>"
                        "<main><h2>Intro</h2><p>Some documentation content.</p></main>"
                        "</body></html>")

        result = runner.invoke(cli, ["pack", "docs", "-o", "docs-skill"])
        assert result.exit_code == 0, result.output
        assert "warning" not in result.output.lower() and "\u26a0" not in result.output
        assert sorted(os.listdir("docs-skill")) == ["INDEX.md", "SKILL.md", "pages"]
        assert os.path.isfile("docs-skill/pages/Modding/vi.md")
        assert _read("docs-skill/pages/Modding.md").startswith("<!-- dograpper-context-v1\n")
        # pack never rewrites the skill stub
        assert runner.invoke(cli, ["pack", "docs", "-o", "docs-skill"]).exit_code == 0
        assert _read("docs-skill/SKILL.md") == stub
