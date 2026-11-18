"""Init subcommand — onboarding wizard that generates .dograpper.json.

Asks for (or receives via flags) the intended ingestion target and writes
a ready-to-use config reusing the existing --bundle presets. The generated
file plugs into the standard config precedence: defaults < JSON < CLI.
The claude-code target also writes a SKILL.md stub into the skill directory,
the directory `pack -o` fills; pack never touches that file (ADR-0010 point 7).
"""

import json
import os
import re
import shlex

import click

from ..lib.config_loader import is_explicit

# Preset registry: target -> (description, config dict).
# Keys use the hyphenated form consumed by config_loader.
TARGETS = {
    "notebooklm": {
        "description": "NotebookLM sources (≤50 balanced md chunks + import guide)",
        "config": {
            "download": {
                "depth": 3,
            },
            "pack": {
                "bundle": "notebooklm",
                "strategy": "semantic",
                "format": "md",
                "max-chunks": 50,
                "max-words-per-chunk": 400000,
                "context-header": True,
                "score": True,
                "dedup": "both",
            },
        },
    },
    "rag": {
        "description": "RAG pipelines (JSONL records with context headers and cross-refs)",
        "config": {
            "download": {
                "depth": 3,
            },
            "pack": {
                "strategy": "size",
                "format": "jsonl",
                "context-header": True,
                "cross-refs": True,
                "score": True,
                "dedup": "both",
            },
        },
    },
    "claude-project": {
        "description": "Claude Projects knowledge uploads (compact md chunks with context headers)",
        "config": {
            "download": {
                "depth": 3,
            },
            "pack": {
                "strategy": "semantic",
                "format": "md",
                "max-words-per-chunk": 100000,
                "context-header": True,
                "score": True,
                "dedup": "both",
            },
        },
    },
    "claude-code": {
        "description": "Claude Code skill (one md file per page plus INDEX.md, read with grep)",
        "config": {
            "download": {
                "depth": 3,
            },
            "pack": {
                "layout": "page",
                "format": "md",
                "context-header": True,
                # dedup keeps a repeated block on one page only (#89)
                "dedup": "off",
            },
        },
    },
}

SKILL_TARGET = "claude-code"
SKILL_FILENAME = "SKILL.md"

_SKILL_STUB = """---
name: {name}
description: TODO - say what these pages document and when Claude should use them (Claude reads this line to decide when to load the skill)
---

# {name}

<!-- Written once by `dograpper init`; dograpper never rewrites this file. -->

Reference pages packed by dograpper: one file per page under `pages/`, and
[INDEX.md](INDEX.md) with one line per page (title, path, word count, URL).

## When to use

TODO: the product, version and kinds of questions these pages answer.

## How to look things up

1. Find the page: `grep -i 'term' INDEX.md`, or Glob `pages/**/Name.md`.
2. Find the line: `grep -rn 'exact text' pages/` gives `file:line`.
3. Read a bounded slice: Read the file with an offset near that line and a
   limit. Pages are never split, so do not read a large page whole.

Each page starts with a `dograpper-context-v1` header holding its title,
source path and URL.
"""


def skill_name(skill_dir: str) -> str:
    """Skill name from the directory name: lowercase letters, digits and hyphens."""
    slug = re.sub(r"[^a-z0-9]+", "-", os.path.basename(os.path.normpath(skill_dir)).lower())
    return slug.strip("-")[:64].strip("-") or "docs"


def build_preset_config(target: str) -> dict:
    """Return the config dict for a target preset. Raises KeyError if unknown."""
    return json.loads(json.dumps(TARGETS[target]["config"]))


@click.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  dograpper init\n"
        "  dograpper init --target notebooklm --yes\n"
        "  dograpper init --target rag --yes -o my-config.json\n"
        "  dograpper init --target claude-code --yes --skill-dir ./wiki-skill\n"
    )
)
@click.option('--target', '-t', type=click.Choice(sorted(TARGETS)), default=None,
              help="Ingestion target preset, prompted interactively when omitted: "
                   + "; ".join(f"{name}: {TARGETS[name]['description']}"
                               for name in sorted(TARGETS)) + ".")
