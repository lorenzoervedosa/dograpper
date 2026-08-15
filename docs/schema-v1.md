# dograpper-context-v1 Schema

## Header Format

Each chunk begins with a metadata block in an HTML comment:

```
<!-- dograpper-context-v1
{ ... JSON ... }
-->
```

## Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| source | string | yes | Relative path of the source file |
| url | string | no | Original URL (from download manifest) |
| chunk_index | int | no | Sub-chunk position (1-based). Omitted if file is not split. |
| total_chunks | int | no | Total sub-chunks for this file. Omitted if file is not split. |
| word_count | int | no | Word count of this chunk's content (excluding header) |
| context_breadcrumb | string[] | no | Heading hierarchy at chunk start. Omitted if no headings. |
| llm_readiness | object | no | Readiness metrics (present when --score is used) |
| schema_version | string | yes | Always "v1" |

## llm_readiness Object

| Field | Type | Description |
|-------|------|-------------|
| score | float | Composite score 0.0-1.0 |
| grade | string | "A", "B", or "C" |
| noise_ratio | float | Proportion of boilerplate removed (0.0-1.0) |

## JSONL Record Format (`--format jsonl`)

Each line of a `.jsonl` chunk file is a self-contained JSON object for one
source file (or one sub-chunk of it, when heading-driven splitting divides
a file across sub-chunks). Same `schema_version: "v1"`, but a different
field shape than the header above — JSONL is meant to be parsed
line-by-line by RAG ingestion code, not read by a human alongside the
content.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | string | yes | Unique record identifier |
| source | string | yes | Relative path of the source file |
| words | int | yes | Word count of `content` |
| content | string | yes | Extracted text |
| schema_version | string | yes | Always "v1" |
| breadcrumb | string[] | no | Heading hierarchy at this position. Present with `--context-header` or `--score`, only when the source file has headings. |
| chunk_index | int | no | Sub-chunk position (1-based). Present only when heading-driven splitting produced more than one sub-chunk for this file. |
| total_chunks | int | no | Total sub-chunks for this file. Same condition as `chunk_index`. |
| url | string | no | Original URL. Present only with `--context-header` **and** a matching manifest entry — `--score` alone never populates it, even against a matching manifest. |
| readiness_grade | string | no | Bare grade letter ("A"/"B"/"C"). Present with `--score`. Not the same shape as the header's `llm_readiness` object — see below. |

### Field names diverge from the header format

The header and JSONL records describe the same concepts with different
field names in three places. A consumer written against one shape will
not parse the other correctly for these fields:

| Concept | Header field | JSONL field |
|---|---|---|
| word count | `word_count` | `words` |
| breadcrumb | `context_breadcrumb` | `breadcrumb` |
| readiness | `llm_readiness` (object: `score`, `grade`, `noise_ratio`) | `readiness_grade` (bare string, grade only) |

`source`, `url`, `chunk_index`, `total_chunks` and `schema_version` are
identical between the two shapes. `id` and `content` are JSONL-only —
the header format doesn't need an id (it's inline metadata above the
content) or its own content field (it's prepended to the chunk's actual
text).

Source of truth: `src/dograpper/lib/chunker.py` (record construction) and
`src/dograpper/lib/pack_reader.py` (the shape read back by `explain`,
`eval` and `serve`).

## Versioning

Future versions (v2+) will be backward-compatible. Parsers should
check `schema_version` and ignore unknown fields.
