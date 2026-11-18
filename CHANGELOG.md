# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries start at `0.4.0`. For anything earlier, read `git log`.

## How to update this file

**What earns an entry.** A change belongs here exactly when a user can observe
it without reading the source: the CLI surface (a command, a flag, printed
output, an exit code), the files a run writes or the format of those files, the
GitHub Action's inputs/outputs/behaviour, or an install or runtime requirement.
Everything else — internal refactors, tests, tooling, docs — earns nothing.

**Which section.** Derive it from the Conventional Commit type:

| Commit | Section |
|---|---|
| `feat:` introducing new surface | `Added` |
| `feat:` or `fix:` that alters documented behaviour on purpose | `Changed` |
| `fix:` restoring intended behaviour | `Fixed` |
| removal of existing surface | `Removed` |
| surface kept but slated for removal | `Deprecated` |
| anything with a security impact | `Security` |
| `refactor:` `test:` `chore:` `ci:` `build:` `docs:` | *(none)* |

A `refactor:` or `chore:` that would need an entry was mistyped — it changed
behaviour, so it is a `feat:` or a `fix:`.

**When.** In the same pull request that makes the change, appended to
`## [Unreleased]`. Never reconstructed in a batch at release time.

**Granularity.** One line per user-visible change, not per commit: five commits
that build one flag are one entry. A contract change links its ADR and issue.

**Releasing.** Rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`, open a
fresh empty `## [Unreleased]` above it, and bump `version` in `pyproject.toml`
in the same commit — `dograpper --version` reads the installed package
metadata, so a tag without the bump ships a binary that misreports itself.
While the project is pre-1.0, new surface or a contract change is a MINOR bump
and fixes alone are a PATCH bump.

`tests/test_changelog.py` enforces the mechanical half of these rules.

## [Unreleased]

### Added

