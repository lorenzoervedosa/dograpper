# Javadoc ingestion case study

> Discovery, 2026-11-14. Question: is dograpper effective at turning a mirrored
> Javadoc site into LLM-ready context? Measured on `main` at `ead98ac`.

## Corpus

- Javadoc 25 output for a game's Java modding API, mirrored with HTTrack:
  1,948 files (1,906 HTML), 125 MB. 1,826 pages belong to the game's own
  packages, 42 to bundled third-party libraries. The rest are Javadoc auxiliary
  pages (`index-files/`, trees, search, deprecated list, constant values) and
  assets (`.js`, `.css`, fonts).
- Mostly signatures, very little prose. Only 6.9% of class pages have a class
  description. In the largest class, 22 of 499 methods (4%) have a doc comment.
- The mirroring tool saved 5 pages as the Cloudflare challenge interstitial
  instead of the real page (HTTP 403 with `cf-mitigated`). They were recovered by
  hand for this study.

## Target and criteria

- **Target:** a JSONL pack served through `dograpper serve` (MCP) to a coding
  agent that writes mods.
- **Questions the agent needs answered:**
  - exact API lookups, e.g. "the signature of `X.y`" or "the members of `X`";
  - code generation against the API.
- **Out of reach:** intent-style discovery, such as "how do I make zombies
  ignore the player". The prose needed for that is not in the corpus, so no
  packing tool can supply it.

## Verdict

**dograpper is not effective as-is for this target.**

What works: it cleans the corpus well. Scope can be set with a
`.docsignore`, navigation is stripped, each class becomes one record, and every
record carries its canonical URL once a manifest exists.

What fails:

- Retrieval over whole-class records misses exact lookups.
- The default extraction drops generic type parameters.
- The value-add features (dedup, cross-refs, readiness score, built-in eval)
  are neutral or harmful on an API reference.

