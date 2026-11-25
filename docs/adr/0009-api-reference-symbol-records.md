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

## Amendment (2026-11-18)

The member-record p99 bound in the acceptance bar is now set per generator:

| Generator | Member record p99 |
|---|---|
| Javadoc | ≤ 100 words |
| Sphinx autodoc | ≤ 300 words |
| rustdoc | ≤ 300 words |
| TypeDoc | ≤ 250 words |
| Doxygen | ≤ 550 words |

Every other criterion still applies to every generator:

- member records max ≤ 3,000 words;
- container records max ≤ 5,000 words;
- at least 80% of about 20 lookups in the top 5;
- 100% of sampled signatures keep their type parameters;
- pack time at most 2× the baseline.

Evidence comes from the Sphinx autodoc acceptance run
([#75](https://github.com/lorenzoervedosa/dograpper/issues/75), phase 2). The
corpus was the packaging docs (packaging.pypa.io, Sphinx 9.1, 237 member
records).

- Member p99 was 250 words and the largest member had 299 words.
- Python docstrings carry doctest examples and parameter lists, which the
  Javadoc corpus did not have. Each record holds one member's own
  documentation, so a lower bound would mean dropping docstring content.
- The larger records did not hurt retrieval. All 22 curated lookups hit the
  declaring member or its container record in the top 5, and in 21 of them
  the member record itself was in the top 5.

Each future generator (rustdoc, TypeDoc, Doxygen) declares its own member p99
bound in its phase PR and adds it to the table above. The PR must show
evidence for that bound:

- the measured size distribution on its acceptance corpus;
- the lookup results showing that the bound does not hurt retrieval.

## Amendment (2026-11-19): rustdoc

The rustdoc adapter ([#75](https://github.com/lorenzoervedosa/dograpper/issues/75),
phase 3) reads rustdoc 1.96 pages only: rustdoc's markup changes between
releases, so a page whose `data-rustdoc-version` is another one keeps one
record. rustdoc writes one page per symbol, so two points of the decision
read differently for it:

- **Pages with no container.** A function, constant, static or macro page
  documents one member and nothing else. Its one record is a member record,
  with the page's own id `NN_path` (decision 5 gives that id to a page's main
  container) and `container` set to the module.
- **Implementations.** A container record keeps the `impl` headers of its
  trait implementations, auto trait implementations and, on a trait page,
  implementations on foreign types and implementors. This is rustdoc's form
  of the implemented interfaces in decision 4. The members of those
  implementations are dropped, and so are the blanket implementations
  (`impl<T> Any for T`, …). Their documentation is usually the trait's,
  repeated on every implementing type, as summary tables repeat member
  names. Each member of an inherent `impl` block starts with that block's
  header, so the bounds it adds (`impl<T: Ord> Boxed<T>`) reach the member.

The member record p99 bound for rustdoc is 300 words (table above). The
evidence comes from the acceptance run
([case study](../discovery/rustdoc-api-records-acceptance.md)) on `itertools`
0.14.0, documented locally, with 316 member records:

- Member p99 was 226 words and the largest member had 419. The largest are
  doc comments with runnable examples, as in Python docstrings.
- The larger records did not hurt retrieval. All 22 curated lookups had the
  declaring member in the top 5. On the same corpus without `--api-records`,
  the declaring page was in the top 5 for 18 of them.
- All 263 member signatures with type parameters kept them; the largest
  container had 2,545 words; the pack took 1.9 s against 12.1 s without
  `--api-records`.

## Amendment (2026-11-20): rustdoc nightly

The rustdoc version lock is now a list of accepted prefixes: `1.96.` and
`1.102.0-nightly (6905905bb ` (the build of 2026-11-19). The nightly was
measured on the same `itertools` 0.14.0 corpus and passed the bar (see the
[case study](../discovery/rustdoc-api-records-acceptance.md)). Any other
version, including another nightly, keeps its pages whole with the version in
the warning: a nightly's markup can change from one day to the next, so the
lock widens by measured build, not by range. One markup difference was
handled: the notable-trait mark is a `<span class="tooltip">` on the nightly
and an `<a class="tooltip">` on 1.96; both are dropped.

## Amendment (2026-11-19): TypeDoc

The member record p99 bound for TypeDoc
([#75](https://github.com/lorenzoervedosa/dograpper/issues/75), phase 4) is
250 words (table above). The evidence comes from the acceptance run
([the TypeDoc acceptance doc](../discovery/typedoc-api-records-acceptance.md))
on `@tanstack/query-core` 5.108.1, generated locally with TypeDoc 0.28.20, with
585 member records:

- Member p99 was 216 words and the largest member had 301.
- TypeDoc repeats each type parameter and parameter of a signature in the
  doc comment's lists, with their defaults and docs. Generic TypeScript APIs
  have many type parameters.
- 22 of 24 lookups hit the declaring member or its container record in the
  top 5. 14 of the targets are member records over 100 words, and for 12 of
  them the member record itself was in the top 5.

TypeDoc writes one page per symbol, so two record rules are specific to
it:

- A function, variable or type alias page has no container on it. The page
  is one member record with id `NN_path`, the page's id, instead of
  `NN_path#anchor`. Its `container` is the module or namespace in the
  breadcrumb. When the breadcrumb starts at the symbol, as in a
  single-entry-point project, there is no container: `container` is absent
  and the breadcrumb is `[member]` instead of `[container, member]`.
- Inherited members are rendered in full on each subclass page. They get no
  member records; the container record lists their names by base
  (`Inherited from Box: put, map`), like Javadoc's "inherited from" lists.

The adapter supports only TypeDoc 0.28: the fixture and the corpus were
measured on 0.28.20, and 0.28.0 was checked on the fixture. Pages from 0.25 to
0.27 are kept whole. They put member anchors outside the `h3`, start the
breadcrumb at the project and mark no current page in it. The "Defined in"
source locations, which TypeDoc writes by default, are dropped from the records,
like Sphinx's `[source]` links.

## Amendment (2026-11-20): Doxygen

The Doxygen adapter ([#168](https://github.com/lorenzoervedosa/dograpper/issues/168),
phase 5 of [#75](https://github.com/lorenzoervedosa/dograpper/issues/75))
reads Doxygen 1.9.8 pages of C and C++ only. A page whose generator meta
names another version keeps one record. Three points of the decision read
differently for Doxygen:

- **Summary tables.** A member Doxygen documents by a brief description
  only has no documentation section: its anchor and its brief sit in its
  summary row. That row is its member record. The rows of the members that
  have a section repeat them, and are dropped as decision 4 drops summary
  tables; their names stay on the container record by section, inherited
  ones by base (`... inherited from std::_Vector_base< _Tp, _Alloc >: ...`).
- **File pages.** A file page that documents members is a container record.
  Its member records are named as the page writes them (`ring_push`, or
  `std::operator==` for a namespace that has no page), with the file as
  their container. It does not repeat the members of the namespaces it lists,
  which their namespace's page documents; a file page that documents no
  member keeps one record.
- **Shared anchors.** Doxygen 1.9.8 gives two overloads that differ only in
  their template constraints the same anchor. Such a page keeps one record,
  as decision 5 needs one id per record.
  (Superseded on 2026-11-25 by
  [#188](https://github.com/lorenzoervedosa/dograpper/issues/188), see the
  amendment below.)

The member record p99 bound for Doxygen is 550 words (table above), set by
the maintainer on 2026-11-20 above the 300 asked for in #168, after the
measurement. The evidence comes from the acceptance run
([the Doxygen acceptance doc](../discovery/doxygen-api-records-acceptance.md))
on two corpora generated locally, ICU 74.2 (C, 1,034 member records) and
libstdc++ 13 (templated C++, 2,240 member records):

- Member p99 was 506 words on ICU, 138 on libstdc++ and 305 on both
  together; the largest member had 2,359 words (the `UProperty` enum, one
  documented enumerator per value). ICU's long records are its own API
  documentation: functions that describe every parameter, error code and
  callback (`ucnv_convertEx`, 739 words), and enums. Without the enums the
  ICU p99 is still 358, so a lower bound would mean cutting documentation.
- 21 of 24 lookups hit the declaring member or its container record in the
  top 5. One miss is a large record: `ucnv_open` (325 words) ranks below
  its shorter siblings `ucnv_open*`. `UErrorCode` (1,587 words) still ranks
  3rd.
- 1,051 of 1,051 template headers of member records were kept verbatim,
  both headers of a member template of a class template included. The
  largest container had 925 words; both packs were faster than without
  `--api-records` (3.2 s vs 5.1 s, 7.4 s vs 9.1 s).

Topic (group) pages, related pages and the other Doxygen languages keep one
record: their markup was not measured. (For topic pages, superseded on
2026-11-25 by [#187](https://github.com/lorenzoervedosa/dograpper/issues/187),
see the amendment below.)

## Amendment (2026-11-25): Doxygen overloads under one anchor

[#188](https://github.com/lorenzoervedosa/dograpper/issues/188) reverses the
"Shared anchors" point of the 2026-11-20 amendment. Overloads that Doxygen
1.9.8 gives one anchor (they differ only in their template constraints) are
one member record under that anchor, holding each overload's template
headers, signature and documentation in page order; decision 5 still holds,
as the page then has one record per anchor. Members of different names or
kinds under one anchor keep the page whole. The shared duplicate-anchor
check of the other adapters is unchanged.

On libstdc++ 13 this splits `std::optional` and `std::pair`, the only pages
the 2026-11-20 run kept whole for this reason: 7 merged records of 60 to 93
words, two overloads each, and the member p99 stays 138 words
([acceptance doc, "Follow-ups"](../discovery/doxygen-api-records-acceptance.md)).

## Amendment (2026-11-25): Doxygen topic (group) pages

[#187](https://github.com/lorenzoervedosa/dograpper/issues/187) reverses the
2026-11-20 amendment for topic pages. A Doxygen 1.9.8 page whose title has no
"Reference" suffix and that documents members in sections is a topic page
(`\defgroup`): a container record with `symbol_kind` `group` (title,
description, member names by summary section), and one member record per
member it documents, with the group's title as `container`. A group is not a
code symbol, so a container here may be the page that documents members no
code symbol declares, as a file page already was (glossary: **Container**).
Members are named as the page writes them; the maintainer chose this on
2026-11-25 after the run showed that Doxygen writes a namespace member
qualified (`std::copy`) and a `\relates` symbol bare (`make_shared`), with no
scope anywhere on the page. The section's title drops the namespace, so the
name comes from the member's summary row. A topic page
without member sections keeps one record, and its member anchors must start
with `g`, as Doxygen writes a group member's.

On libstdc++ 13 regenerated with its groups (644 pages, 24 group pages, 11
with member sections), the 11 pages give 353 member records that had none
before; the member p99 is 142 words (≤ 550), the largest container 772 (≤
5,000), and 31 of 34 lookups over both corpora hit in the top 5
([acceptance doc, "Follow-ups"](../discovery/doxygen-api-records-acceptance.md)).