@click.option('--yes', '-y', is_flag=True, default=False,
              help="Non-interactive mode: write without prompting (requires --target).")
@click.option('--output', '-o', 'output_path', type=click.Path(), default=None,
              help="Where to write the generated config "
                   "[default: the global --config path, i.e. .dograpper.json].")
@click.option('--force', '-f', is_flag=True, default=False,
              help="Overwrite an existing config file (never an existing SKILL.md).")
@click.option('--skill-dir', type=click.Path(file_okay=False), default="docs-skill",
              show_default=True,
              help="claude-code target: the directory to pack into (pack -o); "
                   "a SKILL.md stub is written there unless one exists.")
@click.pass_context
def init(ctx: click.Context, target: str, yes: bool, output_path: str, force: bool,
         skill_dir: str):
    """Generate a .dograpper.json config for your ingestion target.

    Interactive by default: pick a target (notebooklm, rag, claude-project,
    claude-code), preview the generated config, confirm the write. Use
    --target with --yes for scripts.
    """
    if yes and target is None:
        raise click.UsageError("--yes requires --target (non-interactive mode).")

    ctx.ensure_object(dict)
    if output_path is None:
        output_path = ctx.obj.get('CONFIG_PATH', '.dograpper.json')

    # Overwrite guard runs before any prompt so the wizard never asks
    # questions it may discard.
    if os.path.exists(output_path) and not force:
        if yes:
            raise click.ClickException(
                f"{output_path} already exists. Use --force to overwrite.")
        click.confirm(f"{output_path} already exists. Overwrite?", abort=True)

    if target is None:
        click.echo("Available targets:")
        for name in sorted(TARGETS):
            click.echo(f"  {name:<16} {TARGETS[name]['description']}")
        target = click.prompt(
            "Target", type=click.Choice(sorted(TARGETS)), show_choices=False)
    if is_explicit(ctx, 'skill_dir') and target != SKILL_TARGET:
        raise click.UsageError(f"--skill-dir only applies to --target {SKILL_TARGET}.")

    config = build_preset_config(target)
    rendered = json.dumps(config, indent=2, ensure_ascii=False)

    click.echo(f"\nGenerated config for target '{target}':\n")
    click.echo(rendered)
    click.echo()
    skill_path = os.path.join(skill_dir, SKILL_FILENAME) if target == SKILL_TARGET else None
    if skill_path:
        state = "kept as is" if os.path.exists(skill_path) else "stub to write"
        click.echo(f"Skill file: {skill_path} ({state})\n")

    if not yes:
        click.confirm(f"Write to {output_path}?", abort=True)

    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(rendered + "\n")

    click.echo(f"Config written to {output_path}")
    if skill_path:
        if os.path.exists(skill_path):
            click.echo(f"{skill_path} already exists: kept, not overwritten")
        else:
            os.makedirs(skill_dir, exist_ok=True)
            with open(skill_path, 'x', encoding='utf-8') as f:
                f.write(_SKILL_STUB.format(name=skill_name(skill_dir)))
            click.echo(f"Skill stub written to {skill_path}: edit its description")

    pack_out = shlex.quote(skill_dir) if skill_path else "./chunks"
    config_flag = f"--config {output_path} " if output_path != ".dograpper.json" else ""
    click.echo("\nNext steps:")
    click.echo(f"  dograpper {config_flag}download <url> -o ./docs")
    click.echo(f"  dograpper {config_flag}pack ./docs -o {pack_out}")
    if skill_path:
        click.echo(f"  mkdir -p ~/.claude/skills && ln -s {shlex.quote(os.path.abspath(skill_dir))} "
                   f"~/.claude/skills/{skill_name(skill_dir)}")
