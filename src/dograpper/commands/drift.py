"""Drift subcommand — context drift between two llm-readiness.json snapshots.

Thin CLI wrapper over lib/readiness_diff.py. Compares the freshly generated
readiness snapshot against a previous one (plus, optionally, the
delta_manifest.json source-file lists) and renders a markdown or plain-text
drift report. Used standalone and by the freshness GitHub Action.
"""

import json
import click
import logging

from ..lib.readiness_diff import compare_readiness, render_markdown, render_text

logger = logging.getLogger(__name__)


def _load_readiness(ctx, path, label):
    """Load and validate an llm-readiness.json file, or exit 1 loudly.

    Deliberately diverges from utils/chunk_inspector.load_sidecar, which
    returns None on a missing/invalid sidecar because explain/serve treat
    readiness as optional decoration. Here the snapshots are the command's
    primary input, so any missing or malformed file must fail loudly.
    """
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        click.echo(f"Error: cannot read {label} snapshot {path}: {e}", err=True)
        ctx.exit(1)
    if not isinstance(data, dict) or not isinstance(data.get("chunks"), list):
        click.echo(
            f"Error: {label} snapshot {path} is not a valid llm-readiness.json "
            "(missing `chunks` list). Re-pack with --score.",
            err=True,
        )
        ctx.exit(1)
    for entry in data["chunks"]:
        if (not isinstance(entry, dict)
                or not isinstance(entry.get("chunk_id"), str)
                or not isinstance(entry.get("score"), (int, float))
                or isinstance(entry.get("score"), bool)
                or not isinstance(entry.get("grade"), str)):
            click.echo(
                f"Error: {label} snapshot {path} has an invalid chunk entry "
                "(chunk_id/score/grade missing or wrong type). "
                "Re-pack with --score.",
                err=True,
            )
            ctx.exit(1)
    return data


@click.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  dograpper drift --new chunks/llm-readiness.json --old old-readiness.json\n"
        "  dograpper drift --new chunks/llm-readiness.json --old old-readiness.json \\\n"
        "      --delta-manifest chunks/delta_manifest.json --format markdown -o drift.md\n"
    )
)
@click.option('--new', 'new_path', required=True, type=click.Path(),
              help="Freshly generated llm-readiness.json (pack --score).")
@click.option('--old', 'old_path', type=click.Path(), default=None,
              help="Previous llm-readiness.json snapshot. Omit for first-run "
                   "mode (every chunk reported as added).")
@click.option('--delta-manifest', 'delta_path', type=click.Path(), default=None,
              help="delta_manifest.json from pack --delta. Missing file is "
                   "tolerated (no source drift recorded).")
@click.option('--format', 'output_format', type=click.Choice(['markdown', 'text']),
              default='markdown', show_default=True,
              help="Report format. Markdown starts with the "
                   "<!-- dograpper-drift --> marker.")
@click.option('--output', '-o', type=click.Path(), default=None,
              help="Write the report to this file instead of stdout.")
@click.option('--fail-on-drift', is_flag=True, default=False,
              help="Exit 1 when any drift exists (first run counts as drift).")
@click.pass_context
def drift(ctx, new_path, old_path, delta_path, output_format, output,
          fail_on_drift):
    """Report context drift between two llm-readiness.json snapshots."""
    new_data = _load_readiness(ctx, new_path, "new")

    old_data = None
    if old_path is not None:
        old_data = _load_readiness(ctx, old_path, "old")

    delta = None
    if delta_path is not None:
        try:
            with open(delta_path, 'r', encoding='utf-8', errors='replace') as f:
                delta = json.load(f)
        except FileNotFoundError:
            # pack --delta legitimately does not write the manifest when
            # nothing changed — the renderers label this in the output.
            logger.debug(f"delta manifest {delta_path} not found; "
                         "reporting no source drift recorded")
        except (OSError, json.JSONDecodeError) as e:
            click.echo(f"Error: cannot read delta manifest {delta_path}: {e}",
                       err=True)
            ctx.exit(1)
        if delta is not None and not isinstance(delta, dict):
            click.echo(
                f"Error: delta manifest {delta_path} is not a valid "
                "delta_manifest.json (expected a JSON object).",
                err=True,
            )
            ctx.exit(1)

    report = compare_readiness(old_data, new_data)
    if output_format == 'markdown':
        rendered = render_markdown(report, delta)
    else:
        rendered = render_text(report, delta)

    if output:
        with open(output, 'w', encoding='utf-8') as f:
            f.write(rendered + "\n")
    else:
        click.echo(rendered)

    if fail_on_drift and report.has_drift:
        ctx.exit(1)