- `dograpper docs`: serves a self-contained, offline reference page for every
  command and option on `127.0.0.1` (`--port`, default 8000; `--no-browser`),
  generated from the installed CLI. Command descriptions and option help
  strings were rewritten to say what each flag does. ([#110])
- `pack` detects bot-challenge interstitial pages (Cloudflare "Just a
  moment..." title) in its input, warns once with the affected files, keeps
  them out of the chunks and reports `Challenge pages: N` in the summary; it
  fails if every input file is one. ([#69])
- `download --downloader httrack` (and the same flags on `sync`): a pure-Python
  fetcher that mirrors HTTrack 3.51's request identity, with `[httrack]` flags
  (`--user-agent`, `--no-robots`, `--connections`, `--max-conn-rate`,
  `--max-bandwidth`, `--timeout`, `--retries`, `--max-links`,
  `--max-retry-after`, `--disable-security-limits`). Recursive crawl and the
  Playwright fallback fail loud under this profile for now.
- `httrack` install extra (`brotli`, `zstandard`) enabling `br` / `zstd`
  response decoding for the httrack profile.
- `download` (wget paths) lists the URLs behind a wget exit code 8 in the
  summary as `Failed: N URLs (first 5 shown)` with each URL and HTTP status;
  `--verbose` lists them all ([#97](https://github.com/lorenzoervedosa/dograpper/issues/97)).
- `pack --layout page` (config key `layout`, forwarded by `sync`) writes one
  file per page under `pages/`, mirroring `INPUT_DIR` with the `--format`
  extension (`Modding/vi.html` -> `pages/Modding/vi.md`), plus an `INDEX.md`
  with one line per page: `- [title](<path>), N words, URL`. Names are
  portable (HTTrack's forbidden characters, Windows reserved names and a
  trailing dot or space get `_`; case-only collisions get `-2`, `-3`...).
  Every run rebuilds `pages/` and swaps it in, with no word cap, chunk cap or
  size warning, and never touches other files in the output directory.
  `--context-header` writes one header per page; `--cross-refs` markers,
  `cross_refs.json`, `llm-readiness.json` and `delta_manifest.json` name pages
  by path. Chunk-only settings, `--bundle`, `--for-queries`, `--format jsonl`
  and `--dedup` other than `off` exit 2; a `pages/` without `INDEX.md` exits
  1. ([ADR-0010](docs/adr/0010-per-page-pack-layout.md), [#84])
- `pack --layout page --context-header` writes exactly one
  `dograpper-context-v1` header per page file, at line 1, with a new
  optional `title` field first: the `<title>` minus the site suffix shared by
  more than half of the pages, else the raw page's first `h1`, else the file
  stem. The page header holds no `chunk_index`, `total_chunks` or
  `context_breadcrumb`. ([ADR-0010](docs/adr/0010-per-page-pack-layout.md),
  [#85])
- `init --target claude-code`: a config for Claude Code (`layout: page`,
  `format: md`, `context-header`, `dedup: off`, no chunk-only key) and a
  `SKILL.md` stub in `--skill-dir` (default `docs-skill`, the directory to
  pack into) with the skill name, a description to fill in, a link to
  `INDEX.md` and grep-then-Read usage. An existing `SKILL.md` is never
  overwritten. The `claude-project` description now says it targets Claude
  Projects. ([#93])
- `download --filter RULE` (repeatable, config key `filter`, forwarded by
  `sync`): HTTrack scan rules (`+pattern` accepts, `-pattern` refuses, the last
  match wins) applied to every discovered link before it is fetched, under both
  downloaders: the llms.txt/sitemap lists, `wget --mirror` (as
  `--accept-regex`/`--reject-regex`), Playwright and httrack redirect targets.
  A `+` rule lifts `--no-parent` for the URLs it matches; the start URL is never
  filtered. Refused URLs are counted as `Filtered by --filter: N` in the
  summary ([#96](https://github.com/lorenzoervedosa/dograpper/issues/96)).
- `pack --api-records` (config key `api_records`, `--format jsonl` only)
  writes each javadoc 25 type page as one container record (qualified name and
  kind, inheritance, signature, description, declared member names,
  "inherited from" lists; no summary tables) plus one member record per
  member (qualified name, full signature with type parameters, doc comment,
  notes), with ids `NN_path` and `NN_path#anchor`, `breadcrumb`
  `[container, member]`, `url` ending with the member anchor, and new optional
  JSONL fields `symbol`, `kind`, `symbol_kind`, `container` and `generator`.
  Split pages skip extraction and `--dedup`; every other page keeps one
  record, is listed in a warning with the reason and is counted in the
  summary's `API records:` line. With `--format md`/`txt`, `--bundle
  notebooklm` or `--layout page` it exits 2.
  ([ADR-0009](docs/adr/0009-api-reference-symbol-records.md),
  [#76](https://github.com/lorenzoervedosa/dograpper/issues/76))
- `pack` cleans MediaWiki pages (detected by their `<meta name="generator">`)
  before extraction: navigation boxes (`navbox`), section edit links
  (`mw-editsection`) and maintenance boxes (stub, outdated, "help update"
  boxes with their `Edit (Create account)` links) leave the text; note boxes
  stay. The version banner leaves the text too: the context header (both
  layouts) and the JSONL records gain the optional page metadata fields
  `version` and `version_status` (`current`, `outdated`, `older-build`),
  read from the banner, else from the first hidden `Version X` category. A
  redirect alias (a page saved through a redirect, with its target's
  content) is skipped when its target page is packed too, listed on stderr
  and counted as `Redirect aliases: N` in the summary. Pages from any other
  generator are extracted exactly as before. ([schema](docs/schema-v1.md),
  [#88])

### Changed

- `pack` now packs documentation formats only by default (`.html`, `.htm`,
  `.md`, `.txt`). `.js`, `.css`, `.json` and other text files are skipped and
  listed by extension in one summary line; `robots.txt`,
  `.dograpper-manifest.json`, `delta_manifest.json` and `pack_state.json` are
  always skipped. `--include-extensions` (config key `include-extensions`)
  brings other extensions back. Corpora that relied on packing e.g. `.json`
  or extensionless files must now opt in. ([#91])
- `pack --context-header` fills `url` for pages without a manifest entry from
  the marker in the page head: HTTrack's `Mirrored from <url>` footer or a
  browser's `saved from url=(N)<url>`. The value is validated (http/https,
  length, characters, host) and the manifest still wins. The pack summary gains
  a `Source URLs` line counting URLs by source and listing files left without
  one, including rejected or conflicting markers. ([#90])
- `download --manifest` resolves a relative path against `-o`, so the default
  `.dograpper-manifest.json` now lives in the output directory instead of the
  current one: a re-run from another directory stays incremental and two
  mirrors no longer share a manifest. A manifest left at the old location is
  not read; `download` prints a one-line note naming the new path.
  `pack --manifest` resolves against `INPUT_DIR`; by default `pack` looks in
  `INPUT_DIR` and, inside a mirror, up to its root (the parent of the host
  directory, at most 8 levels up), naming a manifest found above `INPUT_DIR`
  in a note. The GitHub Action's manifest moves into `input-dir` and is left
  out of the source-file drift list; a repo-root one from earlier runs is no
  longer read. ([#95])
- `pack --format md` (the default) writes each HTML page's structure as
  Markdown: `#`–`######` headings, `[text](target)` links with the `href` as
  the page wrote it, `-` / `N.` list items with nesting, and pipe tables with
  one line per row. A link to the same page, or with a scheme other than
  `http`, `https` or `mailto`, keeps only its text; a list item holding a
  block is written as its blocks. Counts leave the markup out (context
  headers, `INDEX.md`, `llm-readiness.json`), and `--max-words-per-chunk`
  measures each page's plain text, as for `txt`. `--dedup` compares a table
  or a list as one block. `txt` and `jsonl` output is unchanged. ([#87])

### Fixed

- `download` and `pack --delta` exit 1 with the path in the message when the
  manifest (`.dograpper-manifest.json`) or `pack_state.json` cannot be written,
  instead of logging an error and exiting 0; both files are now written
  atomically, so an interrupted run keeps the previous one.
  ([#113](https://github.com/lorenzoervedosa/dograpper/issues/113))
- `pack` never reads its own output: when `-o` lies inside `INPUT_DIR` (the
  default for `sync`, `<output>/chunks`), that subtree is left out of the input
  and reported once as `Excluded own output directory: N file(s) under ...`,
  so a second run no longer re-packs the first one's chunks and the delta gate
  reports "no files changed". `-o` equal to `INPUT_DIR` is a usage error
  (exit 2). ([#112](https://github.com/lorenzoervedosa/dograpper/issues/112))
- `pack` zero-pads chunk file names, JSONL ids, `Chunk N of M` headers and sidecar
  chunk ids to one width per run (`max(2, digits of the chunk count)`), so
  100 or more chunks sort numerically; packs under 100 chunks keep their names
  ([#92](https://github.com/lorenzoervedosa/dograpper/issues/92)).
- `pack --score` no longer grades a chunk with empty extracted content as `A`;
  it is graded `C` with score 0. ([#69])
- `download` manifest entries record `url` as the URL dograpper requested for
  each file (never a redirect target, which may carry a signed token; without
  userinfo; none at all when its query has a parameter other than a
  navigation name such as `title`, `oldid`, `page` or `lang`) instead of
  appending the saved path to the seed URL, which doubled a seed's path
  segment (`.../PZ-API-Docs/PZ-API-Docs/index.html`), glued paths onto a page
  seed and kept the `.html` that `--adjust-extension` added. Query pages such
  as `index.php?title=...` get their real URL. A file no run recorded gets
  `"url": null`, and `pack --context-header` leaves `url` out for such
  sources. ([#94])
- `download` no longer lists its own manifest, `delta_manifest.json` or
  `pack_state.json` among the mirror's files when they sit inside `-o`, and
  `pack --delta` leaves them out of `pack_state.json`. ([#95])
- `download` sitemap discovery no longer crashes on a truncated or corrupt
  gzip sitemap or on a malformed URL in a sitemap index; the bad entry is
  skipped.
- `download` llms.txt discovery no longer crashes on a truncated or corrupt
  gzip body; the candidate is logged and skipped. ([#77])
- `pack --cross-refs` no longer corrupts words where a link's text is a
  substring of an unrelated word in the chunk (e.g. link text "Install"
  inside the word "Installation"). `annotate_cross_refs` now matches on
  word boundaries instead of doing a plain substring replace. ([#55])
- `pack --delta` no longer reports a byte-identical file as `modified` when
  only its mtime changed (a `touch`, a `cp` without `-p`, a fresh `git
  clone`). The manifest diff now falls back to an md5 content hash whenever
  size matches but mtime disagrees, instead of trusting mtime alone; the
  mtime match itself remains a fast path that skips hashing. Manifests
  written before this change still load and compare correctly. ([#56])
- `pack` no longer drops HTML-escaped angle brackets (`&lt;T&gt;`, escaped
  markup in code blocks) during content extraction; default output now keeps
  `List<T>` and `<div>` examples, matching `--no-extract`. ([#66])
- `pack --dedup` no longer deletes a page's own content. A block is never
  removed against another block of the same page, in any mode, and `fuzzy`
  keeps a near-duplicate that starts with a different token (a key, tag or
  parameter name) or differs only in numbers (a version banner, a date). The
  summary and the `--dry-run` report gain a `Matches kept` line counting the
  blocks each rule kept. A block identical on several pages, an identical
  version banner included, is still kept only on the first. ([#89])
- `pack --dedup` no longer deletes the version banner of a MediaWiki page
  because an earlier page carries the same one (as text, 137 banners became
  29 under `exact` on a 167-page wiki): the version is now page metadata in
  the context header, out of the text dedup reads, so with `--context-header`
  every page keeps its `version`. ([#88], [#89])
- `pack --cross-refs` annotates each page's own content, for the links that
  page holds, as the chunk is written, instead of the first occurrence of the
  link text anywhere in the written chunk file. Markers no longer rewrite
  JSONL `id`/`source` values, md/txt file indexes or context headers, land in
  another page that merely mentions the link text, or split a dotted
  identifier (`pkg.AttachedItems [-> docs_chunk_01].AttachedItems`), and
  large corpora no longer stall (each link text's pattern is compiled once
  per run). ([#67])
- `pack --context-header --manifest PATH` exits 1 with a clear message when
  PATH is missing or cannot be loaded, instead of silently packing without
  URLs. A broken file at the default manifest path is reported as a note and
  skipped. ([#90])
- `pack --context-header` resolves manifest URLs when `INPUT_DIR` is a
  subdirectory of the download output, instead of matching nothing. Files are
  matched on their path in the mirror, so a page in a subdirectory no longer
  takes the URL of a same-named page at the site root; a file that matches
  several entries gets no `url` and is listed in the summary. ([#90])
- `pack --context-header` writes `>` in header values as the JSON escape
  `\u003e`, so a heading or source path holding `-->` no longer closes the
  `dograpper-context-v1` comment early; JSON parsers read the same value.
  ([ADR-0010](docs/adr/0010-per-page-pack-layout.md))
- `pack` keeps the line breaks and indentation of HTML `<pre>` blocks in
  `md`, `txt` and `jsonl` instead of flattening each one to a single line.
  `md` writes them as fenced code blocks tagged with the language named by a
  `mw-highlight-lang-*`, `language-*`, `lang-*` or Sphinx `highlight-*` class
  (` ```lua `); `txt`
  and `jsonl` carry the code without the fence. `--dedup` and chunking no
  longer split a code block at a blank line, and `--score` counts a fenced
  block as intact even when its code holds backticks or a `<pre>` sample.
  ([#86])
- `download`'s Playwright layer follows the links of a page it skips as
  cached on an incremental run, instead of ending the crawl there. ([#94])
- `pack --cross-refs` writes its marker after a Markdown link whose text it
  matched (`[Item](Item.html) [-> docs_chunk_02]`) instead of inside the
  brackets, and never inside a link's target, where it broke the link. ([#87])
- `pack --layout page --format txt` writes `<pre>` code without its fence
  lines, as txt chunks do, and leaves them out of the page's `INDEX.md` and
  header word counts. ([#86])

### Security

- URLs that `download` logs during llms.txt and sitemap discovery drop
  credentials and escape control characters, so a hostile sitemap or
  robots.txt cannot inject terminal escape sequences.
- `download` never writes a credential from a URL's query into the manifest,
  and so into a pack: a URL is recorded only when every query parameter is a
  navigation name (`title`, `oldid`, `page`, `lang`, `q`, ... see README),
  otherwise `"url": null`. Logs and failure reports show the value of
  credential-like parameters (`token`, `secret`, `key`, `sig`, `jwt`,
  `X-Amz-*`, ...) as `REDACTED`. ([#94])

## [0.4.0] - 2026-08-15

### Added

- `dograpper eval` — offline validation of a packed context: deterministic
  golden Q&A generated from heading breadcrumbs, BM25 retrieval, and
  hit-rate@k / MRR reported per readiness grade. No network calls.
- `dograpper explain` — read-only preview of exactly what the LLM receives per
  chunk (v1 headers, cross-references, grade). Writes nothing.
- `dograpper serve` — local MCP server over the packed JSONL, speaking
  newline-delimited JSON-RPC 2.0 on stdio: search, get, cross-refs, readiness.
- `dograpper init` — onboarding wizard that generates a `.dograpper.json` tuned
  per target (`notebooklm`, `rag`, `claude-project`). `--target` with `--yes`
  for scripted use.
- `dograpper drift` — diff between two `llm-readiness.json` snapshots, rendered
  as markdown or text, with `--fail-on-drift` for CI.
- Composite GitHub Action for context freshness: re-packs, computes the drift
  and posts a single upserted report comment on the pull request.
- `pack --for-queries` — reorders source files by BM25 affinity to a list of
  expected queries so content answering the same question is co-located.
  Requires `--strategy size`.
- `pack --report` — writes `readiness-report.html` with per-page before/after
  extraction data and the cause of each score penalty. Implies `--score`.

### Changed

- `pack --delta` is now a change gate: the corpus state recorded by the last
  pack decides *whether* the run happens, not *which* files it packs. Nothing
  changed, nothing is written; anything changed, the pack runs in full. Partial
  runs used to renumber chunks from `01` and overwrite the artifacts of the
  files they did not touch. ([#39], [ADR-0008](docs/adr/0008-delta-as-a-change-gate.md))
- `pack --delta` records `pack_state.json` in the output directory and diffs
  against it on the next run, so delta now works in pack-only flows. ([#39])
- `pack --manifest` no longer drives the delta comparison; its remaining role is
  resolving source URLs for `--context-header`. `pack` never writes it. ([#39])
- `--report` is a paired flag (`--report/--no-report`) so a config file that
  enables it can still be overridden from the command line.

### Fixed

- The content extractor no longer discards the rest of a page after a
  blacklisted element whose end tag never arrives — a void element such as
  `<img class="copy-button">`, or stray markup inside a code sample. Extraction
  used to stop mid-sentence at an arbitrary point. ([#42])
- `sync` preserves explicit CLI flag precedence across `ctx.invoke`, so a
  `.dograpper.json` value no longer overrides a flag typed on the command line.
- `pack` skips binary files instead of counting their bytes as words. ([#2])
- `download` uses a binary reject-list so wget follows pretty URLs. ([#1])
- `pack` no longer aborts when a single page fails extraction during `--report`.
- `serve` survives malformed request params and tool handlers that raise.
- `drift` rejects malformed snapshots and delta manifests loudly instead of
  degrading silently, and omits the source-file section when no delta manifest
  was given.
- Boundary issues are attributed to the source page that caused them rather
  than to the joined chunk text.
- Query-oriented ordering ignores terms common to the corpus, excludes the
  queries file itself from the packed corpus, ranks on post-dedup text, warns
  on unreadable files instead of skipping them silently, and reports its
  summary in `--dry-run`.
- The release install script matches the filename referenced by its `.sha256`
  companion.

[#1]: https://github.com/lorenzoervedosa/dograpper/issues/1
[#2]: https://github.com/lorenzoervedosa/dograpper/issues/2
[#39]: https://github.com/lorenzoervedosa/dograpper/issues/39
[#42]: https://github.com/lorenzoervedosa/dograpper/issues/42
[#55]: https://github.com/lorenzoervedosa/dograpper/issues/55
[#56]: https://github.com/lorenzoervedosa/dograpper/issues/56
[#66]: https://github.com/lorenzoervedosa/dograpper/issues/66
[#77]: https://github.com/lorenzoervedosa/dograpper/issues/77
[#91]: https://github.com/lorenzoervedosa/dograpper/issues/91
[#69]: https://github.com/lorenzoervedosa/dograpper/issues/69
[#89]: https://github.com/lorenzoervedosa/dograpper/issues/89
[#67]: https://github.com/lorenzoervedosa/dograpper/issues/67
[#94]: https://github.com/lorenzoervedosa/dograpper/issues/94
[#90]: https://github.com/lorenzoervedosa/dograpper/issues/90
[#84]: https://github.com/lorenzoervedosa/dograpper/issues/84
[#85]: https://github.com/lorenzoervedosa/dograpper/issues/85
[#93]: https://github.com/lorenzoervedosa/dograpper/issues/93
[#86]: https://github.com/lorenzoervedosa/dograpper/issues/86
[#95]: https://github.com/lorenzoervedosa/dograpper/issues/95
[#87]: https://github.com/lorenzoervedosa/dograpper/issues/87
[#88]: https://github.com/lorenzoervedosa/dograpper/issues/88
[#110]: https://github.com/lorenzoervedosa/dograpper/issues/110