| # | Criterion | Result | Evidence |
|---|---|---|---|
| 1 | Signature fidelity | Fail | Default extraction drops HTML-escaped `<…>` (#66). The scoped pack has 0 `static <T> …` method signatures, while `--no-extract` has 32. Example: `static <C> IsoPlayer findPlayer(...)` becomes `static IsoPlayer findPlayer(...)`. `--no-extract` keeps generics but brings back navigation and the per-page member table of contents (+15% words). Summary tables come out one cell per paragraph, so the return type and the method name land in separate paragraphs. |
| 2 | Granularity | Pass, with a caveat | One record per class page, never split. But a record is the whole page: median 243 words, 18 records over 5k words, 7 over 10k, and the largest is 38.7k. `get_chunk` on the largest player class returns 143k characters. |
| 3 | Noise | Pass with config | Unscoped, 38% of output words fall outside the in-scope class pages: `index-files/` alone is 32%, other auxiliary pages and out-of-scope packages 4.1%, `.js`/`.css` 1.9%. With the `.docsignore` below this drops to 0.6%. |
| 4 | Dedup safety | Fail | `--dedup both` removes override signatures declared by several classes (6 occurrences down to 1), along with genuine boilerplate (#68). The workaround is to run without dedup. |
| 5 | Retrieval | Fail | The built-in `eval` reports hit@5 = 50.5% and MRR = 0.283 over 1,899 golden pairs. But every golden question is "What does the documentation say about Class X?", so it only tests name lookup. Real lookups through `serve` (table below) found the expected class in the top 5 for 1 of 5 API lookups. |
| 6 | Fits the target | Pass | 1,690 records, 858k words, ~3.0M tokens (cl100k). Pack time 65 s. That size is fine for an MCP index. |

Real lookups (`search_chunks`, k=5, scoped pack):

| Query | Expected page | Rank |
|---|---|---|
| `IsoPlayer getInventory` | `IsoPlayer` or `IsoGameCharacter` (declares the method) | not in top 5 |
| `InventoryItem getWeight` | `InventoryItem` | not in top 5 |
| `ItemContainer AddItem` | `ItemContainer` | 4 |
| `getPlayer global Lua function` | `LuaManager.GlobalObject` | not in top 5 |
| `add item to player inventory` | `ItemContainer` | not in top 5 |
| `make zombie ignore player` | (intent, no expected page) | irrelevant hits |

## Workaround configuration

This is what works today with no code changes.

`.docsignore`:

```gitignore
org/
index-files/
script-files/
resource-files/
*.js
*.css
*-tree.html
index-2.html
allclasses-index.html
allpackages-index.html
deprecated-list.html
constant-values.html
serialized-form.html
help-doc.html
search.html
```

`index-2.html` is an HTTrack artifact: `/` is saved as `index.html` and
`/index.html` as `index-2.html`, so the overview page appears twice.

```bash
dograpper pack <mirror> -o ./pack --format jsonl --context-header --score \
  --ignore-file ./.docsignore --manifest ./manifest.json
dograpper serve ./pack
```

Do not use `--dedup` (#68) or `--cross-refs` (#67). `--cross-refs` writes
markers into the `id` and `source` fields and inside identifiers, and did not
finish within 10 minutes on the full corpus.

**Source URLs.** `pack` fills the `url` field only from a dograpper download
manifest, and an HTTrack mirror has none. A manifest built from HTTrack's
`<!-- Mirrored from <url> -->` markers, holding only `url`, `size_bytes` and
`local_path` per file, gave all 1,690 records a URL with no code change. The
markers on pages recovered by hand come from the browser:
`<!-- saved from url=(N)<url> -->`.

## Issues filed

| Issue | Kind | Summary |
|---|---|---|
| #66 | bug | Default extraction drops HTML-escaped angle brackets (generics, markup examples) |
| #67 | bug | `--cross-refs` annotates the serialized chunk file and corrupts record metadata |
| #68 | enhancement | Block dedup removes per-page API members that repeat across pages |
| #69 | enhancement | Detect bot-challenge pages in `pack` input instead of packing them silently |

## Gaps not filed

| Gap | Size | Notes |
|---|---|---|
| G1. `pack` ingests `.js`/`.css` as documentation | S | 13 such files in this corpus. `member-search-index.js` alone is 1.1% of words. |
| G2. No ignore preset for Javadoc | S | The `.docsignore` above. |
| G3. No API-reference-aware extraction | M–L | Would mean one record per member (or per class section), compact one-line signatures, summary and details merged, type parameters kept. This gap decides criteria 2 and 5. It is a new product direction and needs its own design pass. |
| G4. Breadcrumb holds only the page `h1` | M | Section (`h2`) and member (`h3`) headings never reach the context header. |
| G5. Golden Q&A asks only about the deepest heading | M | No member or parameter questions. On this corpus 27 auxiliary pages all share the heading "Index", so they yield 27 identical questions. |
| G6. Readiness score grades empty and non-documentation records `A` | S | Overlaps #69. |
| G7. BM25 over whole-class records ranks short pages above the page that declares the member | — | Hypothesis, not isolated: BM25 length normalization (`b = 0.75`) against records up to 38.7k words. Resolved by G3. |
| G8. Manifest URL lookup depends on the `pack` input directory | S | From reading the code: `local_path` must equal the path relative to the pack input. Packing a subdirectory of the download output therefore matches nothing, and the `try/except: pass` around the lookup in `commands/pack.py` (step 7c) hides it. |

Two requirements for the HTTrack-style downloader under development were handed
to that work:

1. Record the fetched URL and the saved `local_path` for every file in the
   manifest, rather than rebuilding the URL from the path.
2. Do not save challenge responses as pages.

## Alternatives

A structured API dump (JSON per class and member), where one exists, would beat
HTML extraction for exact lookups, because it is already member-level. For a
coding agent, plain per-class text files plus `grep` on exact identifiers
probably also beat BM25 over whole-class records. Neither alternative was
measured.

## Reproduction

1. Pack the mirror with the command above.
2. Build the manifest with a throwaway script that collects the
   `Mirrored from` / `saved from url=` marker of each HTML file.
3. Drive `dograpper serve` over stdio with JSON-RPC `initialize`, then
   `tools/call search_chunks` for each query in the lookup table.
4. Compute generic-signature counts and noise shares from the JSONL `words` and
   `content` fields.
