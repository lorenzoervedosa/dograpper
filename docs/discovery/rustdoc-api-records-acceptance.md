# rustdoc API records: acceptance run

> Discovery, 2026-11-19. Question: does the rustdoc adapter of `pack
> --api-records` ([ADR-0009](../adr/0009-api-reference-symbol-records.md),
> [#75](https://github.com/lorenzoervedosa/dograpper/issues/75) phase 3) pass
> the per-generator acceptance bar on a real crate?

## Corpus

- `itertools` 0.14.0, the crate's published source from the local Cargo
  registry, documented locally with rustdoc 1.96.1. No site was crawled.
- rustdoc ran directly, without Cargo: the crate's dev-dependencies are not in
  the local registry, so `cargo doc --offline` cannot resolve them. Its one
  dependency, `either` 1.19.0, was compiled to metadata first:

  ```bash
  rustc --edition 2021 --crate-type lib --crate-name either \
    --cfg 'feature="std"' --cfg 'feature="use_std"' --emit=metadata \
    -o deps/libeither.rmeta <registry>/either-1.19.0/src/lib.rs
  rustdoc --edition 2018 --crate-name itertools --crate-type lib --crate-version 0.14.0 \
    --cfg 'feature="default"' --cfg 'feature="use_std"' --cfg 'feature="use_alloc"' \
    --extern either=deps/libeither.rmeta -o out <registry>/itertools-0.14.0/src/lib.rs
  ```

- Input to `pack`: the 252 HTML files under `out/itertools/` (27 MB), without
  `static.files/`, source pages or the search index.
  - 125 pages document a symbol: 52 structs, 38 functions, 18 type aliases,
    6 enums, 5 traits, 3 macros, the crate and 2 modules.
  - 126 are redirect stubs that rustdoc writes at the private module of a
    re-exported symbol. They have no generator meta, so they keep one record
    each (4 words on average).
  - The remaining page is `all.html`.
- Most of the 27 MB is the members of trait implementations. Every iterator
  struct page repeats the documentation of `Iterator`'s and `Itertools`'
  provided methods under "Trait Implementations" and "Blanket
  Implementations"; `Zip` alone is 2.3 MB.

## Results

Packed with `pack --format jsonl --api-records` on `main` + the adapter. The
baseline is the same pack without `--api-records`.

| Criterion | Bar | Result |
|---|---|---|
| Lookups in the top 5 | ≥ 80% of ~20 | 22 of 22 hit the declaring member (20 in the top 3); baseline: the declaring page in 18 of 22 |
| Signatures with type parameters | 100% | 263 of 263 kept verbatim |
| Member records | p99 declared per generator; max ≤ 3,000 | p99 226 words, max 419 |
| Container records | max ≤ 5,000 | max 2,545 |
| Pack time | ≤ 2× baseline | 1.9 s vs 12.1 s (median of 3) |

Records: 400 API records from the 125 symbol pages (84 container, 316
member: 255 methods, 38 functions, 17 variants, 3 macros, 2 fields, 1
associated type), plus 127 pages kept whole. Total output 40,551 words; the
baseline writes 441,811 words in 252 records, the largest 38,887.

### Record sizes

| Records | n | Median | p90 | p99 | Max |
|---|---|---|---|---|---|
| Member | 316 | 64 | 138 | 226 | 419 |
| Container | 84 | 152 | 222 | 1,604 | 2,545 |

- The largest members are `Itertools` methods whose doc comments carry
  runnable examples: `tree_reduce` (419 words), `merge_join_by` (317),
  `GroupingMap::aggregate` (292). Like Python docstrings, a Rust doc comment
  is a member's own documentation, examples included; a p99 of 100 would mean
  cutting it.
- The largest container is the `Itertools` trait (2,545 words): its
  declaration lists every method signature. Next is `Zip` (1,604): its trait
  implementation headers cover tuples of up to 12 iterators.

### Lookups

`dograpper serve` over stdio, `search_chunks` with `k = 5`. The hit counts
when the declaring member, or its container record, is in the top 5; the
member itself was in every top 5.

| # | Query | Expected member | Rank |
|---|---|---|---|
| 1 | `interleave two iterators` | `Itertools::interleave` | 1 |
| 2 | `tuple_windows` | `Itertools::tuple_windows` | 1 |
| 3 | `chunk_by consecutive key` | `Itertools::chunk_by` | 1 |
| 4 | `kmerge_by` | `Itertools::kmerge_by` | 4 |
| 5 | `cartesian_product` | `Itertools::cartesian_product` | 1 |
| 6 | `multi_cartesian_product` | `Itertools::multi_cartesian_product` | 1 |
| 7 | `sorted_by_key` | `Itertools::sorted_by_key` | 2 |
| 8 | `fold_while FoldWhile` | `Itertools::fold_while` | 1 |
| 9 | `minmax` | `Itertools::minmax` | 1 |
| 10 | `zip_longest EitherOrBoth` | `Itertools::zip_longest` | 1 |
| 11 | `merge_join_by` | `Itertools::merge_join_by` | 5 |
| 12 | `izip macro` | `izip!` (macro page) | 2 |
| 13 | `iproduct` | `iproduct!` (macro page) | 2 |
| 14 | `EitherOrBoth Both` | `EitherOrBoth::Both` | 3 |
| 15 | `with_position Position` | `Itertools::with_position` | 1 |
| 16 | `join iterator with separator` | `Itertools::join` | 2 |
| 17 | `repeat_n` | `repeat_n` (function page) | 1 |
| 18 | `GroupingMap aggregate` | `structs::GroupingMap::aggregate` | 2 |
| 19 | `into_grouping_map_by` | `Itertools::into_grouping_map_by` | 1 |
| 20 | `PeekingNext peeking_next` | `PeekingNext::peeking_next` | 1 |
| 21 | `MultiPeek reset_peek` | `structs::MultiPeek::reset_peek` | 1 |
| 22 | `exactly_one` | `Itertools::exactly_one` | 1 |

The larger member records did not push the declaring member out. What ranks
above it in the three lowest cases:

- `kmerge_by` (4) and `merge_join_by` (5): the free functions of the same name
  (`itertools::kmerge_by`, `itertools::merge_join_by`, rank 1), which answer
  the lookup too, and redirect stubs such as `kmerge_impl/fn.kmerge_by.html`.
  A stub's only text is "Redirecting to …/fn.kmerge_by.html", so it matches
  the name.
- `EitherOrBoth Both` (3): the methods `is_both` and `both` of the same enum.

### Signatures

A separate script read every member header straight from the HTML with
regular expressions (the `h4.code-header` of a method, the `h3` of a variant,
the `code` of a field, the declaration of a function page), dropping the
permalink signs, `Source` links and the notable-trait marks (`ⓘ`) as the
adapter does. 263 of the 316 headers have type parameters, and all 263
appear verbatim in their member record.

## Reproduction

1. Build the corpus with the commands above, then copy only the `*.html`
   files under `out/itertools/` into a fresh directory.
2. `dograpper pack <dir> -o <pack> --format jsonl --api-records`, and the same
   without `--api-records` for the baseline; time both.
3. Compute the size distribution from the JSONL `words`, `kind` and `symbol`
   fields.
4. Drive `dograpper serve <pack>` over stdio with JSON-RPC `initialize`, then
   `tools/call search_chunks` (`k = 5`) for each query in the table.

## Not covered

- Pages with `Methods from Deref<Target = …>` sections (smart pointers and
  collections, e.g. `Vec` and `String` in the standard library) keep one
  record: that section was not in a measured corpus. `rust-docs` is not
  installed on the measuring machine, so the standard library was not packed.
- Primitive, keyword, attribute-macro and derive-macro pages keep one record
  for the same reason.
- docs.rs builds with nightly rustdoc, whose markup can differ from 1.96, so
  its pages keep one record until a nightly corpus is measured.
- The container bound (≤ 5,000 words) is measured, not enforced: the `impl`
  header lists grow with the number of implementations (`Zip`, 1,604 words,
  is mostly headers), so a trait implemented across a large crate such as
  the standard library could pass it.
- A trait implementation member with a doc comment of its own (not the
  trait's) is dropped with the others.
- Redirect stubs are packed as one record each and can take top-5 slots for
  a name lookup (see above); `pack` does not recognise them yet.
