# Troubleshooting

## `download` fetches only 1 file

The site is a client-rendered SPA without `llms.txt` or an accessible
`sitemap.xml`. The anti-shell heuristic detects this and falls back
to Playwright automatically — if it doesn't, make sure `playwright` is
installed along with its system libraries (see [System dependencies](install.md#system-dependencies)).

Expected log with the cascade working:

```
INFO: [cascade] layer-3 wget --mirror: link-graph fallback
INFO: [cascade] layer-4 playwright: --mirror yielded only 1 HTML file(s) (likely client-rendered index)
INFO: SPA detected, falling back to playwright
```

## `libnspr4.so: cannot open shared object file`

Missing system libs for Chromium. Run `dograpper doctor
--check-system-libs` for the exact `apt install` command, or see
[System dependencies](install.md#system-dependencies).

## Cross-host sub-sitemaps being rejected

Sub-sitemaps on different hosts are accepted when
the `path-prefix` identifies the project (same-netloc **OR**
path-prefix). Covers Mintlify (sub-sitemap at
`www.mintlify.com/<proj>/sitemap.xml`). If it still rejects them, run
with `-v` to see the decision in the log
(`sitemap: skipping out-of-scope sub-sitemap`).

## `pack --delta` packs everything on the first run

Expected behavior. `--delta` diffs the corpus against
`<output-dir>/pack_state.json`, written at the end of every successful
delta run. The first run has no baseline, so every file counts as
"added" and the pack runs in full.

## `pack --delta` re-packs every file even though only one changed

Also expected. `--delta` decides *whether* to pack, not *which* files
to pack: partial runs renumbered the chunks from 01 and overwrote the
artifacts of the files they did not touch. See
[ADR-0008](https://github.com/lorenzoervedosa/dograpper/blob/main/docs/adr/0008-delta-as-a-change-gate.md).

## Chunks too large for NotebookLM

`--bundle notebooklm` caps `--max-words-per-chunk` at 500,000 — with
the default (also 500,000) this produces no size reduction on its
own. Combine with `--strategy semantic` to keep modules cohesive, and
if chunks still overflow, lower `--max-words-per-chunk` explicitly
below the cap and combine with `--dedup both`.

## `wget returned 8` but the download looks fine

wget exit code 8 means "server error on some URLs" — treated as a
partial success. The manifest only records files that were actually
downloaded. The failing URLs are listed at the end of the `Download complete`
summary as `Failed: N URLs (first 5 shown)`, each with its HTTP status; add
`--verbose` (before the subcommand) to list all of them. A missing
`robots.txt` is not counted. Re-running (incremental) closes transient gaps,
but a permanent 404 stays missing.
