# Generated artifacts

| Artifact | Flag | Description |
|----------|------|-----------|
| `docs_chunk_*.md` | (default) | Markdown chunks (headings, links, lists, tables, code) |
| `docs_chunk_*.txt` | `--format txt` | Plain-text chunks |
| `docs_chunk_*.jsonl` | `--format jsonl` | One JSON line per source file |
| `pages/**/*.md` | `--layout page` | One file per page, mirroring the input tree (`.txt` with `--format txt`) |
| `INDEX.md` | `--layout page` | One line per page: title, path, word count, URL |
| `cross_refs.json` | `--cross-refs` | Cross-reference graph between chunks |
| `llm-readiness.json` | `--score` | Quality scores per chunk |
| `readiness-report.html` | `--report` | Visual before/after report with penalty causes |
| `IMPORT_GUIDE.md` | `--bundle` | Upload guide with recommended ordering (both `notebooklm` and `rag-standard`) |
| `delta_manifest.json` | `--delta` | Mapping of changed files |
| `pack_state.json` | `--delta` | Corpus state as of this pack; the next `--delta` run diffs against it |
| `.dograpper-manifest.json` | `download` | Mirror manifest (hashes + mtimes), in the `-o` directory |
| `hts-changes.json` | `download --changes` | HTTrack's change report of the last run, in the `-o` directory |
| `.dograpper.json`, `SKILL.md` | `init` | Config for the chosen target; skill stub for the `claude-code` target (never overwritten) |

## Output summary

At the end of `pack`, dograpper prints a summary:

```
Pack complete:
  Files processed: 47
  Files excluded:  12
  Chunks generated: 5 / 50 (max)
  Words per chunk:  ~94,000 avg (min: 78,230, max: 112,400)
  Total words:     470,120
  Output:          ./chunks/
```

Before the summary, when files outside `--include-extensions` were found, one
line lists them: `Skipped non-documentation files: 15 (.css x1, .js x13, robots.txt x1)`.
They are also counted in `Files excluded`.

When `--output` lies inside `INPUT_DIR` (as with `sync`'s default
`<output>/chunks`), `pack` never reads its own output: that subtree is left out
of the input and one line reports it: `Excluded own output directory: 4
file(s) under ./docs/chunks`. These files are not counted in `Files excluded`.
`--output` equal to `INPUT_DIR` is a usage error.

Conditional extra lines (per enabled flag):

| Flag | Extra lines |
|---|---|
| `--show-tokens` | `Tokens per chunk`, `Total tokens`, `Encoding` |
| `--dedup` | `Dedup mode`, `Blocks analyzed`, `Blocks removed`, `Matches kept`, `Pages exempted`, `Words removed` |
| `--cross-refs` | `Cross-refs: ./chunks/cross_refs.json (N links, M unresolved)` |
| `--score` | `LLM Readiness: ./chunks/llm-readiness.json`, then the grade counts (`5x A, 2x B, 0x C (avg: 0.87)`) |
| `--report` | after the summary: `Readiness report (worst first):`, one graded row per chunk, `Report: <path>` |
| `--api-records` | `API records: N pages split into M records (C container, K member), P pages kept whole` |
| `--delta` | `Delta: N added, M modified, K removed`, `Delta manifest: ...` |
| `--bundle` | `Import guide: <path>` |
| bot-challenge pages found | `Challenge pages: N` |
| saved HTTP error pages found | `Error pages: N` |
| MediaWiki redirect aliases of packed pages found | `Redirect aliases: N` |
| `--for-queries` | `Query packing: ...` |
| `--context-header` or `--layout page` | `Source URLs: N from manifest, M from page markers, K without`, `Rejected markers: ...`, files without a URL |
| `--layout page` | `Pages written: N` and `Index: <path>` replace `Chunks generated` and `Words per chunk`; no chunk-limit warnings |

Warnings appear when:
- Input `.html`/`.htm` files are Cloudflare bot-challenge interstitials
  (`<title>Just a moment...</title>`), typically saved by an external
  mirroring tool that was blocked. They carry no content, so `pack` lists
  them once on stderr, leaves them out of the chunks and counts them (also
  in `--dry-run`); if every file is one, `pack` fails. A page that merely
  mentions the phrase in its text is not affected.
- Input `.html`/`.htm` files are saved HTTP error pages: the `<title>` is a
  status line such as `404 Not Found` and the whole file holds at most 40
  words of text (scripts and styles excluded). `pack` lists them once on
  stderr and leaves them out, in both layouts and in `--dry-run`; the pack
  summary counts them (`Error pages: N`, and in `Files excluded`); if every file is one, `pack` fails. A page about HTTP
  errors or one that merely mentions the status is not affected.
- An individual file exceeds `--max-words-per-chunk` (it goes alone
  into a chunk, overshooting the stated limit).
- Total chunks exceed `--max-chunks` (nothing is discarded — every
  chunk is still written, just with a warning; use `--bundle
  notebooklm` for a hard cap that's actually enforced).
