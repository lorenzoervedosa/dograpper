"""Mold of the pack stages that leave pages out (6a to 6a-3): warn with the listing, filter, fail when none is left."""

import os

import click

from ..utils.output import say


def skip_pages(kept: list[str], skipped: list[str], input_dir: str, headline: str,
               empty_error: str | None = None) -> list[str]:
    """`kept` without `skipped`; `headline` and the listed paths go to stderr (silenced by -q).

    With `empty_error`, nothing left to pack raises it as a ClickException.
    """
    if not skipped:
        return kept
    listed = "\n".join("  " + os.path.relpath(p, input_dir).replace(os.sep, '/') for p in skipped)
    say(f"{headline}:\n{listed}", err=True)
    gone = set(skipped)
    kept = [p for p in kept if p not in gone]
    if empty_error and not kept:
        raise click.ClickException(empty_error)
    return kept
