# dograpper serve

Serve a packed chunks directory as a **local MCP server** (stdio), so MCP
clients — Claude Code/Desktop, Cursor — can query the packed context live.
Stdlib-only implementation: no SDK, no network, fully offline.

```bash
# Pack for serving (jsonl + context + cross-refs + score)
dograpper pack ./docs -o ./chunks --format jsonl --context-header --cross-refs --score

# Register in Claude Code
claude mcp add my-docs -- dograpper serve ./chunks
```

MCP tools exposed:

| Tool | Purpose |
|---|---|
| `search_chunks(query, k)` | Deterministic BM25 top-k retrieval (id, chunk_id, source, rank, score, breadcrumb, grade, words, excerpt) |
| `get_chunk(id)` | Full content of a record by id |
| `get_cross_refs(chunk_id)` | `references_to` / `referenced_by` navigation (needs `--cross-refs` pack) |
| `get_readiness(chunk_id?)` | Per-chunk readiness entry or the pack summary (needs `--score` pack) |

Retrieval reuses the same BM25 engine as `dograpper eval`, with stable
tie-breaking — the same query always returns the same order. The server
reads stdin line-by-line (JSON-RPC 2.0) and exits when the client closes
the pipe. Status messages go to stderr; stdout carries only the protocol.
Exits 1 if no JSONL chunks match `--prefix`.

## Options

```{dograpper-options} serve
```
