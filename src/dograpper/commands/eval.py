"""Eval subcommand — empirical hit-rate validation of packed context.

Reads JSONL chunks produced by `pack --format jsonl --context-header`,
generates deterministic offline golden Q&A from heading breadcrumbs, runs
BM25 retrieval, and reports hit-rate@k, MRR and a per-grade breakdown.
Fully offline — no network calls.
"""

import json
import click
import logging

from ..lib.pack_reader import load_chunks
from ..lib.retrieval import build_index
from ..lib.golden_qa import generate_golden_qa
from ..lib.eval_harness import evaluate

logger = logging.getLogger(__name__)


@click.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  dograpper eval ./chunks\n"
        "  dograpper eval ./chunks -k 3 -o eval-report.json\n"
    )
)
@click.argument('chunks_dir', type=click.Path(exists=True, file_okay=False, dir_okay=True), required=True)
@click.option('--top-k', '-k', type=int, default=5, show_default=True,
              help="Retrieval depth used to compute hit-rate.")
@click.option('--output', '-o', type=click.Path(), default=None,
              help="Write the JSON report to this path.")
@click.option('--prefix', type=str, default="docs_chunk_", show_default=True,
              help="Chunk filename prefix to load.")
@click.pass_context
def eval(ctx, chunks_dir, top_k, output, prefix):
    """Validate packed context empirically via golden Q&A hit-rate."""
    chunks = load_chunks(chunks_dir, prefix=prefix)
    if not chunks:
        click.echo(
            "Error: no JSONL chunks found. Re-pack with "
            "`dograpper pack <dir> -o <chunks> --format jsonl --context-header`.",
            err=True,
        )
        ctx.exit(1)

    pairs = generate_golden_qa(chunks)
    if not pairs:
        click.echo(
            "Error: no golden Q&A could be generated (chunks lack heading "
            "breadcrumbs). Re-pack with --context-header.",
            err=True,
        )
        ctx.exit(1)

    index = build_index(chunks)
    report = evaluate(index, chunks, pairs, k=top_k)

    click.echo(f"Chunks:        {len(chunks)}")
    click.echo(f"Golden Q&A:    {report.total_questions}")
    click.echo(f"Hit-rate@{top_k}:   {report.hit_rate:.1%} ({report.hits}/{report.total_questions})")
    click.echo(f"MRR:           {report.mrr:.3f}")
    if report.per_grade:
        click.echo("By readiness grade:")
        for grade, stats in report.per_grade.items():
            click.echo(f"  {grade}: {stats['hit_rate']:.1%} ({stats['hits']}/{stats['questions']})")

    if output:
        payload = {
            "k": report.k,
            "total_questions": report.total_questions,
            "hits": report.hits,
            "hit_rate": report.hit_rate,
            "mrr": report.mrr,
            "per_grade": report.per_grade,
        }
        with open(output, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        click.echo(f"Report written to {output}")
