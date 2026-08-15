# dograpper

      $$\                                                                                
      $$ |                                                                               
 $$$$$$$ | $$$$$$\   $$$$$$\   $$$$$$\  $$$$$$\   $$$$$$\   $$$$$$\   $$$$$$\   $$$$$$\  
$$  __$$ |$$  __$$\ $$  __$$\ $$  __$$\ \____$$\ $$  __$$\ $$  __$$\ $$  __$$\ $$  __$$\ 
$$ /  $$ |$$ /  $$ |$$ /  $$ |$$ |  \__|$$$$$$$ |$$ /  $$ |$$ /  $$ |$$$$$$$$ |$$ |  \__|
$$ |  $$ |$$ |  $$ |$$ |  $$ |$$ |     $$  __$$ |$$ |  $$ |$$ |  $$ |$$   ____|$$ |      
\$$$$$$$ |\$$$$$$  |\$$$$$$$ |$$ |     \$$$$$$$ |$$$$$$$  |$$$$$$$  |\$$$$$$$\ $$ |      
 \_______| \______/  \____$$ |\__|      \_______|$$  ____/ $$  ____/  \_______|\__|      
                    $$\   $$ |                   $$ |      $$ |                          
                    \$$$$$$  |                   $$ |      $$ |                          
                     \______/                    \__|      \__|

                     
**Context Engineering Pipeline for Deterministic LLM Ingestion**

Turns HTML documentation into structured, deduplicated, scored, and versioned
context — ready for ingestion into NotebookLM, RAG pipelines, Claude Projects,
and fine-tuning.

---

## Install (end users)

> v1 supports Linux x86_64 only

```bash
# Install (Linux x86_64 only)
curl -fsSL https://raw.githubusercontent.com/lorenzobrasil/dograpper/main/scripts/install.sh | sh
dograpper doctor --install             # fetches wget + chromium
dograpper doctor --check-system-libs   # diagnoses missing system libs
dograpper --help
```

### Proxy / MITM

```bash
HTTPS_PROXY=http://proxy:3128 curl -fsSL https://raw.githubusercontent.com/lorenzobrasil/dograpper/main/scripts/install.sh | sh
CURL_CA_BUNDLE=/path/to/cacert.pem curl -fsSL https://raw.githubusercontent.com/lorenzobrasil/dograpper/main/scripts/install.sh | sh
```

### Storage layout

| Path | Contents |
|------|---------|
| `~/.dograpper/bin/` | static wget |
| `~/.dograpper/playwright-browsers/` | chromium |

Override the default root: `DOGRAPPER_HOME=/custom/path dograpper doctor --install`

### Exit codes

| Code | Origin | Meaning | Remediation |
|------|--------|---------|-------------|
| 0 | any | success | — |
| 1 | doctor (default) | one or more deps missing | run `dograpper doctor --install` |
| 1 | doctor --install | download, SHA256 verification, or the chromium install step failed | retry, check network/proxy |
| 1 | doctor --check-system-libs | `ldd` not found on this system | install `ldd` (usually part of `libc-bin`) |
| 1 | download / crawl | chromium not installed, or any other crawl failure | run `dograpper doctor --install` |
| 2 | doctor --check-system-libs | system libs missing | run suggested `apt install ...` |
| 4 | doctor --install | concurrent install lock held | wait for other install, retry |
| 10 | install.sh | SHA256 mismatch | retry install, report issue |
| 20 | install.sh | unsupported architecture | — |
| 21 | install.sh | unsupported OS | — |
| 30 | install.sh | binary or checksum download failed | check network/proxy, retry |

---

## The problem

Static LLMs don't browse the web. When fed raw documentation as context,
they suffer from: boilerplate (navbars, footers, banners), duplication
across pages, chunks without hierarchy, and code blocks cut in half.
The result is degraded retrieval and hallucination.

## The solution

`dograpper` is a deterministic pipeline that solves each stage:

```
URL → Mirror → Extract → Dedup → Score → Chunk → Export (MD/JSONL)
```

| Stage | What it does | Flag |
|-------|-----------|------|
| **Mirror** | Mirrors site locally via wget/playwright | `download` |
| **Extract** | Strips boilerplate, preserves main content | (automatic) |
| **Dedup** | Eliminates repeated blocks across pages | `--dedup` |
| **Score** | Audits context quality per chunk | `--score` |
| **Chunk** | Groups within limits, preserving code blocks | `pack` |
| **Context** | Injects breadcrumb, metadata, versioned schema | `--context-header` |
| **Export** | MD, JSONL, with cross-refs and import guide | `--format`, `--cross-refs` |

---

## Installation (development)

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/your-user/dograpper.git
cd dograpper
uv sync
uv run dograpper --help
```

### System dependencies

The `download` subcommand uses `wget` by default:

```bash
# macOS
brew install wget

# Ubuntu/Debian
sudo apt install wget
```

For SPA sites (React, Next.js, Mintlify, Docusaurus, etc.), cascade layer 4
uses `playwright`:

```bash
uv sync --extra headless
uv run playwright install chromium
```

On Linux, Chromium requires native libraries. On Ubuntu 22.04+ / Debian 12+:

```bash
sudo apt install -y libnspr4 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
  libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
  libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2t64
