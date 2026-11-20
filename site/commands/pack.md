# dograpper pack

Processes and groups files into chunks optimized for LLM ingestion.

```bash
dograpper pack <input_directory> -o <output_directory> [options]
```

## Pack internal pipeline

Operation order (each stage reads the output of the previous one):

```
list files → apply .docsignore → skip bot-challenge pages
           → skip saved HTTP error pages
           → skip MediaWiki redirect aliases of packed pages
           → --api-records? split API reference pages into records
             (those pages skip extraction and dedup)
           → --no-extract? yes: full HTML / no: extract
           → --dedup → --bundle? cap max-chunks/max-words-per-chunk
           → --strategy (size|semantic) → boundary-aware chunking
           → --score? compute readiness
           → --cross-refs? resolve links
           → --format (md|txt|jsonl) + --context-header? inject → write
             (--cross-refs markers go into each page's content;
              --layout page: one file per page under pages/ + INDEX.md)
           → --bundle? generate guide
```

## Smart extraction (on by default)

Before packing, dograpper extracts only the main content of each HTML.
Preference order:

1. Semantic selectors (`<main>`, `<article>`, `[role=main]`).
2. Text density scoring (best `<div>` by text/tags ratio).
3. Fallback: full HTML with `<script>`, `<style>`, `<nav>`, `<footer>`
   stripped.

Blacklist removes: navigation, breadcrumbs, sidebars, table of
contents, "copy to clipboard" buttons, version banners, cookie and
announcement banners, feedback widgets, edit-on-github links. Use
`--no-extract` to keep the full HTML.

MediaWiki pages (`<meta name="generator" content="MediaWiki ...">`) lose
their wiki chrome first: navigation boxes (`navbox`), section edit links
(`mw-editsection`) and maintenance boxes (an `mbox` with a
`mw-customtoggle-mbox-*` toggle: stub, outdated, "help update") are cut from
the page before the steps above. Note boxes, which have no toggle, stay.
The version banner (`This page was last updated for an older version of the
current build (42.10.0).`) leaves the text too and becomes page metadata,
`version` and `version_status`, in the context header; without a banner, the
first hidden `Version X` category gives `version`. A version box whose
wording is not one of the three known ones stays in the text. Pages from any
other generator are not touched. Measured on MediaWiki 1.43 (Citizen skin).

