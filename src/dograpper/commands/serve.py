"""Serve subcommand — local MCP server over the packed context.

Exposes a chunks directory (JSONL pack) as an MCP server on stdio so MCP
clients (Claude Code/Desktop, Cursor) can query the packed context live:
deterministic BM25 top-k retrieval, chunk lookup by id, cross-reference
navigation and readiness grades. Fully local, zero outbound network.
"""

import click
from importlib.metadata import PackageNotFoundError, version as _pkg_version

from ..lib.mcp_server import McpServer, Tool, ToolError, serve_stdio
from ..lib.pack_reader import load_chunks
from ..lib.retrieval import build_index
from ..utils.chunk_inspector import load_sidecar

EXCERPT_WORDS = 50


def _excerpt(text: str) -> str:
    words = text.split()
    if len(words) <= EXCERPT_WORDS:
        return text
    return " ".join(words[:EXCERPT_WORDS]) + " […]"


def _parent_chunk_id(record_id: str, prefix: str) -> str:
    """Map a JSONL record id (``NN_path`` or ``NN_j_path``) to the chunk
    file id (``<prefix>NN``) used by cross_refs.json / llm-readiness.json."""
    index = record_id.split("_", 1)[0]
    return f"{prefix}{index}"


def build_tools(chunks, index, cross_refs, readiness, prefix: str):
    """Wire the MCP tools over the loaded pack artifacts."""
    by_id = {c.id: c for c in chunks}

    def search_chunks(args: dict):
        query = args.get("query")
        if not query or not isinstance(query, str):
            raise ToolError("Missing required argument: query")
        k = args.get("k", 5)
        if isinstance(k, bool) or not isinstance(k, int) or k < 1:
            raise ToolError("k must be a positive integer")
        hits = index.search(query, k=k)
        results = []
        for hit in hits:
            if hit.score <= 0:
                continue
            rec = by_id.get(hit.doc_id)
            if rec is None:
                continue
            results.append({
                "id": rec.id,
                "chunk_id": _parent_chunk_id(rec.id, prefix),
                "source": rec.source,
                "rank": hit.rank,
                "score": round(hit.score, 4),
                "breadcrumb": rec.breadcrumb,
                "grade": rec.grade,
                "words": rec.words,
                "excerpt": _excerpt(rec.text),
            })
        return {"query": query, "k": k, "results": results}

    def get_chunk(args: dict):
        rec_id = args.get("id")
        if not rec_id or not isinstance(rec_id, str):
            raise ToolError("Missing required argument: id")
        rec = by_id.get(rec_id)
        if rec is None:
            raise ToolError(f"Chunk not found: {rec_id}")
        return {
            "id": rec.id,
            "chunk_id": _parent_chunk_id(rec.id, prefix),
            "source": rec.source,
            "breadcrumb": rec.breadcrumb,
            "grade": rec.grade,
            "words": rec.words,
            "content": rec.text,
        }

    def get_cross_refs(args: dict):
        chunk_id = args.get("chunk_id")
        if not chunk_id or not isinstance(chunk_id, str):
            raise ToolError("Missing required argument: chunk_id")
        if cross_refs is None:
            raise ToolError(
                "No cross_refs.json in this pack. Re-pack with --cross-refs.")
        entry = cross_refs.get(chunk_id)
        if entry is None:
            raise ToolError(f"No cross-references for chunk: {chunk_id}")
        return {"chunk_id": chunk_id,
                "references_to": entry.get("references_to", []),
                "referenced_by": entry.get("referenced_by", []),
                "links": entry.get("links", [])}

    def get_readiness(args: dict):
        if readiness is None:
            raise ToolError(
                "No llm-readiness.json in this pack. Re-pack with --score.")
        chunk_id = args.get("chunk_id")
        if chunk_id:
            for entry in readiness.get("chunks", []):
                if entry.get("chunk_id") == chunk_id:
                    return entry
            raise ToolError(f"No readiness entry for chunk: {chunk_id}")
        return readiness.get("summary", {})

    return [
        Tool(
            name="search_chunks",
            description=(
                "Deterministic BM25 top-k search over the packed documentation "
                "chunks. Returns ranked records with source, breadcrumb, "
                "readiness grade and a content excerpt."),
            input_schema={
                "type": "object",
                "properties": {
                    "query": {"type": "string",
                              "description": "Search query."},
                    "k": {"type": "integer", "default": 5,
                          "description": "Number of results."},
                },
                "required": ["query"],
            },
            handler=search_chunks,
        ),
        Tool(
            name="get_chunk",
            description="Fetch the full content of a chunk record by its id.",
            input_schema={
                "type": "object",
                "properties": {
                    "id": {"type": "string",
                           "description": "Record id, e.g. 00_guide/intro.html."},
                },
                "required": ["id"],
            },
            handler=get_chunk,
        ),
        Tool(
            name="get_cross_refs",
            description=(
                "Navigate cross-references between chunk files: which chunks "
                "this one links to (references_to) and which link back "
                "(referenced_by). Requires a pack built with --cross-refs."),
            input_schema={
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string",
                                 "description": "Chunk file id, e.g. docs_chunk_00."},
                },
                "required": ["chunk_id"],
            },
            handler=get_cross_refs,
        ),
        Tool(
            name="get_readiness",
            description=(
                "LLM readiness score. With chunk_id, the per-chunk entry "
                "(grade, noise_ratio, boundary_integrity, context_depth); "
                "without, the pack summary. Requires a pack built with --score."),
            input_schema={
                "type": "object",
                "properties": {
                    "chunk_id": {"type": "string",
                                 "description": "Chunk file id, e.g. docs_chunk_00."},
                },
            },
            handler=get_readiness,
        ),
    ]