```

On Ubuntu ≤22.04 the package is called `libasound2` (without the `t64` suffix).

---

## Quickstart

```bash
# One-time setup: generate a config for your target (notebooklm / rag / claude-project)
dograpper init

# Full pipeline: download + pack optimized for NotebookLM
dograpper download https://flask.palletsprojects.com/en/stable/ -o ./flask-docs
dograpper pack ./flask-docs -o ./chunks --bundle notebooklm --context-header --score

# Or in a single command:
dograpper sync https://flask.palletsprojects.com/en/stable/ -o ./flask-docs

# For RAG: JSONL export with cross-references
dograpper pack ./flask-docs -o ./chunks --format jsonl --cross-refs --score

# Change-gated re-pack: no-op if nothing changed, full repack if anything did
dograpper pack ./flask-docs -o ./chunks --delta
```

---

## Use cases

### NotebookLM
```bash
dograpper pack ./docs -o ./chunks --bundle notebooklm --context-header --score
# Produces ≤50 balanced chunks + IMPORT_GUIDE.md with upload ordering
```

### RAG / Vector DB
```bash
dograpper pack ./docs -o ./chunks --format jsonl --cross-refs --score
# JSONL ready for embeddings, with cross-reference graph
```

### Incremental maintenance (CI/CD)
```bash
dograpper sync <url> -o ./docs
# Incremental download + automatic delta pack
```

For a ready-made CI setup — scheduled refresh, PR drift report and
auto-commit — see the [GitHub Action](#github-action).

### Air-gapped environments
Zero outbound calls after the initial download. No telemetry. Auditable
manifest. Ideal for corporate RAG and regulated environments.

---

## Commands

### `dograpper doctor`

Detects, reports, and installs the heavy dependencies (`wget`, chromium)
dograpper needs but doesn't bundle, into `DOGRAPPER_HOME` (default
`~/.dograpper`; see [Storage layout](#storage-layout)).

```bash
dograpper doctor [options]
```

| Option | Default | Description |
|---|---|---|
| `--install` | `false` | Download and install missing dependencies (wget, chromium) |
| `--force` | `false` | Re-install even if already present |
| `--check-system-libs` | `false` | Diagnose missing chromium system libraries via `ldd`; suggests the install command |

Without flags, prints a status table (`WGET`/`CHROMIUM`, path, version) and
exits 0 if both are present, 1 if either is missing.

#### Exit codes

| Code | Mode | Meaning |
|---|---|---|
| 0 | any | success |
| 1 | default | one or more deps missing |
| 1 | `--install` | download, SHA256 verification, or the chromium install step failed |
| 1 | `--check-system-libs` | `ldd` not found on this system |
| 2 | `--check-system-libs` | required system libraries missing |
| 3 | `--check-system-libs` | chromium not installed |
| 4 | `--install` | another `--install` holds the lock |

#### Examples

```bash
dograpper doctor
dograpper doctor --install
dograpper doctor --install --force
dograpper doctor --check-system-libs
```

### `dograpper download`

Mirrors a documentation site to local disk.

```bash
dograpper download <url> -o <directory> [options]
```

| Option | Alias | Default | Description |
|---|---|---|---|
| `--output` | `-o` | *required* | Destination directory |
| `--depth` | `-d` | `0` (unlimited) | Maximum link depth |
| `--headless` | — | `false` | Skip wget and use playwright directly |
| `--delay` | — | `0` | Delay between requests (ms) |
| `--include-extensions` | — | `html,md,txt` | Allowed extensions (csv) |
| `--manifest` | — | `.dograpper-manifest.json` | Cache file path |

#### Discovery cascade (4 layers)

`download` tries URL sources in order of authority, falling through to the
next one when the previous fails or returns fewer than 3 usable URLs
(threshold `MIN_URLS_TO_CONSIDER_DISCOVERED`):

1. **`llms.txt`** ([llmstxt.org](https://llmstxt.org)) — canonical docs
   index maintained by Mintlify, Anthropic, Stripe. Parser accepts
   markdown links and bare URLs, with fallback to `llms-full.txt`.
2. **`sitemap.xml`** — recursive `sitemapindex`, automatic gzip,
   scoping by **same-netloc OR canonicalized path-prefix**. Covers hosts
   like Mintlify whose sub-sitemap lives on a CDN
   (`www.mintlify.com/<project>/`) but the path identifies the project.
   The probe also tries `sitemap_index.xml` and `sitemap-index.xml`.
3. **`wget --mirror`** — traditional link-graph crawl, `User-Agent` of
   Chrome/120 to avoid being blocked by edge WAFs (Cloudflare, Vercel).
   Runs with `--no-parent`, `--timestamping` (always, enables incremental
   mode via mtime diff), `--convert-links`, `--adjust-extension`,
   `--page-requisites`.
4. **Playwright (bounded hydration)** — SPA fallback:
   `domcontentloaded` 10s + `a[href]` wait 5s + 500ms grace
   (max 15.5s). Replaces `networkidle`, which could hang for 30s on SPAs
   with RUM beacons.

Layers 1 and 2 run **even with `--headless`**, because Mintlify and
similar sites publish authoritative indexes that are the strongest
signal on SPAs. When a layer-1+2 wins, its URLs are handed off via
`wget -i` (with `--no-parent` + `--timestamping`) or as `seed_urls` to
Playwright.

**Anti-shell heuristics**:
- If `wget -i` returns empty pages → cascade re-hydrates the same URLs
  in Playwright (`is_spa(output)`).
- If `wget --mirror` produces ≤1 HTML file → assume recursion failed
  (client-rendered site) and skip to Playwright.

#### Observability

Each layer emits a prefixed `[cascade] layer-N ...` log line, easy to
grep:

```
INFO: [cascade] layer-1 llms.txt: probing
INFO: [cascade] layer-1 llms.txt: raw=0 in-scope=0
INFO: [cascade] layer-2 sitemap.xml: probing
INFO: [cascade] layer-2 sitemap: raw=120 in-scope=120
INFO: [cascade] layer-2 sitemap: WIN (>=3)
INFO: [cascade] layer-3 wget -i: fetching 120 URLs from sitemap.xml
```

#### Incremental

A `.dograpper-manifest.json` manifest is generated after each download,
recording mirrored files with SHA-256 hashes and mtimes. Future re-runs
use this manifest + `wget --timestamping` to fetch only files that
changed on the server.

#### Examples

```bash
# Rust docs, no depth limit
dograpper download https://docs.rust-lang.org -o ./rust-docs

