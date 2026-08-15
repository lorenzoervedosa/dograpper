"""Explain subcommand — preview exactly what the LLM receives per chunk.

Read-only inspection of packed chunks: rendered dograpper-context-v1
headers, breadcrumbs, readiness grades, cross-references and content
previews. Nothing is written to disk.
"""

import click
import logging

from ..utils.chunk_inspector import (
    discover_chunks,
    parse_chunk_sections,
    load_sidecar,
    readiness_for,
    cross_refs_for,
)

logger = logging.getLogger(__name__)

PREVIEW_WORDS = 60


def _preview(text: str, full: bool) -> str:
    if full:
        return text
    words = text.split()
    if len(words) <= PREVIEW_WORDS:
        return text
    return " ".join(words[:PREVIEW_WORDS]) + " […]"


def _echo_breadcrumb(breadcrumb):
    if breadcrumb:
        click.echo(f"  Breadcrumb: {' > '.join(breadcrumb)}")


@click.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  dograpper explain ./chunks\n"
        "  dograpper explain ./chunks docs_chunk_00\n"
        "  dograpper explain ./chunks 00 --full\n"
    )
)
@click.argument('chunks_dir', type=click.Path(exists=True, file_okay=False, dir_okay=True), required=True)
@click.argument('chunk_id', type=str, required=False, default=None)
@click.option('--prefix', type=str, default="docs_chunk_", show_default=True,
              help="Chunk filename prefix to inspect.")
@click.option('--full', is_flag=True, default=False,
              help="Print full section contents instead of a preview.")
@click.pass_context
def explain(ctx, chunks_dir, chunk_id, prefix, full):
    """Preview what the LLM will receive for a packed chunk.

    Without CHUNK_ID, lists the chunks found in CHUNKS_DIR. With a
    CHUNK_ID (e.g. docs_chunk_00, or just 00), prints the final view
    per section: v1 context header, breadcrumb, readiness grade,
    cross-references and a content preview. Read-only.
    """
    chunks = discover_chunks(chunks_dir, prefix=prefix)
    if not chunks:
        click.echo(
            f"Error: no chunk files ({prefix}*.md/.txt/.jsonl) found in {chunks_dir}.",
            err=True,
        )
        ctx.exit(1)

    readiness = load_sidecar(chunks_dir, "llm-readiness.json")
    cross_refs = load_sidecar(chunks_dir, "cross_refs.json")

    if chunk_id is None:
        click.echo(f"Chunks in {chunks_dir}:")
        for info in chunks:
            entry = readiness_for(readiness, info.chunk_id)
            grade = ""
            if entry:
                grade = (f"  grade {entry.get('grade', '?')} "
                         f"({entry.get('score', '?')})")
            click.echo(f"  {info.chunk_id}.{info.format}{grade}")
        click.echo("\nRun `dograpper explain <chunks-dir> <chunk-id>` to inspect one.")
        return

    # Accept bare index ("00") as shorthand for <prefix>00
    wanted = chunk_id if chunk_id.startswith(prefix) else f"{prefix}{chunk_id}"
    matching = [c for c in chunks if c.chunk_id == wanted]
    if not matching:
        available = ", ".join(sorted({c.chunk_id for c in chunks}))
        click.echo(f"Error: chunk '{wanted}' not found. Available: {available}", err=True)
        ctx.exit(1)
    info = matching[0]
    if len(matching) > 1:
        others = ", ".join(f".{c.format}" for c in matching[1:])
        click.echo(f"Note: {info.chunk_id} also exists as {others}; "
                   f"inspecting .{info.format}")

    click.echo(f"Chunk:  {info.chunk_id}.{info.format}")

    entry = readiness_for(readiness, info.chunk_id)
    if entry:
        click.echo(f"Readiness: grade {entry.get('grade', '?')} "
                   f"(score {entry.get('score', '?')}, "
                   f"noise_ratio {entry.get('noise_ratio', '?')}, "
                   f"boundary_integrity {entry.get('boundary_integrity', '?')}, "
                   f"context_depth {entry.get('context_depth', '?')})")

    refs = cross_refs_for(cross_refs, info.chunk_id)
    if refs:
        to = refs.get("references_to", [])
        by = refs.get("referenced_by", [])
        click.echo(f"Cross-refs: {len(refs.get('links', []))} links"
                   f" | references_to: {', '.join(to) if to else '—'}"
                   f" | referenced_by: {', '.join(by) if by else '—'}")

    if info.format == "jsonl":
        from ..lib.pack_reader import load_chunks
        records = load_chunks(chunks_dir, files=[info.path])

        click.echo(f"Records: {len(records)}\n")
        for rec in records:
            click.echo(f"— id: {rec.id}")
            click.echo(f"  Source: {rec.source}")
            _echo_breadcrumb(rec.breadcrumb)
            if rec.grade:
                click.echo(f"  Grade: {rec.grade}")
            click.echo(f"  Words: {rec.words}")
            click.echo(f"  Content: {_preview(rec.text, full)}")
            click.echo()
    else:
        with open(info.path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        sections = parse_chunk_sections(text)
        click.echo(f"Sections: {len(sections)}\n")
        for i, sec in enumerate(sections):
            click.echo(f"— section {i + 1}")
            if sec.source:
                click.echo(f"  Source: {sec.source}")
            _echo_breadcrumb(sec.breadcrumb)
            if sec.header:
                if "url" in sec.header:
                    click.echo(f"  URL: {sec.header['url']}")
                if "llm_readiness" in sec.header:
                    r = sec.header["llm_readiness"]
                    click.echo(f"  Grade: {r.get('grade', '?')} (score {r.get('score', '?')})")
                if "word_count" in sec.header:
                    click.echo(f"  Words: {sec.header['word_count']}")
            click.echo(f"  Content: {_preview(sec.content, full)}")
            click.echo()
