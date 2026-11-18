"""`pack --layout page`: flag checks, the pages/ ownership guard and the write (ADR-0010).

pack.py keeps the click options and the pipeline; this module owns the mode's CLI rules.
"""

import os

import click

from ..lib.config_loader import is_explicit, read_config_section
from ..lib.page_layout import INDEX_FILENAME, PAGES_DIR, owns_pages, write_pages

# Options that only shape chunks: setting one, on the CLI or in config, is an error.
CHUNK_ONLY_OPTIONS = ('max_words_per_chunk', 'max_chunks', 'strategy', 'prefix', 'with_index')


def _flag(ctx: click.Context, name: str) -> str:
    param = next(p for p in ctx.command.params if p.name == name)
    return "/".join(param.opts + param.secondary_opts)


def check_flags(ctx: click.Context, merged_params: dict, config_path: str) -> None:
    """Usage error (exit 2) for every setting that has no meaning in the page layout."""
    config = read_config_section(config_path, 'pack')
    for name in CHUNK_ONLY_OPTIONS:
        in_config = name in config or name.replace('_', '-') in config
        if is_explicit(ctx, name) or in_config:
            where = f" (set in {config_path})" if not is_explicit(ctx, name) else ""
            raise click.UsageError(
                f"{_flag(ctx, name)}{where} has no effect with --layout page")
    if merged_params['format'] == 'jsonl':
        raise click.UsageError(
            "--layout page writes md or txt pages; --format jsonl needs --layout chunk")
    if merged_params['bundle'] is not None:
        raise click.UsageError(
            "--bundle presets list chunks; they need --layout chunk, not --layout page")
    if merged_params['for_queries']:
        raise click.UsageError(
            "--for-queries co-locates pages in chunks; it needs --layout chunk, "
            "not --layout page")
    if str(merged_params['dedup']).lower() != 'off':
        raise click.UsageError(
            "--layout page needs --dedup off: dedup keeps a repeated block on one page "
            "only, so another page read alone loses it")


def check_ownership(output_dir: str) -> None:
    """Exit 1 when <output>/pages exists but is not a previous page-layout output."""
    if not owns_pages(output_dir):
        raise click.ClickException(
            f"{os.path.join(output_dir, PAGES_DIR)} exists without {INDEX_FILENAME} next to it, "
            "so it is not a previous --layout page output; move it or choose another --output")


def write(chunks, **kwargs) -> str:
    """``write_pages`` with a failed write reported as exit 1. Returns the index path."""
    try:
        return write_pages(chunks, **kwargs)
    except OSError as e:
        raise click.ClickException(f"cannot write the page layout: {e}") from e