# SPA with rate limiting
dograpper download https://react.dev --headless -o ./react-docs --delay 500

# HTML and Markdown only, maximum 3 levels deep
dograpper download https://docs.python.org/3/ -o ./python-docs -d 3 --include-extensions "html,md"

# Mintlify (layer 2 finds the sub-sitemap on CDN automatically)
dograpper download https://mintlify.wiki/user/project -o ./project-docs
```

### `dograpper pack`

Processes and groups files into chunks optimized for LLM ingestion.

```bash
dograpper pack <input_directory> -o <output_directory> [options]
```

| Option | Alias | Default | Description |
|---|---|---|---|
| `--output` | `-o` | *required* | Directory for chunks |
| `--max-words-per-chunk` | — | `500000` | Word limit per chunk |
| `--max-chunks` | — | `50` | Maximum chunk count |
| `--strategy` | — | `size` | Strategy: `size` or `semantic` |
| `--ignore-file` | — | `./.docsignore` | Exclusion file (gitignore syntax) |
| `--ignore` | — | *(none)* | Inline exclusion patterns (repeatable) |
| `--prefix` | — | `docs_chunk_` | Prefix for generated files |
| `--with-index` / `--no-index` | — | `--with-index` | Header with file index |
| `--format` | — | `md` | Output format: `txt`, `md`, `jsonl`, `xml` (deprecated — errors, use `md`) |
| `--no-extract` | — | `false` | Disable smart HTML content extraction |
| `--show-tokens` | — | `false` | Show token count in the final summary |
| `--token-encoding` | — | `cl100k` | Tokenizer encoding: `cl100k`, `o200k`, `p50k` |
| `--dry-run` | — | `false` | Simulate pack without writing; prints report |
| `--dedup` | — | `off` | Block deduplication: `off`, `exact`, `fuzzy`, `both` |
| `--dedup-threshold` | — | `3` | Maximum Hamming distance for fuzzy dedup (0-10) |
| `--context-header` | — | `false` | Injects `dograpper-context-v1` header (structured JSON) |
| `--cross-refs` | — | `false` | Generates `cross_refs.json` and annotates chunks with `[-> chunk_id]` |
| `--delta` | — | `false` | Skip the run entirely when nothing changed since the last pack; pack in full when something did |
| `--manifest` | — | `.dograpper-manifest.json` | Download manifest, used to resolve source URLs for `--context-header` |
| `--bundle` | — | *(none)* | Preset: `notebooklm` or `rag-standard` |
| `--score` | — | `false` | Computes LLM Readiness Score and writes `llm-readiness.json` |
| `--for-queries` | — | *(none)* | Queries file for query-oriented packing (requires `--strategy size`) |
| `--report` / `--no-report` | — | `--no-report` | Writes `readiness-report.html` with per-page extraction diff (implies `--score`) |

#### Pack internal pipeline

Operation order (each stage reads the output of the previous one):

```
list files → apply .docsignore → --no-extract? yes: full HTML / no: extract
           → --dedup → --bundle? cap max-chunks/max-words-per-chunk
           → --strategy (size|semantic) → boundary-aware chunking
           → --score? compute readiness
           → --format (md|txt|jsonl) + --context-header? inject → write
           → --cross-refs? annotate written chunks → --bundle? generate guide
