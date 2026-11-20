# TypeDoc API records: acceptance run

Acceptance run of the TypeDoc adapter (`src/dograpper/utils/api_reference/typedoc.py`)
against the bar in [ADR-0009](../adr/0009-api-reference-symbol-records.md), for
[#75](https://github.com/lorenzoervedosa/dograpper/issues/75) phase 4. Measured on
2026-11-19.

## Corpus

- **Source:** `@tanstack/query-core` 5.108.1, the `src/*.ts` files shipped in its
  npm tarball (`npm pack`, no install scripts run). The package has no
  dependencies, so its sources type-check on their own.
- **Generator:** TypeDoc 0.28.20 (TypeScript 6.0.3), default theme, generated
  locally from `src/index.ts`, so no site was crawled. Options: `--readme none
  --disableGit --sourceLinkTemplate 'https://example.com/query-core/{path}#L{line}'
  --skipErrorChecking`. Source links stay on, as in TypeDoc's default, so every
  page has its "Defined in" lists. Only the HTML pages were packed; TypeDoc's
  `assets/` directory was left out.
- **Same corpus without source links:** a first run used `--disableSources`.
  Its 660 records are identical to the final run's, because the adapter drops
  the "Defined in" lists. The only difference is the `type_alias` spelling,
  renamed between the two runs.
- **Size:** 155 pages. One entry point, so the breadcrumb starts at the symbol
  (`QueryClient`, not `query-core.QueryClient`). The corpus has 10 classes,
  58 interfaces, 59 type aliases, 15 functions and 11 variables, plus the
  index and the hierarchy page.

## Results against the bar

| Criterion (ADR-0009) | Bar | Measured | Pass |
|---|---|---|---|
| Lookups that hit the declaring member or its container record in the top 5 | ≥ 80% of ~20 | 22 of 24 (92%); the member record itself in 21 of 24 | yes |
| Sampled signatures that keep their type parameters | 100% | 238 of 238 | yes |
| Member records, p99 | per generator (ADR amendment) | 216 words | ≤ 250, proposed below |
| Member records, max | ≤ 3,000 words | 301 words | yes |
| Container records, max | ≤ 5,000 words | 665 words | yes |
| Pack time against the baseline | ≤ 2× | 0.20× | yes |

### Pages and records

- 153 of 155 pages were split into 658 records: 73 container and 585 member.
  The two pages kept whole were the index and the hierarchy page, both with
  the reason `TypeDoc page, not an API page`.
- `symbol_kind` counts: 352 `property`, 138 `method`, 59 `type_alias`,
  58 `interface`, 15 `function`, 11 `variable`, 10 `class`, 10 `constructor`
  and 5 `accessor`.

### Record sizes

| Records | n | Median | p90 | p99 | Max |
|---|---|---|---|---|---|
| Member | 585 | 22 | 93 | 216 | 301 (`notifyManager`) |
| Container | 73 | 113 | 197 | 665 | 665 (`InfiniteQueryObserverOptions`) |

- The largest member records are methods with long generic signatures. TypeDoc
  breaks a long signature over several lines with one type parameter per line,
  then lists the type parameters and the parameters again in the doc comment,
  with their defaults and their own docs. `QueryClient.query` has 290 words:
  six type parameters, five of them with defaults, and five paragraphs of doc
  comment.
- `notifyManager` (301 words) is a variable whose object type has six
  documented functions, so its one member record holds all of them.
- 53 of the 585 member records are over 100 words: 41 methods, 6 functions,
  4 properties and 2 variables. 2 are over 250 words.
- The largest containers are option interfaces that inherit many members.
  Their records list the inherited names by base.
- In the baseline (one record per page, no `--api-records`), the largest
  record was `classes/QueryClient.html` with 3,964 words. The next two were
  `InfiniteQueryObserverOptions` with 2,609 words and `QueryObserverOptions`
  with 2,356.

### Lookups

The 24 lookups were written before the run, from the package's API. Each one
names an API member the way a user asks for it. Search went through the
`search_chunks` tool that `dograpper serve` registers, with `k` = 5, on the
same pack. Columns:

- Member: the rank of the member record.
- Container: the rank of its container record. "—" means not in the top 5 or
  no container record: a function or variable page is one member record.
- Baseline: the rank of the page in a pack without `--api-records`.

| Query | Target | Member | Container | Baseline |
|---|---|---|---|---|
| `QueryClient invalidateQueries` | `QueryClient.invalidateQueries` | 1 | 4 | 4 |
| `setQueryData update cached data` | `QueryClient.setQueryData` | 1 | — | 2 |
| `getQueryData read cached data for a query key` | `QueryClient.getQueryData` | 1 | — | 1 |
| `prefetchQuery` | `QueryClient.prefetchQuery` | 1 | 2 | 2 |
| `fetchInfiniteQuery pages` | `QueryClient.fetchInfiniteQuery` | — | — | 2 |
| `ensureQueryData return cached data or fetch` | `QueryClient.ensureQueryData` | 1 | — | 1 |
| `cancel outgoing queries` | `QueryClient.cancelQueries` | 1 | — | 3 |
| `removeQueries remove queries from the cache` | `QueryClient.removeQueries` | 1 | — | 3 |
| `resetQueries reset to initial state` | `QueryClient.resetQueries` | 2 | — | — |
| `how many queries are fetching isFetching` | `QueryClient.isFetching` | 1 | 5 | 4 |
| `QueryCache find query by key` | `QueryCache.find` | 5 | — | 1 |
| `MutationCache findAll mutations` | `MutationCache.findAll` | 1 | 3 | 1 |
| `QueryObserver refetch` | `QueryObserver.refetch` | 3 | — | 1 |
| `InfiniteQueryObserver fetchNextPage` | `InfiniteQueryObserver.fetchNextPage` | 2 | 1 | 1 |
| `MutationObserver mutate` | `MutationObserver.mutate` | — | 2 | 1 |
| `hashKey hash a query key` | `hashKey` | 1 | — | 1 |
| `dehydrate cache state for server rendering` | `dehydrate` | 3 | — | 2 |
| `hydrate dehydrated state into the cache` | `hydrate` | 2 | — | 1 |
| `FocusManager setFocused` | `FocusManager.setFocused` | 1 | 2 | 1 |
| `OnlineManager isOnline` | `OnlineManager.isOnline` | 1 | 2 | 1 |
| `replaceEqualDeep structural sharing` | `replaceEqualDeep` | 2 | — | 1 |
| `refetchOnWindowFocus option` | `QueryObserverOptions.refetchOnWindowFocus` | 2 | — | 2 |
| `staleTime option` | `QueryObserverOptions.staleTime` | — | — | 4 |
| `isCancelledError` | `isCancelledError` | 1 | — | 1 |

The two misses lose to other records that repeat a query word:

- `fetchInfiniteQuery pages` returns `QueryClient.infiniteQuery` and the
  `InfiniteData.pages` records.
- `staleTime option` returns the `StaleTime` type alias and the `staleTime`
  members of `FetchQueryOptions` and `QueryExecuteOptions`, which document the
  same option.

A third query, `MutationObserver mutate`, misses its member record, but the
`MutationObserver` container record ranks 2.

The baseline finds the right page more often (23 of 24) because TypeDoc
already writes one page per class, interface or function. On a class page,
though, what it returns is the whole page: `QueryClient` is one record of
3,964 words. With `--api-records`, the same lookup returns the member record,
median 22 words.

### Type parameters

Every `div.tsd-signature` that has a type-parameter list was checked on every
split page. The check covers own members and the function, variable and type
alias pages; inherited members are only listed by name on the container (ADR-0009),
so their signatures were left out. The signature text was taken from the raw
HTML with whitespace and spacing around punctuation collapsed. Each one must
appear in a record of the same page. 238 of 238 did.

### Pack time

Each figure is the best of 3 runs of `dograpper -q pack <corpus> -o <out>
--format jsonl`, with and without `--api-records`, while other sessions' test
suites loaded the machine. The final run gave 3.05 s for the baseline and 0.60 s
with the flag (0.20×). Three earlier runs on the variant without source links
gave 0.18× to 0.21×. Split pages skip content extraction, which is most of the
baseline's time on these pages: each one carries TypeDoc's full navigation
sidebar.

## Member record p99 bound

Proposed TypeDoc bound: **p99 ≤ 250 words**. The measured p99 is 216, with a
max of 301.

- TypeDoc repeats each type parameter in the signature and again in the
  "Type Parameters" list, and each parameter in the "Parameters" list with its
  own doc. Generic TypeScript APIs carry many type parameters with defaults:
  `fetchInfiniteQuery` has five. Dropping the lists would drop the
  per-parameter docs and defaults.
- The larger records did not hurt retrieval. 14 of the 24 lookup targets are
  member records over 100 words. For 12 of them, the member record itself
  ranked in the top 5. For one more (`MutationObserver.mutate`), the container
  record did.

## Markup versions

The adapter covers TypeDoc 0.28 only. The corpus and the fixture were
measured on 0.28.20; 0.28.0 was checked on the fixture only.

- **0.28.0 and 0.28.20:** the fixture sources give the same 41 records from
  both. Four texts differ, because of TypeDoc's own output and not the markup:
  0.28.0 orders unions the other way (`undefined | V`) and leaves out the
  type parameter docs of constructors.
- **0.25, 0.26 and 0.27:** member anchors sit on an `a.tsd-anchor` before the
  `h3`, and the breadcrumb starts at the project (`fixture.shapes.apply`) with
  no `aria-current` crumb. 0.25 and 0.26 also leave parameter types out of the
  signature. Every API page from these versions is kept whole, with the reason
  `unsupported TypeDoc markup: a breadcrumb without the current page`.
- **Later versions:** TypeDoc writes no version into its pages, so the
  `aria-current` gate rejects only the older layout. A later TypeDoc that keeps
  this markup is split without a warning. Re-run this measurement before
  claiming it.
- Not measured: other themes, a `lang` other than English (the `h1` kind words
  are translated), and the `router` option's other layouts.

## Reproduction

1. In a scratch directory outside the repository, run `npm install
   typedoc@0.28.20 typescript`.
2. Run `npm pack @tanstack/query-core@5.108.1` and extract the tarball into its
   own empty directory.
3. Write a `tsconfig.json` outside the package directory whose `files` names
   the package's `src/index.ts`, with `skipLibCheck` and `lib: ["ES2022",
   "DOM"]`. Then run `typedoc --tsconfig <it> --entryPoints <package>/src/index.ts
   --out <html> --readme none --disableGit --sourceLinkTemplate
   'https://example.com/query-core/{path}#L{line}' --skipErrorChecking`.
4. Copy the `*.html` files, but not `assets/`, into a corpus directory. Pack it
   twice with `uv run dograpper -q pack <corpus> -o <out> --format jsonl`: once
   with `--api-records` and once without.
5. Run the lookups in the table through `build_tools(...)["search_chunks"]`
   with `k` = 5, as `tests/test_api_reference_typedoc.py` does.
