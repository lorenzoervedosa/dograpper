# Doxygen API records: acceptance run

> Discovery, 2026-11-20. Question: does the Doxygen adapter of `pack
> --api-records` ([ADR-0009](../adr/0009-api-reference-symbol-records.md),
> [#168](https://github.com/lorenzoervedosa/dograpper/issues/168), phase 5
> of [#75](https://github.com/lorenzoervedosa/dograpper/issues/75)) pass the
> per-generator acceptance bar on real C and templated C++ headers?

## Corpus

Two projects, documented locally with Doxygen 1.9.8 from headers already on
the measuring machine. No site was crawled.

- **C: ICU 74.2**, 16 C API headers from `/usr/include/unicode` (`ustring.h`,
  `ucnv.h`, `uset.h`, `ucol.h`, `uregex.h`, `ucal.h`, `unorm2.h`, `ubrk.h`,
  `uloc.h`, `utext.h`, `ucsdet.h`, `udat.h`, `unum.h`, `utf8.h`, `utypes.h`,
  `uchar.h`). ICU's own API reference is Doxygen output; the run uses the
  `PREDEFINED` macros and the `\stable`/`\draft`/`\deprecated` aliases of
  ICU's Doxyfile. 62 HTML pages (6.5 MB): 16 file pages, 3 struct pages,
  and 43 listing, source, topic and list pages.
- **C++: libstdc++ 13**, 19 headers from `/usr/include/c++/13` (vector,
  `vector<bool>`, list, forward_list, deque, map, multimap, set,
  unordered_map, queue, stack, unique_ptr, shared_ptr, pair, function,
  iterators, optional, string_view). The real libstdc++ reference is Doxygen
  output too; the run predefines the `_GLIBCXX_*` macros as its Doxyfile
  does. 411 pages (12 MB): 177 class, struct and union pages, most of them
  templates, 16 file pages, and the rest listing, source and topic pages.
- Both runs keep Doxygen's defaults otherwise (`EXTRACT_ALL = NO`,
  `HIDE_UNDOC_MEMBERS = NO`, `HAVE_DOT = NO`, no source browser). Only the
  `*.html` files go to `pack`.

The Doxyfiles, one per project (`INPUT` lists the headers above; the other
keys differ from the defaults):

```text
# ICU
STRIP_FROM_PATH = /usr/include
GENERATE_LATEX = NO
HAVE_DOT = NO
ENABLE_PREPROCESSING = YES
MACRO_EXPANSION = YES
EXPAND_ONLY_PREDEF = YES
PREDEFINED = U_EXPORT2= U_STABLE= U_DRAFT= U_INTERNAL= U_SYSTEM= U_DEPRECATED= U_OBSOLETE= U_CALLCONV= U_CDECL_BEGIN= U_CDECL_END= U_NOEXCEPT= "U_NAMESPACE_BEGIN=namespace icu{" "U_NAMESPACE_END=}" U_SHOW_CPLUSPLUS_API=0 U_DEFINE_LOCAL_OPEN_POINTER()= U_IN_DOXYGEN=1 U_CAPI= U_FORCE_INLINE=
ALIASES = "draft=\xrefitem draft \"Draft\" \"Draft List\" This API may be changed in the future versions and was introduced in" "stable=\xrefitem stable \"Stable\" \"Stable List\"" "deprecated=\xrefitem deprecated \"Deprecated\" \"Deprecated List\"" "obsolete=\xrefitem obsolete \"Obsolete\" \"Obsolete List\"" "internal=\xrefitem internal \"Internal\" \"Internal List\" Do not use. This API is for internal use only."

# libstdc++
EXTENSION_MAPPING = no_extension=C++
STRIP_FROM_PATH = /usr/include/c++/13
GENERATE_LATEX = NO
HAVE_DOT = NO
ENABLE_PREPROCESSING = YES
MACRO_EXPANSION = YES
EXPAND_ONLY_PREDEF = YES
PREDEFINED = __cplusplus=202002L __GTHREADS _GLIBCXX_STD_A=std _GLIBCXX_STD_C=std "_GLIBCXX_VISIBILITY(V)=" _GLIBCXX_BEGIN_NAMESPACE_VERSION= _GLIBCXX_END_NAMESPACE_VERSION= _GLIBCXX_BEGIN_NAMESPACE_CONTAINER= _GLIBCXX_END_NAMESPACE_CONTAINER= _GLIBCXX_BEGIN_NAMESPACE_CXX11= _GLIBCXX_END_NAMESPACE_CXX11= _GLIBCXX_BEGIN_NAMESPACE_ALGO= _GLIBCXX_END_NAMESPACE_ALGO= _GLIBCXX_NOEXCEPT=noexcept "_GLIBCXX_NOEXCEPT_IF(C)=noexcept(C)" _GLIBCXX_USE_NOEXCEPT=noexcept "_GLIBCXX_THROW(E)=" _GLIBCXX_CONSTEXPR=constexpr _GLIBCXX_USE_CONSTEXPR=constexpr _GLIBCXX14_CONSTEXPR=constexpr _GLIBCXX17_CONSTEXPR=constexpr _GLIBCXX20_CONSTEXPR=constexpr _GLIBCXX23_CONSTEXPR=constexpr _GLIBCXX17_INLINE=inline "_GLIBCXX_NODISCARD=[[nodiscard]]" _GLIBCXX_DEPRECATED= "_GLIBCXX_DEPRECATED_SUGGEST(A)=" _GLIBCXX17_DEPRECATED= _GLIBCXX20_DEPRECATED= _GLIBCXX_ABI_TAG_CXX11= _GLIBCXX_USE_CXX11_ABI=1 _GLIBCXX_HOSTED=1 _GLIBCXX_NOTHROW=
```

## Results

Packed with `pack --format jsonl --api-records` on `main` + the adapter. The
baseline is the same pack without `--api-records`.

| Criterion | Bar | ICU (C) | libstdc++ (C++) |
|---|---|---|---|
| Lookups in the top 5 | ≥ 80% of ~20 | 11 of 12 | 10 of 12 |
| Template headers kept | 100% | no templates | 1,063 of 1,063 verbatim |
| Member records | p99 ≤ 550 (Doxygen); max ≤ 3,000 | p99 506, max 2,359 | p99 138, max 200 |
| Container records | max ≤ 5,000 | max 925 | max 771 |
| Pack time | ≤ 2× baseline | 3.6 s vs 5.2 s | 7.8 s vs 9.7 s |

Lookups over both corpora: 21 of 24 (88%). Pack times are the median of 3.
The #168 brief asked for a member p99 of at most 300. ICU's 506 is over it,
so the maintainer set the Doxygen bound at 550 words after this run
([ADR-0009 amendment](../adr/0009-api-reference-symbol-records.md)); both
corpora together give 305.

Records:

- ICU: 19 pages split into 1,053 records (19 container, 1,034 member: 609
  functions, 217 defines, 91 typedefs, 73 enums, 44 variables), 43 pages
  kept whole. Total output 169,613 words; the baseline writes 182,177 words
  in 62 records, the largest 17,726 (`ucnv.h`).
- libstdc++: 193 pages split into 2,445 records (193 container, 2,252
  member: 1,817 functions, 306 typedefs, 99 variables, 24 defines, 6
  enums), 218 pages kept whole. Total output 209,160 words; the baseline
  writes 218,679 words in 411 records, the largest 9,962.

Every page kept whole is a member list (`*-members.html`, or a member list
whose long name Doxygen hashed), a source page, an index or list page, a
topic (group) page or a related page, except `std::optional` and
`std::pair` (see "Not covered").

### Record sizes

| Records | n | Median | p90 | p99 | Max |
|---|---|---|---|---|---|
| Member, ICU | 1,034 | 72 | 194 | 506 | 2,359 |
| Member, libstdc++ | 2,252 | 13 | 73 | 138 | 200 |
| Member, both | 3,286 | | | 305 | 2,359 |
| Container, ICU | 19 | 185 | 758 | 925 | 925 |
| Container, libstdc++ | 193 | 28 | 120 | 280 | 771 |

- ICU has 35 member records over 300 words: 23 functions, 11 enums and 1
  typedef. The functions are ICU's own API documentation: `ucnv_convertEx`
  (739 words), `ucnv_toUnicode` (550), `ucnv_fromUnicode` (540) describe
  every parameter, the error codes and the callbacks. The enums carry one
  documented enumerator per value: `UProperty` (2,359), `UErrorCode`
  (1,587), `UBlockCode` (1,495). Without the enums the ICU p99 is still 358
  words, and 383 for the functions alone, so splitting enumerators into
  records of their own would not bring it to 300.
- libstdc++ members are short: its doc comments are a sentence or two and a
  parameter list. 1,137 of the 2,252 members have no documentation of their
  own and keep only their signature (`HIDE_UNDOC_MEMBERS = NO` lists them).
- The largest container is `std::deque` (771 words): its member names by
  section and its inherited members by base.

### Lookups

`dograpper serve` over stdio, `search_chunks` with `k = 5`. A lookup hits
when the declaring member, or its container record, is in the top 5.
Baseline: the rank of the declaring page in the same pack without
`--api-records`.

| # | Corpus | Query | Expected member | Member rank | Container rank | Member words | Baseline page rank |
|---|---|---|---|---|---|---|---|
| 1 | ICU | `u_strlen length of a string` | `u_strlen` | 3 | - | 39 | 2 |
| 2 | ICU | `ucnv_open open a converter by name` | `ucnv_open` | - | - | 325 | 1 |
| 3 | ICU | `ucnv_fromUChars convert Unicode to codepage` | `ucnv_fromUChars` | 1 | 2 | 189 | 1 |
| 4 | ICU | `uset_contains code point in set` | `uset_contains` | 3 | - | 51 | 1 |
| 5 | ICU | `ucol_strcoll compare two strings` | `ucol_strcoll` | 1 | - | 88 | 1 |
| 6 | ICU | `uregex_open compile a regular expression` | `uregex_open` | 1 | - | 151 | 1 |
| 7 | ICU | `ucal_add add to a calendar field` | `ucal_add` | 1 | 4 | 164 | 1 |
| 8 | ICU | `unorm2_normalize normalize a string` | `unorm2_normalize` | 1 | 2 | 131 | 1 |
| 9 | ICU | `ubrk_next next boundary` | `ubrk_next` | 1 | - | 49 | 1 |
| 10 | ICU | `uloc_getDefault default locale` | `uloc_getDefault` | 1 | 3 | 57 | 2 |
| 11 | ICU | `U8_NEXT next code point UTF-8` | `U8_NEXT` (define) | 1 | - | 137 | 1 |
| 12 | ICU | `UErrorCode error codes` | `UErrorCode` (enum) | 3 | - | 1,587 | 4 |
| 13 | libstdc++ | `vector push_back add an element at the end` | `std::vector::push_back` | 1 | - | 85 | 3 |
| 14 | libstdc++ | `vector reserve capacity` | `std::vector::reserve` | 5 | - | 119 | 1 |
| 15 | libstdc++ | `list splice` | `std::list::splice` | 2 | - | 87 | - |
| 16 | libstdc++ | `map emplace_hint` | `std::map::emplace_hint` | 3 | - | 178 | 4 |
| 17 | libstdc++ | `unique_ptr reset` | `std::unique_ptr::reset` | 4 | 5 | 48 | 3 |
| 18 | libstdc++ | `shared_ptr use_count` | `std::__shared_ptr::use_count` | - | - | 21 | - |
| 19 | libstdc++ | `deque push_front` | `std::deque::push_front` | 1 | - | 76 | 5 |
| 20 | libstdc++ | `forward_list insert_after` | `std::forward_list::insert_after` | 3 | - | 109 | 2 |
| 21 | libstdc++ | `unordered_map rehash buckets` | `std::unordered_map::rehash` | 1 | - | 67 | 1 |
| 22 | libstdc++ | `optional value_or` | `std::optional::value_or` | page kept whole | | | 3 |
| 23 | libstdc++ | `priority_queue push` | `std::priority_queue::push` | 1 | - | 58 | 5 |
| 24 | libstdc++ | `reverse_iterator base` | `std::reverse_iterator::base` | 1 | 4 | 25 | 2 |

The baseline finds the declaring page for 22 of 24, but on ICU that page is
the whole header: `ucnv.h` is one 17,726-word record, so the member is
still buried in it. The three misses:

- `ucnv_open` (2): the record is 325 words, of which the converter-name
  rules take most; the shorter `ucnv_getDefaultName`, `ucnv_openPackage` and
  `ucnv_openCCSID` rank above it. This is the one miss in which a member's
  own size costs its rank.
- `use_count` (18): `std::shared_ptr` inherits it from `std::__shared_ptr`.
  The query says `shared_ptr`, so the constructors of `std::shared_ptr`
  fill the top 5; the `std::shared_ptr` container names `use_count` only
  under "inherited from std::__shared_ptr".
- `value_or` (22): the `std::optional` page keeps one record (see "Not
  covered"); that record is the third result.

The other large member in the set, `UErrorCode` (1,587 words), still ranks
3rd.

### Signatures

A separate script read every template header straight from the HTML with
regular expressions: the `div.memtemplate` blocks of each documentation
section and the `td.memTemplParams` cell of each summary row that holds a
member's anchor. On the pages that were split, 1,063 of 1,063 headers appear
verbatim in their member record, both headers of a member template of a
class template included. The ICU headers declare no templates.

## Reproduction

1. Run Doxygen 1.9.8 with each Doxyfile above, then copy only the `*.html`
   files of each `html/` directory into a fresh directory per project.
2. `dograpper pack <dir> -o <pack> --format jsonl --api-records`, and the same
   without `--api-records` for the baseline; time both.
3. Compute the size distribution from the JSONL `words`, `kind` and
   `symbol_kind` fields.
4. Drive `dograpper serve <pack>` over stdio with JSON-RPC `initialize`, then
   `tools/call search_chunks` (`k = 5`) for each query in the table.

## Not covered

- Doxygen 1.9.8 gives two overloads that differ only in their template
  constraints (`template<typename _Up, _Requires<...>>`) the same anchor.
  A page with a repeated anchor keeps one record, as rustdoc's does, so two
  records never share an id: here `std::optional` and `std::pair`.
- Topic (group) pages keep one record. In libstdc++ the free functions of a
  group (`std::make_shared`, `std::make_unique`, the iterator adaptors'
  helpers) are documented there, not on a file page.
- With `SOURCE_BROWSER = YES`, Doxygen adds "Definition at line N of file F"
  and the reference lists to each member; no measured corpus had them, so
  they stay in the member text.
- Related pages (`\page`), the main page and directory pages keep one
  record, as do the other Doxygen output languages (Java, Python, IDL,
  Fortran) and page kinds (interfaces, protocols, concepts, modules).
- A file page whose namespaces have no page of their own (libstdc++'s
  undocumented `std`) documents those members itself: its summary rows and
  sections are its member records, under their qualified names.