```

#### Smart extraction (on by default)

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

#### Deduplication (`--dedup`)

Removes text blocks duplicated across files (headers, footers,
disclaimers, navigation). Three modes:

- **`exact`** — MD5 hash of a normalized block (lowercase + collapsed
  whitespace). Zero false positives.
- **`fuzzy`** — 64-bit SimHash + Hamming distance ≤ `--dedup-threshold`.
  Detects trivial variations ("page X of Y", timestamps).
- **`both`** — exact first (cheap), then fuzzy on the remainder.

Blocks with fewer than 10 words are ignored (prevents false positives
on repeated `<h1>`). The first occurrence (alphabetical order) is
always preserved.

#### Context header (`--context-header`)

Injects structured metadata in the `dograpper-context-v1` format
(JSON inside an HTML comment) at the top of each file within the chunk.
Fields:

```json
{
  "source": "flask.palletsprojects.com/en/stable/quickstart/index.html",
  "context_breadcrumb": ["Quickstart", "Routing"],
  "chunk_index": 2,
  "total_chunks": 5,
  "word_count": 4820,
  "url": "https://flask.palletsprojects.com/en/stable/quickstart/",
  "llm_readiness": {"score": 0.92, "grade": "A", "noise_ratio": 0.08},
  "schema_version": "v1"
}
```

Optional fields (`url`, `llm_readiness`) are omitted when not available
(they never appear as `null`). Full spec:
[docs/schema-v1.md](docs/schema-v1.md).

#### Cross-references (`--cross-refs`)

Extracts internal links from HTML, resolves relative paths, maps each
target to the chunk where the file was packed, and generates
`cross_refs.json` with `references_to`, `referenced_by`, and `links`
lists per chunk. The text is annotated in-place with `[-> chunk_id]`
markers, letting LLMs navigate between chunks.

Links pointing to files excluded via `.docsignore` appear as
`unresolved` (counted in the summary).

#### JSONL format (`--format jsonl`)

Each chunk becomes a `.jsonl` file where every line is an object per
source file. Ideal for RAG pipelines with their own downstream chunking.

Schema (required fields in **bold**, optional in italics):

- **`id`** — unique record identifier
- **`source`** — relative path of the original file
- **`words`** — word count
- **`content`** — extracted text
- **`schema_version`** — `"v1"`
- *`breadcrumb`, `chunk_index`, `total_chunks`* (with `--context-header` or `--score`)
- *`url`* (with `--context-header` **and** a matching manifest entry — `--score`
  alone never populates it)
- *`readiness_grade`* (with `--score`)

Field names diverge from the header format for word count, breadcrumb and
readiness — see the full field-by-field spec, including the JSONL/header
mapping table, in [docs/schema-v1.md](docs/schema-v1.md).

#### LLM Readiness Score (`--score`)

Per-chunk 0–1 score derived from three weighted metrics:

| Metric | Weight | What it measures |
|---|---|---|
| `noise_ratio` | 40% | Boilerplate remaining after extraction |
| `boundary_integrity` | 30% | Fraction of unbroken code/table blocks |
| `context_depth` | 30% | Mean heading depth (proxy for hierarchy) |

Final grade:
- **A** — score ≥ 0.8 (ready for direct use)
- **B** — 0.5 ≤ score < 0.8 (usable, consider refining extraction)
- **C** — score < 0.5 (review `.docsignore` or run `--dedup`)

Results are saved to `llm-readiness.json`. When combined with
`--context-header` or `--format jsonl`, the grade is injected into
headers/records.

#### Readiness report (`--report`)

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

#### Presets (`--bundle`)

Shortcuts for common combinations.

- **`notebooklm`** — hard ceiling, not a default: caps `max-chunks` at
  50 and `max-words-per-chunk` at 500,000 regardless of what the CLI
  flags request (`--max-chunks 100 --bundle notebooklm` still yields
  50 chunks). Does not set `strategy` or `format`.
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

#### Dry-run (`--dry-run`)

Simulates without writing. Prints: file count, word count, chunk
projection, top 10 by size, warnings. Use it to calibrate parameters
before the final pack.

#### Chunking strategies

- **`size`** (default) — walks files in alphabetical order, accumulating
  words. Cuts upon reaching `--max-words-per-chunk`. Boundary-aware:
  preserves atomic code/table blocks.
- **`semantic`** — groups files from the same directory (module) into
  the same chunk before applying the limit. Preserves thematic
  cohesion. Groups larger than the limit are subdivided.

#### Query-oriented packing (`--for-queries`)

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

#### Examples

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
```

### `dograpper explain`

Read-only preview of exactly what the LLM will receive per chunk —
audit before uploading to NotebookLM or ingesting into a RAG pipeline.
Nothing is written to disk.

```bash
dograpper explain ./chunks                  # list chunks (id, format, grade)
dograpper explain ./chunks docs_chunk_01    # inspect one chunk
dograpper explain ./chunks 01 --full        # bare index, full content
```

| Option | Default | Description |
|---|---|---|
| `--prefix` | `docs_chunk_` | Chunk filename prefix to inspect |
| `--full` | `false` | Print full section contents instead of a 60-word preview |

Per section it shows: the parsed `dograpper-context-v1` header (source,
URL, breadcrumb, per-chunk readiness), cross-references from
`cross_refs.json` (`references_to` / `referenced_by`), readiness detail
from `llm-readiness.json`, and the content preview — including the
`[-> chunk_id]` annotations exactly as the LLM sees them. Works with
`md`, `txt` and `jsonl` packs.

### `dograpper sync`

Convenience wrapper: `download` + `pack --delta` chained, with defaults
tuned for continuous maintenance. Forwards most `download` and `pack`
flags; calibration-only pack flags (`--report`, `--dry-run`) are
deliberately not exposed here.

```bash
dograpper sync <url> -o <dir> [options]
```