@click.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  dograpper serve ./chunks\n"
        "\b\n"
        "Register in Claude Code:\n"
        "  claude mcp add my-docs -- dograpper serve ./chunks\n"
    )
)
@click.argument('chunks_dir', type=click.Path(exists=True, file_okay=False, dir_okay=True), required=True)
@click.option('--prefix', type=str, default="docs_chunk_", show_default=True,
              help="Chunk filename prefix to load.")
@click.pass_context
def serve(ctx, chunks_dir, prefix):
    """Serve the packed context as a local MCP server (stdio).

    Loads the JSONL chunks (plus cross_refs.json / llm-readiness.json when
    present) and answers MCP tool calls: search_chunks, get_chunk,
    get_cross_refs, get_readiness. Runs until stdin closes. Local only —
    no outbound network calls.
    """
    chunks = load_chunks(chunks_dir, prefix=prefix)
    if not chunks:
        click.echo(
            "Error: no JSONL chunks found. Re-pack with "
            "`dograpper pack <dir> -o <chunks> --format jsonl --context-header`.",
            err=True,
        )
        ctx.exit(1)

    index = build_index(chunks)
    cross_refs = load_sidecar(chunks_dir, "cross_refs.json")
    readiness = load_sidecar(chunks_dir, "llm-readiness.json")

    try:
        server_version = _pkg_version("dograpper")
    except PackageNotFoundError:
        server_version = "0.0.0+unknown"

    tools = build_tools(chunks, index, cross_refs, readiness, prefix)
    server = McpServer(name="dograpper", version=server_version, tools=tools)

    # Status goes to stderr: stdout is reserved for the MCP protocol.
    click.echo(
        f"dograpper MCP server: {len(chunks)} records from {chunks_dir} "
        f"(cross_refs: {'yes' if cross_refs else 'no'}, "
        f"readiness: {'yes' if readiness else 'no'}). Waiting for client…",
        err=True,
    )
    import sys
    if hasattr(sys.stdout, "reconfigure"):
        # Packed content is arbitrary unicode; don't let a non-UTF-8
        # locale kill the server mid-response.
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    serve_stdio(server)
