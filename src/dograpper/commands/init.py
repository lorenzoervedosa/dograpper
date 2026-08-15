"""Init subcommand — onboarding wizard that generates .dograpper.json.

Asks for (or receives via flags) the intended ingestion target and writes
a ready-to-use config reusing the existing --bundle presets. The generated
file plugs into the standard config precedence: defaults < JSON < CLI.
"""

import json
import os
import click

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
        "description": "Claude Projects knowledge (compact md chunks with context headers)",
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
}


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
    )
)
@click.option('--target', '-t', type=click.Choice(sorted(TARGETS)), default=None,
              help="Ingestion target preset. Prompted interactively when omitted.")
@click.option('--yes', '-y', is_flag=True, default=False,
              help="Non-interactive mode: write without prompting (requires --target).")
@click.option('--output', '-o', 'output_path', type=click.Path(), default=None,
              help="Where to write the generated config "
                   "[default: the global --config path, i.e. .dograpper.json].")
@click.option('--force', '-f', is_flag=True, default=False,
              help="Overwrite an existing config file.")
@click.pass_context
def init(ctx: click.Context, target: str, yes: bool, output_path: str, force: bool):
    """Generate a .dograpper.json config for your ingestion target.

    Interactive by default: pick a target (notebooklm, rag, claude-project),
    preview the generated config, confirm the write. Use --target with --yes
    for scripts.
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

    config = build_preset_config(target)
    rendered = json.dumps(config, indent=2, ensure_ascii=False)

    click.echo(f"\nGenerated config for target '{target}':\n")
    click.echo(rendered)
    click.echo()

    if not yes:
        click.confirm(f"Write to {output_path}?", abort=True)

    parent = os.path.dirname(output_path)
    if parent:
        os.makedirs(parent, exist_ok=True)

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(rendered + "\n")

    click.echo(f"Config written to {output_path}")
    click.echo("\nNext steps:")
    if output_path != ".dograpper.json":
        click.echo(f"  dograpper --config {output_path} download <url> -o ./docs")
        click.echo(f"  dograpper --config {output_path} pack ./docs -o ./chunks")
    else:
        click.echo("  dograpper download <url> -o ./docs")
        click.echo("  dograpper pack ./docs -o ./chunks")