| Option | Alias | Default | Description |
|---|---|---|---|
| `--output` | `-o` | *required* | Mirror directory (mirrored HTML) |
| `--chunks-dir` | — | `<output>/chunks` | Chunk output directory |
| `--depth` | `-d` | `0` | Maximum depth (passed to `download`) |
| `--headless` | — | `false` | Playwright direct (passed to `download`) |
| `--delay` | — | `0` | Rate limiting in ms (passed to `download`) |
| `--include-extensions` | — | `html,md,txt` | Allowed extensions, comma-separated (passed to `download`) |
| `--max-words-per-chunk` | — | `500000` | Word limit (passed to `pack`) |
| `--max-chunks` | — | `50` | Chunk limit (passed to `pack`) |
| `--strategy` | — | `size` | `size` \| `semantic` (passed to `pack`) |
| `--format` | — | `md` | `txt` \| `md` \| `jsonl` \| `xml` (deprecated) (passed to `pack`) |
| `--bundle` | — | *(none)* | `pack` preset |
| `--context-header` | — | `false` | v1 header (passed to `pack`) |
| `--cross-refs` | — | `false` | Generates `cross_refs.json` and annotates chunks with `[-> chunk_id]` (passed to `pack`) |
| `--score` | — | `false` | LLM Readiness (passed to `pack`) |
| `--dedup` | — | `off` | `off` \| `exact` \| `fuzzy` \| `both` (passed to `pack`) |
| `--show-tokens` | — | `false` | Show per-chunk and total token count (passed to `pack`) |
| `--for-queries` | — | *(none)* | Queries file for query-oriented packing (passed to `pack`) |

`pack` is always executed with an implicit `--delta`: when the mirror
came back unchanged the pack step is skipped entirely, and when
anything changed the chunks are rebuilt in full. See
[ADR-0008](docs/adr/0008-delta-as-a-change-gate.md).

#### Examples

```bash
# Full sync with NotebookLM presets
dograpper sync https://docs.python.org/3/ -o ./py-docs --bundle notebooklm --context-header --score

# Daily cron sync (true incremental)
dograpper sync https://docs.rust-lang.org -o ./rust-docs --chunks-dir ./out/rust

# SPA sync
dograpper sync https://react.dev -o ./react-docs --headless --delay 500
```

### `dograpper drift`

