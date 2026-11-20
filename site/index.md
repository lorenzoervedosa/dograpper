# dograpper

**Context Engineering Pipeline for Deterministic LLM Ingestion**

Turns HTML documentation into structured, deduplicated, scored, and versioned
context — ready for ingestion into NotebookLM, RAG pipelines, Claude Projects,
and fine-tuning.

---

## The problem

Static LLMs don't browse the web. When fed raw documentation as context,
they suffer from: boilerplate (navbars, footers, banners), duplication
across pages, chunks without hierarchy, and code blocks cut in half.
The result is degraded retrieval and hallucination.

## The solution

`dograpper` is a deterministic pipeline that solves each stage:

```
URL → Mirror → Extract → Dedup → Score → Chunk → Export (MD/JSONL)
```

| Stage | What it does | Flag |
|-------|-----------|------|
| **Mirror** | Mirrors site locally via wget/playwright, or the `httrack` / `fire-engine` downloaders | `download` |
| **Extract** | Strips boilerplate, preserves main content | (automatic) |
| **Dedup** | Eliminates repeated blocks across pages | `--dedup` |
| **Score** | Audits context quality per chunk | `--score` |
| **Chunk** | Groups within limits, preserving code blocks | `pack` |
| **Context** | Injects breadcrumb, metadata, versioned schema | `--context-header` |
| **Export** | MD, JSONL, with cross-refs and import guide | `--format`, `--cross-refs` |

---

```{toctree}
:caption: Getting started
:hidden:
:maxdepth: 2
```

```{toctree}
:caption: Guides
:hidden:
:maxdepth: 2
```

```{toctree}
:caption: Commands
:hidden:
:maxdepth: 2

commands/pack
```

```{toctree}
:caption: Reference
:hidden:
:maxdepth: 2
```

```{toctree}
:caption: More
:hidden:
:maxdepth: 2
```
