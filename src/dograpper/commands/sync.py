"""Sync subcommand — download + pack --delta in one step."""

import click
import logging

from ..lib.config_loader import is_explicit_source

logger = logging.getLogger(__name__)

# sync's own option names forwarded to each stage. Used to detect which of
# them the user set explicitly, so precedence survives ctx.invoke (see
# lib/config_loader.py and issue #32).
_DOWNLOAD_PASSTHROUGH = ('depth', 'headless', 'delay', 'include_extensions')
_PACK_PASSTHROUGH = ('max_words_per_chunk', 'max_chunks', 'strategy', 'format',
                     'bundle', 'context_header', 'cross_refs', 'score',
                     'dedup', 'show_tokens', 'for_queries')


def _explicit_params(ctx: click.Context, names) -> set:
    return {name for name in names
            if is_explicit_source(ctx.get_parameter_source(name))}


@click.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  dograpper sync https://docs.example.com -o ./docs\n"
        "  dograpper sync https://docs.example.com -o ./docs --bundle notebooklm --context-header --score\n"
        "  dograpper sync https://spa.example.com -o ./docs --headless --format jsonl --cross-refs\n"
    )
)
@click.argument('url', type=str, required=True)
# --- Download pass-through ---
@click.option('--output', '-o', required=True, type=click.Path(),
              help="Base directory (download writes here, pack reads from here)")
@click.option('--depth', '-d', type=int, default=0, show_default=True,
              help="Maximum link depth (0 = unlimited)")
@click.option('--headless', is_flag=True, default=False,
              help="Skip wget and crawl directly with Playwright (SPAs)")
@click.option('--delay', type=int, default=0, show_default=True,
              help="Interval between requests in ms")
@click.option('--include-extensions', type=str, default="html,md,txt", show_default=True,
              help="Allowed extensions, comma-separated")
# --- Pack pass-through ---
@click.option('--chunks-dir', type=str, default=None,
              help="Chunks output directory (default: <output>/chunks)")
@click.option('--max-words-per-chunk', type=int, default=500000, show_default=True)
@click.option('--max-chunks', type=int, default=50, show_default=True)
@click.option('--strategy', type=click.Choice(['size', 'semantic']), default='size', show_default=True)
@click.option('--format', type=click.Choice(['txt', 'md', 'jsonl', 'xml']), default='md', show_default=True)
@click.option('--bundle', type=click.Choice(['notebooklm', 'rag-standard']), default=None)
@click.option('--context-header', is_flag=True, default=False,
              help="Inject a dograpper-context-v1 header in each chunk file")
@click.option('--cross-refs', is_flag=True, default=False,
              help="Generate cross_refs.json and annotate chunks with [-> chunk_id]")
@click.option('--score', is_flag=True, default=False,
              help="Compute LLM Readiness Score per chunk (llm-readiness.json)")
@click.option('--dedup', type=click.Choice(['off', 'exact', 'fuzzy', 'both'], case_sensitive=False),
              default='off', show_default=True)
@click.option('--show-tokens', is_flag=True, default=False,
              help="Show per-chunk and total token count")
@click.option('--for-queries', type=click.Path(), default=None,
              help="Queries file for query-oriented packing (see pack --for-queries)")
@click.pass_context
def sync(ctx, url, output, depth, headless, delay, include_extensions,
         chunks_dir, max_words_per_chunk, max_chunks, strategy, format,
         bundle, context_header, cross_refs, score, dedup, show_tokens,
         for_queries):
    """Incremental download + pack delta in a single command.

    Equivalent to:
      dograpper download <url> -o <output> [download flags]
      dograpper pack <output> -o <chunks-dir> --delta [pack flags]

    All relevant pack flags (bundle, context-header, score, cross-refs,
    dedup, etc.) are forwarded to the pack stage.
    """
    from .download import download
    from .pack import pack

    chunks_output = chunks_dir or f"{output}/chunks"
    ctx.ensure_object(dict)

    try:
        click.echo("=== Step 1: Download ===")
        # 'output' is always user-derived on sync (-o is required)
        ctx.obj['CLI_EXPLICIT_PARAMS'] = (
            _explicit_params(ctx, _DOWNLOAD_PASSTHROUGH) | {'output'})
        ctx.invoke(
            download,
            url=url,
            output=output,
            depth=depth,
            headless=headless,
            delay=delay,
            include_extensions=include_extensions,
        )

        click.echo("\n=== Step 2: Pack (delta) ===")
        # 'output' comes from --chunks-dir/-o and 'delta' is sync's
        # contract: both always win over config
        ctx.obj['CLI_EXPLICIT_PARAMS'] = (
            _explicit_params(ctx, _PACK_PASSTHROUGH) | {'output', 'delta'})
        ctx.invoke(
            pack,
            input_dir=output,
            output=chunks_output,
            max_words_per_chunk=max_words_per_chunk,
            max_chunks=max_chunks,
            strategy=strategy,
            format=format,
            bundle=bundle,
            context_header=context_header,
            cross_refs=cross_refs,
            score=score,
            dedup=dedup,
            show_tokens=show_tokens,
            for_queries=for_queries,
            delta=True,
        )
    finally:
        ctx.obj.pop('CLI_EXPLICIT_PARAMS', None)
