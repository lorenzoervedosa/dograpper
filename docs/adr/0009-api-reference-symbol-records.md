# 9. API reference pages are split into symbol records by generator-specific adapters

- Status: accepted
- Date: 2026-11-14

## Context

Packing an API reference today produces one record per page, so on a Javadoc
site every class becomes one record. The measured corpus is a Javadoc 25 site
with about 1,700 in-scope pages and 60,000 documented members, mostly signatures
with little prose. There, a single record ran up to 38,700 words. Retrieval was
tested with exact API lookups through `dograpper serve` (see
[the case study](../discovery/javadoc-ingestion-case-study.md)):

- only 1 of 5 lookups found the right page in the top 5;
- `get_chunk` returned 143,000 characters for one class.

Two ways of making records smaller were measured on the same corpus and the same
queries:

| Approach | Right member in top 5 (4 exact lookups) | Record size |
|---|---|---|
| Generic: split records by word count (80 or 400 words) and index the breadcrumb together with the content | 0 of 4 (right page in top 5: 2–3 of 5) | 80–400 words |
| Generator-aware: one container record per class, one member record per documented member, qualified name in the text, summary tables dropped | 4 of 4 (ranks 2, 1, 1, 1) | member p99 81 words; largest 3,861 (a container with 3,842 constants) |

The generic split does not reach the member's own detail, for two reasons:

- the word windows cut across member boundaries;
- summary tables and inherited-member lists repeat every member name, so they
  outrank that detail.

## Decision

1. **Adapters per generator.** One adapter per generator splits API reference
   pages into container records and member records, using the terms in
   [GLOSSARY.md](../../GLOSSARY.md). The adapter reads the generator's HTML
   structure directly.
2. **Opt-in, JSONL only.** The feature is turned on with `pack --api-records`
   (config key `api_records`) and only works with JSONL; any other format is a
   usage error. With the flag on:
   - each page is checked against the supported generators;
   - an unrecognised page, or one with unsupported markup, keeps one record per
     page and produces a warning.
3. **Scope.** The scope is API references in general, delivered one generator
   per PR in this order: Javadoc, Sphinx autodoc, rustdoc, TypeDoc, Doxygen.
   Each adapter:
   - supports only the markup versions that were measured;
   - ships with a fixture generated from code owned by this repository;
   - passes an acceptance run on a real public corpus.
4. **Record content.** Records carry the qualified name in their text, because
   the `serve` index covers text only.
   - Container records hold the description, inheritance, declared member names
     and inherited-member lists.
   - Member records hold the signature, notes and doc comment.
   - Summary tables are dropped.
   - Nested containers get their own container records.
5. **Schema.** The schema stays at v1, with new optional fields `symbol`,
   `kind`, `symbol_kind`, `container` and `generator`. `url` includes the
   member anchor. Ids are `NN_path` for the page's main container and
   `NN_path#anchor` for every other record from that page.
6. **Pipeline.** Recognised pages bypass content extraction and dedup. Query
   ordering ([ADR-0006](0006-query-oriented-packing.md)) and delta
   ([ADR-0008](0008-delta-as-a-change-gate.md)) keep working per page, and
   records inherit their page's chunk. In member records, the breadcrumb is
   `[container, member]`.

## Consequences

- Record count and ids change only when the flag is on.
- Do not fold adapters back into generic word splitting without re-running the
  measurement above.
- Every new generator costs an adapter, a fixture and a corpus. No generic
  fallback extracts members.
- Each generator must pass this acceptance bar:
  - at least 80% of about 20 curated lookups hit the declaring member, or its
    container record, in the top 5;
  - 100% of sampled signatures keep their type parameters;
  - member records have p99 ≤ 100 words and max ≤ 3,000;
  - container records have max ≤ 5,000 words;
  - pack time is at most 2× the baseline.