Compare two `llm-readiness.json` snapshots (produced by `pack --score`)
and render a human-readable **context drift report**: chunks added,
modified (grade/score transitions) and removed, plus the exact
source-file lists from `delta_manifest.json` when available. Built for
CI — it powers the [GitHub Action](#github-action).

```bash
# Keep the previous snapshot, fully re-pack, then diff
cp ./chunks/llm-readiness.json /tmp/old-readiness.json
dograpper pack ./docs -o ./chunks --score
dograpper drift --new ./chunks/llm-readiness.json --old /tmp/old-readiness.json
```

| Option | Alias | Default | Description |
|---|---|---|---|
| `--new` | — | *required* | Freshly generated `llm-readiness.json` |
| `--old` | — | *(none)* | Previous snapshot. Omitted = first-run mode: every chunk reported as added |
| `--delta-manifest` | — | *(none)* | `delta_manifest.json` from `pack --delta`. A missing file is tolerated (`pack --delta` does not write it when nothing changed) |
| `--format` | — | `markdown` | `markdown` \| `text` |
| `--output` | `-o` | *(stdout)* | Write the report to a file instead of stdout |
| `--fail-on-drift` | — | `false` | Exit 1 when any drift exists (first run counts as drift) |

The markdown report always starts with the `<!-- dograpper-drift -->`
marker line, which the GitHub Action uses to update its PR comment in
place instead of posting a new one.

**Caveats**: chunk ids (`docs_chunk_NN`) are positional and can be
renumbered by upstream content changes, so chunk-level drift is
best-effort; the source-file lists from `delta_manifest.json` are exact.
Snapshots from a `--delta` run are directly comparable since
[ADR-0008](docs/adr/0008-delta-as-a-change-gate.md) — a delta run that
fires writes a complete `llm-readiness.json`. `--delta-manifest` is
meant for local use right after a `pack --delta` run — the file on disk
reflects the *last* delta run and can be stale (or absent) if nothing
changed; the GitHub Action does not use it and derives source drift
from git instead.

### `dograpper eval`

Empirically validates a packed context's retrieval quality: generates
deterministic golden Q&A from heading breadcrumbs, runs BM25 retrieval,
and reports hit-rate@k, MRR, and a per-grade breakdown. Fully offline —
no network calls.

```bash
dograpper eval <chunks_dir> [options]
```

| Option | Alias | Default | Description |
|---|---|---|---|
| `CHUNKS_DIR` | — | *required* | Directory containing the JSONL pack |
| `--top-k` | `-k` | `5` | Retrieval depth used to compute hit-rate |
| `--output` | `-o` | *(none)* | Write the JSON report to this path |
| `--prefix` | — | `docs_chunk_` | Chunk filename prefix to load |

Prerequisite: a pack built with `--format jsonl --context-header` —
golden Q&A generation needs the heading breadcrumbs that flag injects.
Exits 1 if no JSONL chunks match `--prefix`, or if none of the loaded
chunks carry a heading breadcrumb to generate a question from.

#### Examples

```bash
dograpper eval ./chunks
dograpper eval ./chunks -k 3 -o eval-report.json
```

### `dograpper init`

Onboarding wizard: generates a ready-to-use `.dograpper.json` tuned for
your ingestion target. Interactive by default; `--target` + `--yes` for
scripts.

```bash
dograpper init                          # interactive wizard
dograpper init --target rag --yes       # non-interactive
```

| Option | Alias | Default | Description |
|---|---|---|---|
| `--target` | `-t` | *(prompted)* | `notebooklm` \| `rag` \| `claude-project` |
| `--yes` | `-y` | `false` | Non-interactive mode (requires `--target`) |
| `--output` | `-o` | global `--config` path | Where to write the config |
| `--force` | `-f` | `false` | Overwrite an existing config file |

Targets:

- **`notebooklm`** — the `--bundle notebooklm` preset (≤50 balanced `md`
  chunks), semantic strategy, context headers, readiness score, dedup.
- **`rag`** — `jsonl` records with context headers, cross-references,
  readiness score and dedup.
- **`claude-project`** — compact `md` chunks (≤100k words), semantic
  strategy, context headers, readiness score and dedup.

Writing to a non-default path prints the `--config <path>` invocation
needed to consume it.

The generated file plugs into the standard config precedence
(defaults < `.dograpper.json` < explicit CLI flags) — any flag you pass
later still wins.

### `dograpper serve`

Serve a packed chunks directory as a **local MCP server** (stdio), so MCP
clients — Claude Code/Desktop, Cursor — can query the packed context live.
Stdlib-only implementation: no SDK, no network, fully offline.

```bash
# Pack for serving (jsonl + context + cross-refs + score)
dograpper pack ./docs -o ./chunks --format jsonl --context-header --cross-refs --score

# Register in Claude Code
claude mcp add my-docs -- dograpper serve ./chunks
```

| Option | Default | Description |
|---|---|---|
| `--prefix` | `docs_chunk_` | Chunk filename prefix to load |

MCP tools exposed:

| Tool | Purpose |
|---|---|
| `search_chunks(query, k)` | Deterministic BM25 top-k retrieval (id, source, breadcrumb, grade, excerpt) |
| `get_chunk(id)` | Full content of a record by id |
| `get_cross_refs(chunk_id)` | `references_to` / `referenced_by` navigation (needs `--cross-refs` pack) |
| `get_readiness(chunk_id?)` | Per-chunk readiness entry or the pack summary (needs `--score` pack) |

Retrieval reuses the same BM25 engine as `dograpper eval`, with stable
tie-breaking — the same query always returns the same order. The server
reads stdin line-by-line (JSON-RPC 2.0) and exits when the client closes
the pipe. Status messages go to stderr; stdout carries only the protocol.

### Global flags

| Flag | Alias | Default | Description |
|---|---|---|---|
| `--verbose` | `-v` | `false` | Detailed log (DEBUG + `[cascade]` prefixes) |
| `--quiet` | `-q` | `false` | Critical errors only |
| `--config` | — | `.dograpper.json` | Configuration file |
| `--version` | — | — | Print the installed version and exit |

`--verbose` and `--quiet` are mutually exclusive.

---

## GitHub Action

dograpper ships a composite GitHub Action (`action.yml` at the repo
root) that keeps your packed context fresh from CI: it downloads the
docs (`dograpper download`, when a `url` is given), always runs a
**full** `pack --score`, computes the drift against the previous
`llm-readiness.json` with [`dograpper drift`](#dograpper-drift), and
posts/updates a single drift report comment on the pull request. The
comment's source-file section comes from `git status` over `input-dir`
— exact lists, since the docs are versioned.

The action always runs a full `pack --score`, never `pack --delta`.
The original reason — a delta pack corrupting the snapshot — is gone
since [ADR-0008](docs/adr/0008-delta-as-a-change-gate.md); what remains
is that incrementality already lives at the download layer (wget
timestamping + manifest) and a full pack over unchanged sources is
deterministic, so no upstream change means an empty drift
(see [ADR-0007](docs/adr/0007-freshness-action-and-drift-command.md)).

It assumes **ubuntu runners** (python3, wget, `jq` and the `gh` CLI are
preinstalled) and that the docs mirror, the chunks directory (with
`llm-readiness.json`) and the repo-root `.dograpper-manifest.json`
(written relative to the working directory, not inside `chunks-dir`)
are **versioned in your repo**: that is what carries state across
stateless CI runners (see
[Incremental maintenance](#incremental-maintenance-cicd)).

```yaml
name: Context freshness

on:
  schedule:
    - cron: "0 6 * * 1" # weekly refresh
  pull_request:

permissions:
  contents: write
  pull-requests: write

jobs:
  freshness:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7

      - name: Refresh context and report drift
        id: freshness
        uses: your-user/dograpper@v1 # pin a tag (or a commit SHA), not a branch
        with:
          url: https://docs.example.com
          input-dir: ./docs
          chunks-dir: ./chunks
          pack-args: "--context-header"
          mode: warn # or `fail` to break the build on drift

      - name: Commit refreshed pack
        if: github.event_name == 'schedule' && steps.freshness.outputs.drift == 'true'
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add ./docs ./chunks .dograpper-manifest.json
          git diff --cached --quiet || git commit -m "chore: refresh packed context"
          git push
```

Inputs:

| Input | Default | Description |
|---|---|---|
| `url` | *(empty)* | Docs site URL. Set → `dograpper download` before packing; empty → only re-packs `input-dir` |
| `input-dir` | `./docs` | Downloaded docs directory (download output / pack input) |
| `chunks-dir` | `./chunks` | Packed chunks directory (versioned in the repo) |
| `pack-args` | *(empty)* | Extra flags appended verbatim to the pack command |
| `mode` | `warn` | `warn`: `::warning::` annotation on drift; `fail`: fail the job on drift (after posting the comment) |
| `comment` | `true` | Post/update the PR drift comment (`pull_request` events only) |
| `github-token` | `${{ github.token }}` | Token used by the `gh` CLI to post the comment |

Outputs: `drift` (`true`/`false`) and `report-path` (the markdown
report). The PR comment is upserted by matching the
`<!-- dograpper-drift -->` marker, so re-runs edit the same comment.

---

## Schema: `dograpper-context-v1`

Each chunk includes a structured and versioned JSON header (when
`--context-header` is active):

```html
<!-- dograpper-context-v1
{
  "source": "flask.palletsprojects.com/en/stable/quickstart/index.html",
  "context_breadcrumb": ["Quickstart", "Routing"],
  "word_count": 4820,
  "llm_readiness": {"score": 0.92, "grade": "A", "noise_ratio": 0.08},
  "schema_version": "v1"
}
-->
```

Full spec: [docs/schema-v1.md](docs/schema-v1.md)

---

## Generated artifacts

| Artifact | Flag | Description |
|----------|------|-----------|
| `docs_chunk_*.md` | (default) | Markdown chunks |
| `docs_chunk_*.jsonl` | `--format jsonl` | One JSON line per source file |
| `cross_refs.json` | `--cross-refs` | Cross-reference graph between chunks |
| `llm-readiness.json` | `--score` | Quality scores per chunk |
| `readiness-report.html` | `--report` | Visual before/after report with penalty causes |
| `IMPORT_GUIDE.md` | `--bundle` | Upload guide with recommended ordering (both `notebooklm` and `rag-standard`) |
| `delta_manifest.json` | `--delta` | Mapping of changed files |
| `pack_state.json` | `--delta` | Corpus state as of this pack; the next `--delta` run diffs against it |
| `.dograpper-manifest.json` | `download` | Mirror manifest (hashes + mtimes) |

---

## Configuration

Create a `.dograpper.json` file at the project root to avoid repeating flags:

```json
{
  "download": {
    "depth": 3,
    "include-extensions": "html,md",
    "manifest": ".dograpper-manifest.json"
  },
  "pack": {
    "max-words-per-chunk": 400000,
    "max-chunks": 50,
    "strategy": "semantic",
    "format": "md",
    "with-index": true,
    "context-header": true,
    "score": true,
    "dedup": "both"
  }
}
```

**Precedence**: code defaults → `.dograpper.json` → CLI flags.
CLI flags always win. Internally this uses Click's
`ctx.get_parameter_source()` to distinguish implicit defaults from
explicit values.

Use `--config` to point to a different file:

```bash
dograpper --config ./projects/rust/.dograpper.json pack ./rust-docs -o ./chunks
```

---

## `.docsignore` file

Create a `.docsignore` at the project root to exclude files from the
pack (gitignore syntax):

```gitignore
# Images
*.png
*.jpg
*.gif
*.svg

# Binaries
*.pdf
*.zip
*.tar.gz

# Unwanted pages
**/404.html
**/changelog/**
```

The file can be customized via `--ignore-file` or complemented with
inline `--ignore` (repeatable).

Binary and image extensions (`.png`, `.jpg`, `.gif`, `.svg`, `.pdf`,
`.zip`, `.tar.gz` and similar) are skipped automatically, unconditionally
— they don't need `.docsignore` entries. Use it for pages and paths that
are still text but you don't want packed.

---

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

Conditional extra lines (per enabled flag):

| Flag | Extra lines |
|---|---|
| `--show-tokens` | `Tokens per chunk`, `Total tokens`, `Encoding` |
| `--dedup` | `Dedup mode`, `Blocks analyzed`, `Blocks removed`, `Words removed` |
| `--cross-refs` | `Cross-refs: ./chunks/cross_refs.json (N links, M unresolved)` |
| `--score` | `LLM Readiness: ./chunks/llm-readiness.json`, `Grade distribution` |
| `--delta` | `Delta: N added, M modified, K removed`, `Delta manifest: ...` |
| `--bundle` | `Import guide: <path>` |
| `--for-queries` | `Query packing: ...` |

Warnings appear when:
- An individual file exceeds `--max-words-per-chunk` (it goes alone
  into a chunk, overshooting the stated limit).
- Total chunks exceed `--max-chunks` (nothing is discarded — every
  chunk is still written, just with a warning; use `--bundle
  notebooklm` for a hard cap that's actually enforced).

---

## Troubleshooting

### `download` fetches only 1 file

The site is a client-rendered SPA without `llms.txt` or an accessible
`sitemap.xml`. The anti-shell heuristic detects this and falls back
to Playwright automatically — if it doesn't, make sure `playwright` is
installed along with its system libraries (see [Installation](#installation-development)).

Expected log with the cascade working:

```
INFO: [cascade] layer-3 wget --mirror: link-graph fallback
INFO: [cascade] layer-4 playwright: --mirror yielded only 1 HTML file(s) (likely client-rendered index)
INFO: SPA detected, falling back to playwright
```

### `libnspr4.so: cannot open shared object file`

Missing system libs for Chromium. Run the apt install from the
[System dependencies](#system-dependencies) section.

### Cross-host sub-sitemaps being rejected

Since cascade v1.1, sub-sitemaps on different hosts are accepted when
the `path-prefix` identifies the project (same-netloc **OR**
path-prefix). Covers Mintlify (sub-sitemap at
`www.mintlify.com/<proj>/sitemap.xml`). If it still rejects them, run
with `-v` to see the decision in the log
(`sitemap: skipping out-of-scope sub-sitemap`).

### `pack --delta` packs everything on the first run

Expected behavior. `--delta` diffs the corpus against
`<output-dir>/pack_state.json`, written at the end of every successful
delta run. The first run has no baseline, so every file counts as
"added" and the pack runs in full.

### `pack --delta` re-packs every file even though only one changed

Also expected. `--delta` decides *whether* to pack, not *which* files
to pack: partial runs renumbered the chunks from 01 and overwrote the
artifacts of the files they did not touch. See
[ADR-0008](docs/adr/0008-delta-as-a-change-gate.md).

### Chunks too large for NotebookLM

`--bundle notebooklm` caps `--max-words-per-chunk` at 500,000 — with
the default (also 500,000) this produces no size reduction on its
own. Combine with `--strategy semantic` to keep modules cohesive, and
if chunks still overflow, lower `--max-words-per-chunk` explicitly
below the cap and combine with `--dedup both`.

### `wget returned 8` but the download looks fine

wget exit code 8 means "server error on some URLs" — treated as a
partial success. The manifest only records files that were actually
downloaded. Re-running (incremental) usually closes the gaps.

---

## Architecture

```
src/dograpper/
├── cli.py                    # Entry point, global flags (--verbose/--quiet/--config/--version)
├── commands/
│   ├── doctor.py              # Detect/install wget + chromium; --check-system-libs
│   ├── download.py            # 4-layer cascade + orchestration
│   ├── drift.py                # Diff two llm-readiness.json snapshots
│   ├── eval.py                  # Golden Q&A hit-rate@k / MRR over a JSONL pack
│   ├── explain.py                # Read-only preview of what an LLM receives per chunk
│   ├── init.py                    # .dograpper.json wizard, per-target presets
│   ├── pack.py
│   ├── serve.py                    # Local MCP server (stdio) over a packed JSONL
│   └── sync.py                # download + pack delta
├── lib/
│   ├── chunker.py            # size/semantic strategies, boundary-aware
│   ├── config_loader.py
│   ├── eval_harness.py        # hit-rate@k / MRR computation
│   ├── golden_qa.py            # Deterministic Q&A generation from heading breadcrumbs
│   ├── ignore_parser.py
│   ├── llms_txt_parser.py    # Layer 1 (stdlib-only)
│   ├── manifest.py           # Manifest + diff_manifests()
│   ├── mcp_server.py           # JSON-RPC 2.0 protocol for `serve`
│   ├── pack_artifacts.py       # Sidecar writers (cross-refs, delta, readiness, tokens)
│   ├── pack_reader.py           # Loads JSONL chunks back for eval/explain/serve
│   ├── pack_scoring.py          # LLM Readiness Score orchestration for `pack --score`
│   ├── playwright_crawl.py   # Layer 4 (bounded hydration + seed_urls)
│   ├── query_packer.py          # BM25 file ordering for `pack --for-queries`
│   ├── readiness_diff.py        # Snapshot comparison for `drift`
│   ├── retrieval.py             # Deterministic BM25 index (eval, serve)
│   ├── sitemap_parser.py     # Layer 2 (recursive sitemapindex, gzip)
│   ├── spa_detector.py       # Small-sample branch (N<5)
│   ├── url_filter.py         # Same-netloc + path-prefix + depth
│   └── wget_mirror.py        # Layer 3 (run_wget_mirror + run_wget_urls)
└── utils/
    ├── chunk_inspector.py      # Read-only chunk parsing for `explain`
    ├── content_extractor.py  # Smart extraction (strips boilerplate)
    ├── dedup.py              # Cross-file dedup (exact + fuzzy)
    ├── dep_resolver.py         # Resolves wget/chromium under DOGRAPPER_HOME
    ├── dry_run_report.py
    ├── heading_extractor.py  # Headings + format_context_header (v1)
    ├── html_stripper.py
    ├── link_extractor.py     # Cross-refs between chunks
    ├── logger.py
    ├── readiness_report.py     # HTML/terminal renderer for `pack --report`
    ├── scorer.py             # LLM Readiness Score
    ├── token_counter.py
    └── word_counter.py
```

---

## Development

```bash
# Install in editable mode with dev deps
uv sync --extra dev

# Run tests
uv run pytest tests/ -v

# Run a specific module
uv run pytest tests/test_download_cascade.py -v

# Run the CLI
uv run dograpper --help
uv run dograpper download --help
uv run dograpper pack --help
```

Every subcommand accepts `-h` as a shortcut for `--help` and prints
practical examples in the footer.

---

## License

MIT — see [LICENSE](LICENSE).
