# dograpper explain

Read-only preview of exactly what the LLM will receive per chunk —
audit before uploading to NotebookLM or ingesting into a RAG pipeline.
Nothing is written to disk.

```bash
dograpper explain ./chunks                  # list chunks (id, format, grade)
dograpper explain ./chunks docs_chunk_01    # inspect one chunk
dograpper explain ./chunks 01 --full        # bare index, full content
```

Per section it shows: the parsed `dograpper-context-v1` header (source,
URL, breadcrumb, per-chunk readiness), cross-references from
`cross_refs.json` (`references_to` / `referenced_by`), readiness detail
from `llm-readiness.json`, and the content preview — including the
`[-> chunk_id]` annotations exactly as the LLM sees them. Works with
`md`, `txt` and `jsonl` packs. Exits 1 when `CHUNKS_DIR` holds no
`<prefix>*` chunk file, or when the chunk id is unknown (the message lists
the ids available).

## Options

```{dograpper-options} explain
```

## Options in detail

### `--full`

Print full section contents instead of a 60-word preview
