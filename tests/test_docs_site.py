"""Drift guard for the docs site in ``site/``.

Parses the Markdown (never builds it, so Sphinx and the ``docs`` extra are not
needed) and checks it against the click tree: every command page names a real
command and renders it with the ``dograpper-options`` directive, every
``### --flag`` detail heading is an option of that command, and every ``--flag`` mentioned anywhere on the site exists.
"""

import re
from pathlib import Path

import click
import pytest

from dograpper.cli import cli

REPO_ROOT = Path(__file__).resolve().parent.parent
SITE = REPO_ROOT / "site"

# Flags of other tools that the docs cite.
FOREIGN_FLAGS = frozenset({
    "--mirror", "--no-parent", "--convert-links", "--adjust-extension",
    "--page-requisites", "--timestamping", "--continue", "--accept-regex",
    "--reject-regex",  # wget
    "--update",  # HTTrack
    "--extra",  # uv
    "--add-dir",  # Claude Code
    "--cached",  # git
})

_FLAG_RE = re.compile(r"(?<![\w-])--[a-z][a-z0-9-]*")
_HEADING_RE = re.compile(r"^### `?(--[a-z][a-z0-9-]*)", re.MULTILINE)
_DIRECTIVE_RE = re.compile(r"^```\{dograpper-options\}\s+(\S+)\s*$", re.MULTILINE)


def _flags_in(text: str) -> set[str]:
    return set(_FLAG_RE.findall(text))


def _option_flags(cmd: click.Command, ctx: click.Context) -> set[str]:
    return {
        name
        for param in cmd.get_params(ctx)
        for name in [*getattr(param, "opts", []), *getattr(param, "secondary_opts", [])]
        if name.startswith("--")
    }


def _cli_flags() -> set[str]:
    root_ctx = click.Context(cli, info_name="dograpper")
    flags = _option_flags(cli, root_ctx)
    for name, cmd in cli.commands.items():
        flags |= _option_flags(cmd, click.Context(cmd, info_name=name, parent=root_ctx))
    return flags


def _site_pages() -> list[Path]:
    build = SITE / "_build"
    return sorted(p for p in SITE.rglob("*.md") if build not in p.parents)


def _command_pages() -> dict[str, Path]:
    return {p.stem: p for p in sorted((SITE / "commands").glob("*.md"))}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


@pytest.mark.parametrize("text,expected", [
    ("see `--depth` and --no-report", {"--depth", "--no-report"}),
    ("|---|---|", set()),
    ("a — b -- c", set()),
    ("`-o` only", set()),
])
def test_flags_in(text, expected):
    assert _flags_in(text) == expected


def test_every_command_page_names_a_command():
    unknown = set(_command_pages()) - set(cli.commands)
    assert not unknown, f"site/commands pages without a click command: {sorted(unknown)}"


def test_every_command_page_renders_its_own_command():
    for stem, path in _command_pages().items():
        directives = _DIRECTIVE_RE.findall(_read(path))
        assert len(directives) == 1, f"{path}: expected exactly one dograpper-options directive"
        assert directives[0] == stem, f"{path}: directive renders {directives[0]!r}, not {stem!r}"
    global_page = SITE / "reference" / "global-options.md"
    if global_page.exists():
        assert _DIRECTIVE_RE.findall(_read(global_page)) == ["dograpper"], global_page


def test_detail_headings_are_options_of_their_command():
    root_ctx = click.Context(cli, info_name="dograpper")
    for stem, path in _command_pages().items():
        cmd = cli.commands[stem]
        valid = _option_flags(cmd, click.Context(cmd, info_name=stem, parent=root_ctx))
        extra = set(_HEADING_RE.findall(_read(path))) - valid
        assert not extra, f"{path}: headings not options of {stem}: {sorted(extra)}"
    global_page = SITE / "reference" / "global-options.md"
    if global_page.exists():
        extra = set(_HEADING_RE.findall(_read(global_page))) - _option_flags(cli, root_ctx)
        assert not extra, f"{global_page}: headings not root options: {sorted(extra)}"


def test_every_flag_on_the_site_exists():
    known = _cli_flags() | FOREIGN_FLAGS
    unknown = sorted(
        (str(p.relative_to(SITE)), flag)
        for p in _site_pages()
        for flag in _flags_in(_read(p)) - known
    )
    assert not unknown, f"flags on the site that the CLI does not have: {unknown}"