A MediaWiki redirect alias is a page saved through a redirect ("Redirected
from ..."): MediaWiki serves it with its target's content and page name
(`wgPageName`). When the target page is packed too, the alias is skipped
before extraction, listed once on stderr and counted as `Redirect aliases: N`
(in `Files excluded`). An alias whose target is not in the input is that
page's only copy and is packed; of several such aliases of one target, the
first in path order is packed.

Code blocks (`<pre>`) keep their line breaks and indentation, with or
without extraction. `md` writes each one as a fenced block whose language
comes from a `mw-highlight-lang-*`, `language-*`, `lang-*` or Sphinx
`highlight-*` class on the `<pre>`, a `<code>` inside it or the nearest
enclosing `<div>` that names one (` ```lua `). A bare fence is written when
none is declared or the class is a placeholder (`highlight-default`,
`highlight-none`, `language-none`). The fence grows past any backtick run in
the code. `txt` and `jsonl` carry the code without the fence. Dedup and
chunking treat a code block as one unit, blank lines included.

## Markdown structure (`md`)

`md` writes the structure of each HTML page as Markdown. `txt` and `jsonl`
keep plain text, unchanged.

- `h1`–`h6` become `#`–`######` lines.
- A link becomes a reference link: the line holds `[text][n]`, and the page
  ends with one `[n]: target` line per distinct target, numbered by first use
  in the page, so a line is as long as its visible text however long its
  targets are. The target is the `href` as the page wrote it: a
  relative target names a file of the mirror (`Lua_(API).html`; in the
  [page layout](#page-layout---layout-page), a packed page's file), an absolute
  one is kept. A target holding parentheses is written as `<...>`; spaces,
  `<`, `>`, `\` and control characters are percent-encoded. A link to the same
  page (`#anchor`, or `page.html#anchor` as mirrors rewrite it), with no
  target, or with a scheme other than `http`, `https` or `mailto`
  (`javascript:`, `data:`...) keeps only its text. So does a link inside code
  (`<code>`, `<pre>`, a Javadoc `div.member-signature`), so a signature reads
  as the source shows it: `public ItemContainer getInventory()`.
- `ul` / `ol` items become `-` / `N.` lines (an `ol`'s `start` is kept), with
  nested lists indented under their item. An item that holds a block (a
  heading, a `div`, a table or code, as Javadoc's member sections do) is
  written as its blocks, without a marker.
- A table becomes a pipe table with one line per row. Its first row is the
  header, and `|` inside a cell is escaped. A one-line `<pre>` in a cell
  becomes a code span, and a list in a cell is written inline. A table whose
  cell holds multi-line code, a heading or another table is written one cell
  per paragraph instead, so the code block keeps its lines.
- In the chunk layout each page section ends with its own definitions,
  numbered from 1, so the numbers repeat across the pages of one chunk file: a
  reference resolves to the definitions that end its section, the first `[n]:`
  line after it. When `--context-header` splits a page into several sections,
  each section ends with the definitions of the references it holds, under the
  page's numbers, so a section read alone resolves all its links. A Markdown
  renderer resolves a repeated number to the first definition of the file, so
  render pages from the page layout (`--layout page`), where a file is a page.
- Word counts leave the markup out: heading and list markers, table pipes,
  the delimiter row and the link definitions are not words (context headers,
  `INDEX.md`, `llm-readiness.json`). `--max-words-per-chunk` measures each page's plain
  text, as for `txt`, so both formats put pages in the same chunks.
- Dedup and chunking treat a list or a table as one block, so `--dedup`
  removes a table repeated on several pages as a whole. `--dedup` never
  removes a page's definitions, and it compares links by target, not by
  number, so it removes the same blocks as it would with inline links.
- `--cross-refs` writes its marker after the link it labels, never in a
  definition: `[Item][2] [-> docs_chunk_02]`.

## Deduplication (`--dedup`)

Removes text blocks duplicated across files (headers, footers,
disclaimers, navigation). Three modes:

- **`exact`** — MD5 hash of a normalized block (lowercase + collapsed
  whitespace). Zero false positives.
- **`fuzzy`** — 64-bit SimHash + Hamming distance ≤ `--dedup-threshold`.
  Detects trivial variations (a navigation box with one extra link).
- **`both`** — exact first (cheap), then fuzzy on the remainder.

Blocks with fewer than 10 words are ignored (prevents false positives
on repeated `<h1>`). The first occurrence (alphabetical order) is
always preserved.

A match never removes a block when:

- **it is on the same page** (any mode). A block repeated inside one
  page, such as two parameters that share a description, is page
  content, not boilerplate.
- **it starts with a different token** (`fuzzy`). The leading token is
  the first token holding a letter or digit, so list bullets are
  skipped: `base:hardcover Book, …` and `base:hollowbook Book, …` are
  different entries.
- **only numbers differ** (`fuzzy`). Tokens holding digits (versions,
  dates, counts) are the page's own data: `… build (42.5.1).` and
  `… build (42.17.0).` are both kept.

The summary's `Matches kept` line counts the blocks each rule kept. A
block identical on several pages is still kept only on the first, even
when it is per-page metadata. A MediaWiki version banner never reaches
dedup: it is header metadata (see Smart extraction), so with
`--context-header` every page keeps its `version`.

A page recognised as an API reference (the generators
[`--api-records`](#api-reference-records---api-records) supports) is never
deduplicated, with or without that flag: its blocks are neither removed nor
used as the first-seen copy that removes blocks elsewhere, so a signature
that several types declare, such as an override, stays on every page
([#68](https://github.com/lorenzoervedosa/dograpper/issues/68)). The summary
reports `Pages exempted: N (API reference)`, and `--dry-run` reports
`Dedup pages exempted: N (API reference)`. API reference pages from a
generator without an adapter (TypeDoc, rustdoc, Doxygen) are still
deduplicated: run without `--dedup` on those corpora.

## Context header (`--context-header`)

Injects structured metadata in the `dograpper-context-v1` format
(JSON inside an HTML comment) at the top of each file within the chunk:

```html
<!-- dograpper-context-v1
{
  "source": "flask.palletsprojects.com/en/stable/quickstart/index.html",
  "url": "https://flask.palletsprojects.com/en/stable/quickstart/",
  "chunk_index": 2,
  "total_chunks": 5,
  "word_count": 4820,
  "context_breadcrumb": ["Quickstart", "Routing"],
  "llm_readiness": {"score": 0.92, "grade": "A", "noise_ratio": 0.08},
  "schema_version": "v1"
}
-->
```

Optional fields (`url`, `context_breadcrumb`, `llm_readiness`, the MediaWiki
page metadata `version` and `version_status`, written after `url`, and
`chunk_index` / `total_chunks`, written only for a file split into several
sub-chunks) are omitted when not available (they never appear as `null`). A
`>` in a value is written as `\u003e`, so a value holding `-->` cannot close
the comment. Full spec:
[docs/schema-v1.md](../reference/schema-v1.md).

In the page layout (`--layout page`) each page file gets exactly one header,
at line 1, with the page `title` as its first field (the same title as in
`INDEX.md`) and no `chunk_index`, `total_chunks` or `context_breadcrumb`.

`url` comes from the file's entry in the download manifest (`--manifest`),
matched on the file's path in the mirror (`local_path`). This also works when
`INPUT_DIR` is a subdirectory of the download output; a file that matches
several entries that way gets no `url` and is listed in the summary. Without
an entry, an HTML page's URL is read from the marker an offline copy left
in its head, so mirrors made by other tools get URLs too:

- HTTrack: `<!-- Mirrored from <url> by HTTrack Website Copier/... -->`.
  HTTrack 3.49 and older write the URL without its scheme; `http://` is
  assumed, as HTTrack itself does for a bare host.
- A browser's "Save page as": `<!-- saved from url=(NNNN)<url> -->`, where
  `NNNN` must equal the URL's length. `saved from url=(0014)about:internet`,
  the Windows zone marker many sites ship in their HTML, names no URL and is
  ignored.

Only the first 8 KiB of the page, up to `<body>`, is scanned. A marker is page
content, so its URL is checked before use: `http` or `https`, at most 2,048
characters, RFC 3986 characters only (no whitespace, control characters,
quotes, angle brackets or non-ASCII), a hostname, no credentials, a numeric
port. A rejected marker, or two markers that disagree, leave `url` out. The
pack summary counts the URLs by source and lists the files left without one
(the first 10; all of them with `--verbose`):

```
  Source URLs:     0 from manifest, 166 from page markers, 2 without
  Rejected markers: 1 invalid, 0 conflicting
    bad.html: invalid page marker
    data.json: no manifest entry or page marker
```

## Cross-references (`--cross-refs`)

Extracts internal links from HTML, resolves relative paths, maps each
target to the chunk where the file was packed, and generates
`cross_refs.json` with `references_to`, `referenced_by`, and `links`
lists per chunk. As each chunk is written, every page's content (each of
its records, when a long page is split) gets a `[-> chunk_id]` marker after
the first whole-word occurrence of the text of each link that page holds
(never inside a dotted identifier such as `pkg.Item.Item`), letting LLMs
navigate between chunks. Record
metadata (JSONL `id`/`source`, the file index, context headers) is never
annotated.

Links pointing to files excluded via `.docsignore` appear as
`unresolved` (counted in the summary).

## JSONL format (`--format jsonl`)

Each chunk becomes a `.jsonl` file where every line is an object per
source file. Ideal for RAG pipelines with their own downstream chunking.

Schema (required fields in **bold**, optional in italics):

- **`id`** — unique record identifier
- **`source`** — relative path of the original file
- **`words`** — word count
- **`content`** — extracted text
- **`schema_version`** — `"v1"`
- *`breadcrumb`, `chunk_index`, `total_chunks`* (with `--context-header` or `--score`)
- *`url`* (with `--context-header`, from a matching manifest entry that has a
  `url` or the page's HTTrack / saved-from marker — `--score` alone never
  populates it)
- *`readiness_grade`* (with `--score`)
- *`symbol`, `kind`, `symbol_kind`, `container`, `generator`* (with
  `--api-records`, on API records only; see below)
- *`version`, `version_status`* (with `--context-header` or `--score`, for a
  MediaWiki page that states its version; see Smart extraction)

Field names diverge from the header format for word count, breadcrumb and
readiness — see the full field-by-field spec, including the JSONL/header
mapping table, in [docs/schema-v1.md](../reference/schema-v1.md).

## API reference records (`--api-records`)

An API reference page holds many symbols, and one record per page buries a
member's signature in a class-sized record. With `--api-records` (config key
`api_records`), each page that a generator adapter recognises is written as
one **container record** plus one **member record** per documented member
([ADR-0009](https://github.com/lorenzoervedosa/dograpper/blob/main/docs/adr/0009-api-reference-symbol-records.md)):

```bash
dograpper pack ./javadoc-mirror -o ./pack --format jsonl --api-records --context-header
dograpper serve ./pack   # search_chunks now ranks member records
```

- **Javadoc**: javadoc 25 type pages (`<meta name="generator"
  content="javadoc/ClassWriter">`).
- **Sphinx autodoc**: Python domain pages, measured on Sphinx 9.1 and 9.2
  with the alabaster and furo themes. Sphinx writes no generator meta, so a
  page is recognised by its object markup (`<dt class="sig sig-object py">`)
  inside the `role="main"` region. The page's first record is its **module**
  container record (the module of its first module-level object): the page
  text outside the objects (title, module docstring, usage prose) and the
  names of the top-level objects. Each class and exception gets a container
  record (signature, `Bases:`, docstring, member names); each function,
  method, property, attribute and data gets a member record
  (`packaging.version.Version.is_prerelease`, every signature with its
  annotations, overloads included, then the docstring and its fields). The
  anchor is the object's HTML id (`#packaging.version.parse`). A page with a
  `:no-index:` object or an object type outside those keeps one record.
- **rustdoc**: rustdoc 1.96 pages (`<meta name="generator" content="rustdoc">`
  and `data-rustdoc-version="1.96.…"`; the page kind comes from
  `<body class="rustdoc struct">`). rustdoc writes one page per symbol:
  - A struct, enum, union, trait or type alias page is a container record:
    the declaration, the doc comment, the member names, then the `impl`
    headers of its trait implementations, auto trait implementations and, on
    a trait, implementations on foreign types and implementors. The members
    of those implementations and the blanket implementations are dropped,
    since their docs usually repeat the trait's.
  - Each field, variant, member of an inherent `impl` block (method,
    associated constant or type) and trait member gets a member record
    (`itertools::Itertools::interleave`):
    the `impl` block's header with its bounds (`impl<T: Ord> Boxed<T>`), the
    signature, the deprecation note and the doc comment. The anchor is the
    rustdoc id (`#method.interleave`, `#structfield.items`, `#variant.Both`).
  - A crate or module page is a container record: its doc comment and its
    symbols' names by section (`Structs: Boxed`), without the descriptions.
  - A function, constant, static or macro page is one member record, under
    the page's own id (`NN_path`), with the module as its container.
  - `all.html`, help and source pages, redirect stubs (no generator meta),
    pages from another rustdoc version and other page kinds (primitive,
    keyword, derive or attribute macro) keep one record, as does a page with
    a section that was not measured, such as `Methods from Deref<Target = …>`.
- **TypeDoc**: TypeDoc 0.28 pages (default theme, English), one page per
  symbol. TypeDoc writes no generator meta either, so a page is
  recognised by its title block (`<div class="tsd-page-title">`); the
  qualified name is its breadcrumb path (`QueryClient`, `shapes.Box`). A
  module, namespace, class, interface or enum page (or a type alias page
  whose type has members) gets a container record: the title with its type
  parameters (`Class Box<T>`), comment, type parameters, hierarchy and
  implemented interfaces, the member names by group (`Methods: ...`) and the
  inherited members by base (`Inherited from Box: ...`). Each own member
  gets a member record (`QueryClient.invalidateQueries`, its flags such as
  `Static Readonly`, every signature with its type parameters, the doc
  comment, parameters, returns and notes; the "Defined in" source locations
  are dropped), anchored at the member's HTML id (`#invalidatequeries`).
  A function, variable or type alias page is one member record with id
  `NN_path` and `container` the module or namespace above it (none when
  the breadcrumb starts at the symbol, as in a single-entry-point project).
  The readme, the hierarchy page, the project index and pages from TypeDoc
  0.25-0.27 (their breadcrumb marks no current page) keep one record.
- **Container record** (`id` `NN_path` for the page's main container,
  `NN_path#anchor` for a Sphinx class or exception): qualified name and kind,
  inheritance, implemented interfaces and known subclasses, signature,
  description, the declared member names, and the "inherited from" lists.
  Summary tables are dropped.
- **Member record** (`id` `NN_path#anchor`; `NN_path` for a rustdoc
  function, constant, static or macro page and a TypeDoc function, variable
  or type alias page): the qualified name
  (`zombie.characters.IsoGameCharacter#getInventory()`,
  `packaging.version.parse`, `itertools::Itertools::interleave`), the full
  signature with its type parameters, the doc comment and the notes
  (Overrides, Specified by, Parameters, Returns, Throws). `url` ends with the member's anchor; `breadcrumb` is
  `[container, member]`.
- **Other pages** (prose, package summaries, other generators, or a type page
  whose markup differs from the measured one) keep one record each. They are
  listed in a warning with the reason (the first 10; all with `--verbose`) and
  counted in the summary's `API records:` line.
- Split pages skip content extraction and `--dedup`, so a member is never
  removed for repeating on another page. `--for-queries` and `--delta` work
  per page, and all records of a page land in that page's chunk.
  `--cross-refs` markers go into each record's content; `--score` grades the
  chunk as before.
- Usage error (exit 2) with `--format md` or `txt`, with `--bundle notebooklm`
  and with `--layout page`.

Field list: [docs/schema-v1.md](../reference/schema-v1.md#api-records---api-records).

## LLM Readiness Score (`--score`)

Per-chunk 0–1 score derived from three weighted metrics:

| Metric | Weight | What it measures |
|---|---|---|
| `noise_ratio` | 40% | Share of the source words that extraction removed as boilerplate (the less removed, the higher the score) |
| `boundary_integrity` | 30% | All or nothing: the chunk holds no unclosed fenced code block and no unbalanced `<pre>` |
| `context_depth` | 30% | Deepest heading level in the chunk: 2 or deeper scores in full, 1 scores half, no heading scores 0 |

Final grade:
- **A** — score ≥ 0.8 (ready for direct use)
- **B** — 0.5 ≤ score < 0.8 (usable, consider refining extraction)
- **C** — score < 0.5 (review `.docsignore` or run `--dedup`)

A chunk whose extracted content is empty (0 words) is always graded **C**
with score 0, regardless of the other metrics.

Results are saved to `llm-readiness.json`. When combined with
`--context-header` or `--format jsonl`, the grade is injected into
headers/records.

## Readiness report (`--report`)

Visual companion to `--score` (implied if absent): writes a
self-contained `readiness-report.html` in the output directory and
prints a colorized worst-first summary after the pack summary.

The report makes each penalty tangible:

- **noise** — per-page before/after word counts plus samples of the
  blocks removed by extraction (first 5 per page, in document order);
- **boundary** — the line and snippet of each broken ` ``` ` fence or
  unmatched `<pre>` tag, attributed to its source page (line numbers
  are relative to that page's extracted content);
- **context depth** — the headings found per page (or the absence of
  headings as the cause).

Chunks are sorted worst-first (C grades on top) so calibration effort
goes where it pays off. Incompatible with `--dry-run`: the report needs
the final chunk text.

```bash
dograpper pack ./docs -o ./chunks --report
```

## Presets (`--bundle`)

Shortcuts for common combinations.

- **`notebooklm`** — hard ceiling, not a default: caps `max-chunks` at
  50 and `max-words-per-chunk` at 500,000 regardless of what the CLI
  flags request (`--max-chunks 100 --bundle notebooklm` still yields
  50 chunks). Does not set `strategy` or `format`. It also redistributes
  whole files across the chunks to even out their word counts, so a corpus
  with no more files than the chunk cap gets one chunk per file.
- **`rag-standard`** — no restrictions; sets nothing.

Both presets generate `IMPORT_GUIDE.md` alongside the chunks.

| Preset | `max-chunks` cap | `max-words-per-chunk` cap | Produces |
|---|---|---|---|
| `notebooklm` | 50 | 500,000 | `IMPORT_GUIDE.md` |
| `rag-standard` | — | — | `IMPORT_GUIDE.md` |

Example combining preset with score:

```bash
dograpper pack ./docs -o ./chunks --bundle notebooklm --context-header --score
```

## Dry-run (`--dry-run`)

Simulates without writing. Prints: file count, word count, chunk
projection, top 10 by size, warnings. Use it to calibrate parameters
before the final pack.

## Chunking strategies

- **`size`** (default) — walks files in alphabetical order, accumulating
  words. Cuts upon reaching `--max-words-per-chunk`. Boundary-aware:
  preserves atomic code/table blocks.
- **`semantic`** — groups files from the same directory (module) into
  the same chunk before applying the limit. Preserves thematic
  cohesion. Groups larger than the limit are subdivided.

## Query-oriented packing (`--for-queries`)

Reorders source files by query affinity **before** chunking, so content
relevant to the same expected question lands in the same chunk. Takes a
text file with one query per line (blank lines and `#` comments are
skipped):

```
# queries.txt — what users will actually ask
how do I declare options
testing CLI applications
```

Each query claims its BM25-matching files (greedy, in file order); files
matched by no query go last in alphabetical order. Query terms that
appear in more than half of the source files are ignored when matching —
they carry no co-location signal (this filter only kicks in on corpora
of 5+ files). The ranking corpus is always the full packed set, `--delta`
included, since a delta run that fires is a full pack. Fully deterministic —
same corpus + same queries file = same chunk layout. The summary reports
the assignment: `Query packing:   3 queries, 12 files matched, 4 unmatched`.

Greedy assignment favors earlier queries: the filter mitigates — it does
not solve — one query absorbing most of the corpus (measured 29/40 files
claimed by the first query on the click docs corpus even with the
filter). Put your most specific queries first.

Incompatible with `--strategy semantic` (two mutually exclusive grouping
policies — the CLI errors instead of silently overriding). Composes with
`--delta`, `--dedup`, `--score`, `--context-header`, `--format jsonl`
and `--bundle`.

## Page layout (`--layout page`)

For readers that open files by name and `grep` them, such as Claude Code,
`--layout page` writes one file per page instead of numbered chunks
([ADR-0010](https://github.com/lorenzoervedosa/dograpper/blob/main/docs/adr/0010-per-page-pack-layout.md)):

```
out/
├── INDEX.md
└── pages/
    ├── ActionGroup.md
    ├── Help_Style_guide.md      # from Help:Style_guide.html
    ├── Modding.md
    └── Modding/
        └── vi.md
```

- **Names.** A page keeps its path relative to `INPUT_DIR`, with the source
  extension replaced by the `--format` one (`md` or `txt`), so
  `Glob **/IsoPlayer.md` finds `zombie/characters/IsoPlayer.html`. The
  characters HTTrack forbids (`\ : * ? " < > | ~`, control characters) become
  `_`; a Windows reserved name (`CON`, `PRN`, `AUX`, `NUL`, `COM1`–`COM9`,
  `LPT1`–`LPT9`, any case) gets a trailing `_`, and a final dot or space
  becomes `_`. Names that differ only in case get `-2`, `-3`… in sorted
  source order, so the same tree always gives the same names.
- **`INDEX.md`.** Two header lines, then one line per page sorted by path,
  so `grep -i term INDEX.md` answers "which page":

  ```
  # Index
  167 pages. One line per page: - [title](<path>), N words, URL

  - [ActionGroup](<pages/ActionGroup.md>), 599 words, https://pzwiki.net/wiki/ActionGroup
  - [Help:Style guide](<pages/Help_Style_guide.md>), 4273 words, https://pzwiki.net/wiki/Help:Style_guide
  ```

  The title is the page's `<head>` `<title>` without the site suffix (the
  text after the last ` - `, ` – `, ` — ` or ` | `) when that suffix ends
  more than half of the run's titles; else the page's first `h1`, read before
  extraction; else the file stem. Whitespace is collapsed, control characters
  are neutralized and `\`, `[`, `]` are backslash-escaped. The URL comes from
  the manifest or the page marker, as for `--context-header`, and is left out
  when unknown. New fields are only ever appended to a line.
- **Links.** In `md`, a link to a packed page points at that page's file,
  relative to the linking file and written `<...>` as in `INDEX.md`
  (`[1]: <../inventory/ItemContainer.md#getItems()>`), so it can be opened as
  written; a link to a redirect alias that `pack` skipped points at its
  target's file. A link to anything else (an absolute URL, a file outside the
  pack) keeps its target as the page wrote it.
- **Whole pages.** Pages are never split and lines never wrapped: a page
  larger than one `Read` call takes stays reachable with `grep -n` plus a
  `Read` with an offset. There is no word cap, no chunk cap and no size
  warning. Without `--context-header` a page file holds only its content.
- **Ownership.** Every run builds `pages/` in a temporary directory next to
  it and swaps it in, so removed and renamed pages disappear and a failed run
  keeps the previous pages. `pack` writes only `INDEX.md`, `pages/` and its
  sidecars: any other file in the output directory, such as a `SKILL.md`,
  survives every repack. A `pages/` without an `INDEX.md` next to it is not a
  previous output, and the run exits 1 before writing anything.

| Flag | With `--layout page` |
|---|---|
| `--max-words-per-chunk`, `--max-chunks`, `--strategy`, `--prefix`, `--with-index`/`--no-index` | usage error (exit 2) when set on the CLI or in `.dograpper.json`, even to the default value |
| `--bundle`, `--for-queries`, `--format jsonl`, `--api-records`, `--dedup exact\|fuzzy\|both` | usage error (exit 2) |
| `--delta` | the [ADR-0008](https://github.com/lorenzoervedosa/dograpper/blob/main/docs/adr/0008-delta-as-a-change-gate.md) gate is unchanged; a run that passes it rebuilds `pages/` in full |
| `--context-header` | one header at line 1 of each page file: `title`, `source`, `url`, `version`, `version_status`, `word_count`, `llm_readiness`; no breadcrumb or outline |
| `--cross-refs` | markers name the page from the output root, `[-> pages/Target.md]`; `cross_refs.json` is keyed by page path |
| `--score`, `--report` | one score per page; `chunk_id` in `llm-readiness.json` is the page path, stable across runs |
| `--dry-run` | projects the page count; never needs or touches `pages/` |

`explain`, `serve`, `eval` and the GitHub Action read the chunk layout only.
Do not mix layouts in one output directory: `pack` never deletes chunk files.

## Examples

```bash
# Basic pack with defaults
dograpper pack ./rust-docs -o ./chunks

# Optimized for NotebookLM
dograpper pack ./docs -o ./chunks --bundle notebooklm --context-header --score

# JSONL for RAG with cross-references
dograpper pack ./docs -o ./chunks --format jsonl --cross-refs --score

# Full dedup + context + tokens
dograpper pack ./docs -o ./chunks --dedup both --context-header --show-tokens

# Dry-run to calibrate parameters
dograpper pack ./docs -o ./chunks --dry-run --dedup both --score --show-tokens

# Group by module, filter images
dograpper pack ./docs -o ./chunks --strategy semantic --ignore "*.png"

# Only re-pack when the sources actually changed
dograpper pack ./docs -o ./chunks --delta

# Co-locate content by expected user queries
dograpper pack ./docs -o ./chunks --for-queries queries.txt

# One file per page plus INDEX.md, for grep-and-Read readers
dograpper pack ./docs -o ./wiki-ref --layout page --context-header
```

## Options

```{dograpper-options} pack
```

## Options in detail

### `--include-extensions`

Extensions packed as documentation (csv). Other files are skipped and counted by extension in the summary. `robots.txt` and dograpper's own manifests are always skipped

### `--format`

Output format: `md` (Markdown: `#` headings, `[text](target)` links, `-` / `N.` lists, pipe tables, fenced code; see [Markdown structure](#markdown-structure-md)), `txt` (plain text), `jsonl` (plain text records)

### `--context-header`

Injects `dograpper-context-v1` header (structured JSON), with the source `url` from the manifest or the page's HTTrack / saved-from marker

### `--manifest`

Download manifest, used to resolve source URLs for `--context-header`; its entry wins over a page marker. A relative path resolves against `INPUT_DIR`, an absolute one is used as is. Given explicitly, it must exist and load (exit 1 otherwise). Not given (or set in `.dograpper.json`), it is looked for in `INPUT_DIR` and, when `INPUT_DIR` lies inside a mirror (`<root>/<host dir>/...`), in its parents up to that root, at most 8 levels up and never above: packing a subdirectory finds the manifest `download` left in `-o`, and one in `/tmp` or `$HOME` is never picked up. The nearest wins, and one found above `INPUT_DIR` is named in a note. None found is skipped; a broken one is skipped with a note

### `--api-records`

Splits API reference pages (Javadoc, Sphinx autodoc, rustdoc, TypeDoc) into container records and one record per member; needs `--format jsonl` (see [API reference records](#api-reference-records---api-records))
