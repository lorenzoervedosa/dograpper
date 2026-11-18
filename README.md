# dograpper

**Context Engineering Pipeline for Deterministic LLM Ingestion**

Turns HTML documentation into structured, deduplicated, scored, and versioned
context — ready for ingestion into NotebookLM, RAG pipelines, Claude Projects,
and fine-tuning.

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

## Quickstart

After [installing](#install):

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

## Install

### Release binary

> Release binaries are Linux x86_64 only.

```bash
curl -fsSL https://raw.githubusercontent.com/lorenzoervedosa/dograpper/main/scripts/install.sh | sh
dograpper doctor --install             # fetches wget + chromium
dograpper doctor --check-system-libs   # diagnoses missing system libs
dograpper --help
```

`install.sh` failures exit with a dedicated code — see
[Exit codes](#exit-codes).

#### Proxy / MITM

```bash
HTTPS_PROXY=http://proxy:3128 curl -fsSL https://raw.githubusercontent.com/lorenzoervedosa/dograpper/main/scripts/install.sh | sh
CURL_CA_BUNDLE=/path/to/cacert.pem curl -fsSL https://raw.githubusercontent.com/lorenzoervedosa/dograpper/main/scripts/install.sh | sh
```

#### Storage layout

| Path | Contents |
|------|---------|
| `~/.dograpper/bin/` | static wget |
| `~/.dograpper/playwright-browsers/` | chromium |

Override the default root: `DOGRAPPER_HOME=/custom/path dograpper doctor --install`

### From source

Requires Python 3.10+ and [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/lorenzoervedosa/dograpper.git
cd dograpper
uv sync --extra dev --extra headless --extra httrack   # same extras as CI
uv run dograpper --help
```

#### System dependencies

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

On Linux, Chromium requires native libraries. `dograpper doctor
--check-system-libs` lists the missing ones and prints the `apt install`
command. On Ubuntu 24.04+ / Debian 13+:

```bash
sudo apt install -y libnspr4 libnss3 libatk1.0-0 libatk-bridge2.0-0 \
  libcups2 libdrm2 libxkbcommon0 libxcomposite1 libxdamage1 libxfixes3 \
  libxrandr2 libgbm1 libpango-1.0-0 libcairo2 libasound2t64
```

On Ubuntu 22.04 / Debian 12 and older the package is called `libasound2`
(without the `t64` suffix).

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

Exit codes: see [Exit codes](#exit-codes).

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
| `--manifest` | — | `.dograpper-manifest.json` | Manifest file for incremental downloads. A relative path resolves against `-o` (so the default lives in the output directory); an absolute path is used as is |
| `--filter` | — | *(none)* | URL rule, repeatable: `+pattern` accepts, `-pattern` refuses, the last match wins (see [URL filters](#url-filters---filter)) |
| `--downloader` | — | `wget` | Download backend: `wget` or `httrack` (see [Downloader profiles](#downloader-profiles)) |

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
   Runs with `--no-parent` (lifted by a `+` [URL filter](#url-filters---filter)),
   `--timestamping` (always, enables incremental
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

#### URL filters (`--filter`)

`--filter RULE` scopes a crawl with HTTrack's scan rules. It is repeatable, is
read from `"filter": [...]` in `.dograpper.json` (a list; explicit flags replace
it) and is forwarded by `sync`. It works with both downloaders and is applied to
every discovered link before it is fetched: the llms.txt and sitemap lists,
`wget --mirror`, the Playwright crawl, and the httrack profile's seeded list and
redirect targets. The start URL itself is never filtered.

- `+pattern` accepts the URLs it matches and `-pattern` refuses them. Rules are
  read in order and the **last** matching rule decides.
- A URL that no rule matches keeps the default scope: same host, under the start
  URL's path, within `--depth`.
- A `+` rule lifts the path limit (wget's `--no-parent`) for the URLs it
  matches. Start with `-*` to make the `+` rules the whole scope.
- Rules never leave the start URL's host. This is a deviation from HTTrack, where
  `+other.host/*` widens the crawl to another site.

Pattern syntax, as HTTrack's `strjoker` matcher implements it. Patterns are
HTTrack wildcards, not regular expressions: `.`, `?` and `+` are literal
characters.

- A pattern is matched from the start of the URL. Write it with or without the
  scheme (`example.com/docs/*` or `https://example.com/docs/*`); the first form
  also ignores a `user:password@`. The fragment is ignored. The query string is
  part of the URL, and the URL is matched as discovered, percent-encoding
  unchanged.
- Literal text ignores ASCII case: `+*/wiki/on*` matches `/wiki/OnTick`.
- `*` matches any run of characters.
- `*[file]` (or `*[name]`) matches a run without `/` or `?`, and `*[path]` a run
  without `?`.
- `*[param]` matches an optional query string (`?…`).
- `*[a-z,0-9,_]` matches a run of the listed characters and ranges. It is
  case-sensitive, and `\` escapes one character (`*[\*]`, `*[\[,\]]`).
- `*[]` means the URL must end there.
- A pattern that does not end in `*[]` also matches the same URL followed by a
  query string: `-*/index.php` refuses `/index.php?action=edit` too, while
  `-*.html*[]` leaves `page.html?x=1` alone.
- Size rules (`*[<NN]`, `*[>NN]`), `mime:` rules and `*(...)` are not supported.
  They, and a rule that starts with neither `+` nor `-`, are a usage error
  (exit 2).

Under `--downloader wget`, `wget --mirror` receives the rules as
`--accept-regex` / `--reject-regex` (POSIX regex). These cannot let a `+` rule
override an earlier `-` rule, so such a list is a usage error before anything
is fetched: put the `-` rules after the `+` rules. Rules before a bare `-*` or
`+*` never decide anything and do not count for this check. The httrack
profile has no such limit.

The summary counts the refused URLs as `Filtered by --filter: N`; URLs outside
the default scope that no rule matched are not counted. Page requisites (CSS,
images) that `wget -i` fetches for a listed page are scoped by
`--include-extensions` only.

#### Downloader profiles

`--downloader` picks the backend for the fetch step (also accepted by `sync`,
which forwards every flag below, and as `"downloader"` in `.dograpper.json`).
Precedence is unchanged: defaults < JSON < explicit CLI.

- **`wget`** (default) — unchanged: the cascade above, with `wget` and
  Playwright.
- **`httrack`** — a pure-Python fetcher that reproduces HTTrack 3.51 on the
  wire (header set and order, `Accept-Encoding`, TLS settings) and in
  behavior (robots.txt longest-match, retries, pacing). Layers 1 and 2
  discover URLs through the same identity, following up to 5 same-host
  redirects with a robots.txt check before every hop; the seeded URLs are
  then fetched by the new engine.

`[httrack]` flags (an error under `--downloader wget` when given on the
command line, or set away from its default in `.dograpper.json`). Their
`.dograpper.json` keys get the same type and range checks as the flags, so
`"no-robots": "false"` means false and `"retries": 1.5` is rejected:

| Flag | Default | Meaning |
|---|---|---|
| `--user-agent` | `Mozilla/5.0 (compatible; dograpper/<version>)` | User-Agent header |
| `--no-robots` | off | Ignore robots.txt |
| `--connections` | `4` | Parallel connections (clamped to 8) |
| `--max-conn-rate` | `5.0` | Max connections opened per second (clamped to 5) |
| `--max-bandwidth` | `100000` | Max bytes/second (clamped to 10000000) |
| `--timeout` | `120` | Per-request timeout, seconds |
| `--retries` | `2` | Retries per URL |
| `--max-links` | `100000` | Max URLs fetched per run |
| `--max-retry-after` | `60` | Max seconds honored from `Retry-After` / `Crawl-delay` (hard cap 3600) |
| `--disable-security-limits` | off | Lift the connection, rate and bandwidth clamps |

`--delay` (ms) also applies. Deviations from HTTrack, deliberate because they
protect the corpus:

- Error and challenge bodies (non-2xx, Cloudflare interstitials) are never
  stored; they are counted in the end-of-run report.
- robots.txt `Crawl-delay` is honored (HTTrack ignores it).
- The discovery cascade is kept (llms.txt, sitemap).
- Nothing is purged from the output directory.
- TLS certificate verification stays on.
- robots rules are matched on the percent-escaped target, per RFC 9309;
  redirects when fetching robots.txt are followed on the same host only.

**OpenSSL >= 3.5.** The TLS handshake only matches HTTrack's on OpenSSL 3.5
or newer; on older builds `dograpper` warns and some CDNs may reject the
connection. Run on a uv-managed Python (`uv python install 3.13`), whose
interpreter bundles a recent OpenSSL. The release binary is built that way.

**Brotli and zstd.** `uv sync --extra httrack` (or `pip install
'dograpper[httrack]'`) installs `brotli>=1.2` and `zstandard>=0.22`, which let
the profile advertise and decode `br` / `zstd` over TLS. Without them it
advertises only what it can decode. Python 3.14's stdlib `compression.zstd`
is used when available. The release binary includes this extra.

**Current gaps (fail loud, exit 1).** Under `httrack`, recursive crawling
(cascade layer 3 when no llms.txt/sitemap wins) and the Playwright fallback
are not implemented yet; use `--downloader wget` for those sites. Link
rewriting also lands later, so `pack --cross-refs` finds fewer references in
httrack-fetched trees.

#### Incremental

A `.dograpper-manifest.json` manifest is generated after each download,
recording mirrored files with MD5 content hashes and mtimes. Future re-runs
use this manifest + `wget --timestamping` to fetch only files that
changed on the server.

The manifest lives in the output directory: a relative `--manifest`
resolves against `-o`, an absolute one is used as is, so a re-run from any
directory finds it and two mirrors never share one. It never lists itself,
`delta_manifest.json` or `pack_state.json`. `pack` reads it the same way,
relative to `INPUT_DIR` (its `--manifest` row says how a subdirectory of a
mirror finds the mirror's manifest). Up to 0.4.0 the default was relative to the current
directory; a manifest left there is not read (it may belong to another
mirror) and `download` says so in one line, then writes the new one in `-o`.
wget's own timestamping keeps that first run cheap.

Each entry's `url` is the URL dograpper requested for the file (the seed, a
discovered or a listed URL), and `pack --context-header` copies it into the
chunks. wget's log pairs each request with the file it saved or found up to
date; the Playwright and httrack layers record the URL they requested for
each file they write. After a redirect it is still the requested URL, never
the one the server redirected to: that one can carry a secret (a presigned
`X-Amz-Signature=...` link, a `token=`), and the manifest and every pack
built from it are meant to be shared. When several httrack seeds redirect to
one file, the one that needed no redirect wins, else the smallest URL.
`user:password@` is dropped. A URL with a query is recorded only when every
parameter name is a navigation name (`title`, `oldid`, `curid`, `diff`,
`pagefrom`, `pageuntil`, `from`, `until`, `page`, `p`, `id`, `lang`,
`uselang`, `hl`, `locale`, `v`, `version`, `section`, `tab`, `topic`, `view`,
`ns`, `namespace`, `category`, `cat`, `tag`, `q`, `query`, `search`, any
case); any other parameter gives `"url": null`. This fails closed on secrets
at the cost of the URL of pages whose query has another parameter. Logs and
failure reports keep such URLs but show the value of credential-like
parameters (`token`, `secret`, `key`, `sig`, `jwt`, `X-Amz-*`, ...) as
`REDACTED`.
A file the current run did not fetch keeps the `url` recorded when it was; a
file no run recorded gets `"url": null`. The saved path is never turned back
into a URL: `--adjust-extension` adds `.html`, a directory URL is saved as
`index.html`, and a query is decoded (wget), dropped (Playwright) or hashed
(httrack) in the file name.

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

# One MediaWiki category: the category page plus its member pages (/wiki/On*), nothing else
dograpper download "https://pzwiki.net/w/index.php?title=Category:Current_Lua_events&pagefrom=OnLoadSoundBanks" \
  -o ./lua-events -d 1 --filter '-*' --filter '+pzwiki.net/wiki/On*'

# Crawl a wiki category but skip unrelated meta pages
dograpper download https://pzwiki.net/wiki/Category:Lua_events -o ./lua-events -d 1 \
  --filter '-*/wiki/Category:En' --filter '-*/wiki/PZwiki:*' --filter '-*/wiki/Special:*'
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
| `--include-extensions` | — | `html,htm,md,txt` | Extensions packed as documentation (csv). Other files are skipped and counted by extension in the summary. `robots.txt` and dograpper's own manifests are always skipped |
| `--prefix` | — | `docs_chunk_` | Prefix for generated files |
| `--with-index` / `--no-index` | — | `--with-index` | Header with file index |
| `--format` | — | `md` | Output format: `md` (Markdown: `#` headings, `[text](target)` links, `-` / `N.` lists, pipe tables, fenced code; see [Markdown structure](#markdown-structure-md)), `txt` (plain text), `jsonl` (plain text records), `xml` (deprecated — errors, use `md`) |
| `--layout` | — | `chunk` | `chunk`: numbered chunk files. `page`: one file per page under `pages/` plus `INDEX.md` (see [Page layout](#page-layout---layout-page)) |
| `--no-extract` | — | `false` | Disable smart HTML content extraction |
| `--show-tokens` | — | `false` | Show token count in the final summary |
| `--token-encoding` | — | `cl100k` | Tokenizer encoding: `cl100k`, `o200k`, `p50k` |
| `--dry-run` | — | `false` | Simulate pack without writing; prints report |
| `--dedup` | — | `off` | Block deduplication: `off`, `exact`, `fuzzy`, `both` |
| `--dedup-threshold` | — | `3` | Maximum Hamming distance for fuzzy dedup (0-10) |
| `--context-header` | — | `false` | Injects `dograpper-context-v1` header (structured JSON), with the source `url` from the manifest or the page's HTTrack / saved-from marker |
| `--cross-refs` | — | `false` | Generates `cross_refs.json` and annotates chunks with `[-> chunk_id]` |
| `--delta` | — | `false` | Skip the run entirely when nothing changed since the last pack; pack in full when something did |
| `--manifest` | — | `.dograpper-manifest.json` | Download manifest, used to resolve source URLs for `--context-header`; its entry wins over a page marker. A relative path resolves against `INPUT_DIR`, an absolute one is used as is. Given explicitly, it must exist and load (exit 1 otherwise). Not given (or set in `.dograpper.json`), it is looked for in `INPUT_DIR` and, when `INPUT_DIR` lies inside a mirror (`<root>/<host dir>/...`), in its parents up to that root, at most 8 levels up and never above: packing a subdirectory finds the manifest `download` left in `-o`, and one in `/tmp` or `$HOME` is never picked up. The nearest wins, and one found above `INPUT_DIR` is named in a note. None found is skipped; a broken one is skipped with a note |
| `--bundle` | — | *(none)* | Preset: `notebooklm` or `rag-standard` |
| `--score` | — | `false` | Computes LLM Readiness Score and writes `llm-readiness.json` |
| `--for-queries` | — | *(none)* | Queries file for query-oriented packing (requires `--strategy size`) |
| `--report` / `--no-report` | — | `--no-report` | Writes `readiness-report.html` with per-page extraction diff (implies `--score`) |
| `--api-records` | — | `false` | Splits API reference pages (Javadoc) into one container record and one record per member; needs `--format jsonl` (see [API reference records](#api-reference-records---api-records)) |

#### Pack internal pipeline

Operation order (each stage reads the output of the previous one):

```
list files → apply .docsignore → skip bot-challenge pages
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

#### Markdown structure (`md`)

`md` writes the structure of each HTML page as Markdown. `txt` and `jsonl`
keep plain text, unchanged.

- `h1`–`h6` become `#`–`######` lines.
- A link becomes `[text](target)`, with the `href` as the page wrote it: a
  relative target names a file of the mirror (`Lua_(API).html`), an absolute
  one is kept. A target holding parentheses is written as `<...>`; spaces,
  `<`, `>`, `\` and control characters are percent-encoded. A link to the same
  page (`#anchor`, or `page.html#anchor` as mirrors rewrite it), with no
  target, or with a scheme other than `http`, `https` or `mailto`
  (`javascript:`, `data:`...) keeps only its text.
- `ul` / `ol` items become `-` / `N.` lines (an `ol`'s `start` is kept), with
  nested lists indented under their item. An item that holds a block (a
  heading, a `div`, a table or code, as Javadoc's member sections do) is
  written as its blocks, without a marker.
- A table becomes a pipe table with one line per row. Its first row is the
  header, and `|` inside a cell is escaped. A one-line `<pre>` in a cell
  becomes a code span, and a list in a cell is written inline. A table whose
  cell holds multi-line code, a heading or another table is written one cell
  per paragraph instead, so the code block keeps its lines.
- Word counts leave the markup out: heading and list markers, table pipes and
  the delimiter row are not words (context headers, `INDEX.md`,
  `llm-readiness.json`). `--max-words-per-chunk` measures each page's plain
  text, as for `txt`, so both formats put pages in the same chunks.
- Dedup and chunking treat a list or a table as one block, so `--dedup`
  removes a table repeated on several pages as a whole.
- `--cross-refs` writes its marker after the link it labels:
  `[Item](Item.html) [-> docs_chunk_02]`.

#### Deduplication (`--dedup`)

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
and `--dry-run` report `Pages exempted: N (API reference)`. API reference
pages from a generator without an adapter (TypeDoc, rustdoc, Doxygen) are
still deduplicated: run without `--dedup` on those corpora.

#### Context header (`--context-header`)

Injects structured metadata in the `dograpper-context-v1` format
(JSON inside an HTML comment) at the top of each file within the chunk:

```html
<!-- dograpper-context-v1
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
-->
```

Optional fields (`url`, `llm_readiness`, and the MediaWiki page metadata
`version` and `version_status`, written after `url`) are omitted when not
available (they never appear as `null`). A `>` in a value is written as
`\u003e`, so a value holding `-->` cannot close the comment. Full spec:
[docs/schema-v1.md](docs/schema-v1.md).

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

#### Cross-references (`--cross-refs`)

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
mapping table, in [docs/schema-v1.md](docs/schema-v1.md).

#### API reference records (`--api-records`)

An API reference page holds many symbols, and one record per page buries a
member's signature in a class-sized record. With `--api-records` (config key
`api_records`), each page that a generator adapter recognises is written as
one **container record** plus one **member record** per documented member
([ADR-0009](docs/adr/0009-api-reference-symbol-records.md)):

```bash
dograpper pack ./javadoc-mirror -o ./pack --format jsonl --api-records --context-header
dograpper serve ./pack   # search_chunks now ranks member records
```

- **Javadoc** (javadoc 25 type pages, `<meta name="generator"
  content="javadoc/ClassWriter">`) is the only adapter so far.
- **Container record** (`id` `NN_path`): qualified name and kind, inheritance,
  implemented interfaces and known subclasses, signature, description, the
  declared member names, and the "inherited from" lists. Summary tables are
  dropped.
- **Member record** (`id` `NN_path#anchor`): the qualified name
  (`zombie.characters.IsoGameCharacter#getInventory()`), the full signature
  with its type parameters, the doc comment and the notes (Overrides,
  Specified by, Parameters, Returns, Throws). `url` ends with the member's
  anchor; `breadcrumb` is `[container, member]`.
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

Field list: [docs/schema-v1.md](docs/schema-v1.md#api-records---api-records).

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

A chunk whose extracted content is empty (0 words) is always graded **C**
with score 0, regardless of the other metrics.

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

#### Page layout (`--layout page`)

For readers that open files by name and `grep` them, such as Claude Code,
`--layout page` writes one file per page instead of numbered chunks
([ADR-0010](docs/adr/0010-per-page-pack-layout.md)):

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
  `LPT1`–`LPT9`, any case) and a name ending in a dot or a space get a
  trailing `_`. Names that differ only in case get `-2`, `-3`… in sorted
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
| `--delta` | the [ADR-0008](docs/adr/0008-delta-as-a-change-gate.md) gate is unchanged; a run that passes it rebuilds `pages/` in full |
| `--context-header` | one header at line 1 of each page file: `title`, `source`, `url`, `version`, `version_status`, `word_count`, `llm_readiness`; no breadcrumb or outline |
| `--cross-refs` | markers name the page from the output root, `[-> pages/Target.md]`; `cross_refs.json` is keyed by page path |
| `--score`, `--report` | one score per page; `chunk_id` in `llm-readiness.json` is the page path, stable across runs |
| `--dry-run` | projects the page count; never needs or touches `pages/` |

`explain`, `serve`, `eval` and the GitHub Action read the chunk layout only.
Do not mix layouts in one output directory: `pack` never deletes chunk files.

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

# One file per page plus INDEX.md, for grep-and-Read readers
dograpper pack ./docs -o ./wiki-ref --layout page --context-header
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
| `--filter` | — | *(none)* | URL rule, repeatable (passed to `download`; see [URL filters](#url-filters---filter)) |
| `--downloader` | — | `wget` | `wget` \| `httrack` (passed to `download`; see [Downloader profiles](#downloader-profiles)) |
| `[httrack]` flags | — | see [Downloader profiles](#downloader-profiles) | `--user-agent`, `--no-robots`, `--connections`, `--max-conn-rate`, `--max-bandwidth`, `--timeout`, `--retries`, `--max-links`, `--max-retry-after`, `--disable-security-limits` (passed to `download`) |
| `--max-words-per-chunk` | — | `500000` | Word limit (passed to `pack`) |
| `--max-chunks` | — | `50` | Chunk limit (passed to `pack`) |
| `--strategy` | — | `size` | `size` \| `semantic` (passed to `pack`) |
| `--format` | — | `md` | `txt` \| `md` \| `jsonl` \| `xml` (deprecated) (passed to `pack`) |
| `--layout` | — | `chunk` | `chunk` \| `page` (passed to `pack`) |
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
| `--target` | `-t` | *(prompted)* | `notebooklm` \| `rag` \| `claude-project` \| `claude-code` |
| `--yes` | `-y` | `false` | Non-interactive mode (requires `--target`; exit 2 without it) |
| `--output` | `-o` | global `--config` path | Where to write the config |
| `--force` | `-f` | `false` | Overwrite an existing config file (never an existing `SKILL.md`) |
| `--skill-dir` | — | `docs-skill` | `claude-code` only: the directory you will pack into; a `SKILL.md` stub is written there unless one exists |

Targets:

- **`notebooklm`** — the `--bundle notebooklm` preset (≤50 balanced `md`
  chunks), semantic strategy, context headers, readiness score, dedup.
- **`rag`** — `jsonl` records with context headers, cross-references,
  readiness score and dedup.
- **`claude-project`** — for a Claude Project (claude.ai Projects knowledge):
  compact `md` chunks (≤100k words) to upload, semantic strategy, context
  headers, readiness score and dedup.
- **`claude-code`** — for Claude Code: the
  [page layout](#page-layout---layout-page) (`layout: page`, `format: md`),
  one context header per page and `dedup: off` (dedup keeps a repeated block
  on one page only, #89). It sets no chunk-only key, so `pack` accepts it
  without a warning. It also writes a `SKILL.md` stub into `--skill-dir`:
  frontmatter `name` (from the directory name) and a `description` to fill
  in, a link to `INDEX.md`, and the grep-then-Read lookup steps.

A Claude Project and Claude Code are different targets. A Claude Project
receives uploaded files whole, so it gets a few large chunks. Claude Code
reads a local directory on demand: it finds a file by name or with `grep`
and reads a bounded slice of it, so it gets one file per page, named after
the page, plus an index.

`init` writes `SKILL.md` once and never rewrites it, even with `--force`;
`pack` never touches it either, so the description you write survives every
repack. Pack into the skill directory, then register it:

```bash
dograpper init --target claude-code --yes --skill-dir ./pz-wiki
dograpper download https://docs.example.com/ -o ./docs
dograpper pack ./docs -o ./pz-wiki                 # INDEX.md + pages/, SKILL.md kept
# edit the description in ./pz-wiki/SKILL.md, then, for every project:
mkdir -p ~/.claude/skills && ln -s "$PWD/pz-wiki" ~/.claude/skills/pz-wiki
# or for one project: ln -s "$PWD/pz-wiki" <project>/.claude/skills/pz-wiki
```

Keep the link name equal to the `name` in `SKILL.md`. `claude --add-dir
<dir>` loads skills from `<dir>/.claude/skills/`; adding the pack directory
itself only gives the session read access to its files.

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

### `dograpper docs`

Serve a **local reference site** for every command and option, generated at
run time from the installed CLI, so it always matches `--help`. One
self-contained page (no external stylesheet, script, font or image), so it
works offline and from the release binary. Each option has an anchor, for
example `#download--depth`.

```bash
dograpper docs                      # serves http://127.0.0.1:8000/ and opens the browser
dograpper docs --port 9000 --no-browser
```

| Option | Default | Description |
|---|---|---|
| `--port` | `8000` | TCP port, bound on `127.0.0.1` only. A busy port exits non-zero; it never moves to another port |
| `--no-browser` | off | Only print the URL (always printed) instead of opening the browser |

Stop the server with Ctrl+C.

### Global flags

| Flag | Alias | Default | Description |
|---|---|---|---|
| `--verbose` | `-v` | `false` | Detailed log (DEBUG + `[cascade]` prefixes) |
| `--quiet` | `-q` | `false` | Critical errors only |
| `--config` | — | `.dograpper.json` | Configuration file |
| `--version` | — | — | Print the installed version and exit |

`--verbose` and `--quiet` are mutually exclusive.

---

## Exit codes

| Code | Origin | Meaning | Remediation |
|------|--------|---------|-------------|
| 0 | any | success | — |
| 1 | doctor (default) | one or more deps missing | run `dograpper doctor --install` |
| 1 | doctor --install | download, SHA256 verification, or the chromium install step failed | retry, check network/proxy |
| 1 | doctor --check-system-libs | `ldd` not found on this system | install `ldd` (usually part of `libc-bin`) |
| 1 | download / crawl | chromium not installed, or any other crawl failure | run `dograpper doctor --install` |
| 1 | download --downloader httrack | every seed refused/challenged | retry later, switch to `--downloader wget`, or change network |
| 1 | pack --context-header --manifest | the manifest named with `--manifest` is missing or cannot be loaded | fix the path, or re-run `dograpper download` to rewrite the manifest |
| 1 | pack --layout page | `pages/` exists in the output directory without `INDEX.md`, or a page file cannot be written | move that `pages/` away or pick another `--output`; free space or fix permissions |
| 2 | pack --layout page | a chunk-only setting, `--bundle`, `--for-queries`, `--format jsonl` or `--dedup` other than `off` | drop the setting, or use `--layout chunk` |
| 1 | download | the manifest cannot be written | fix permissions or free space in `--output`; the mirror itself is complete |
| 1 | pack --delta | `pack_state.json` cannot be written | fix permissions or free space in `--output`; the chunks are complete, the next `--delta` run packs in full |
| 2 | pack | `--output` is the same directory as `INPUT_DIR` | use a subdirectory or another path |
| 2 | doctor --check-system-libs | system libs missing | run suggested `apt install ...` |
| 3 | doctor --check-system-libs | chromium not installed | run `dograpper doctor --install` |
| 4 | doctor --install | concurrent install lock held | wait for other install, retry |
| 10 | install.sh | SHA256 mismatch | retry install, report issue |
| 20 | install.sh | unsupported architecture | — |
| 21 | install.sh | unsupported OS | — |
| 30 | install.sh | binary or checksum download failed | check network/proxy, retry |

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
preinstalled) and that the docs mirror (`input-dir`, which holds the
`.dograpper-manifest.json` that `download` writes there) and the chunks
directory (with `llm-readiness.json`) are **versioned in your repo**: that is
what carries state across stateless CI runners (see
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
        uses: lorenzoervedosa/dograpper@v0.4.0 # pin a release tag (or a commit SHA), not a branch
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
          git add ./docs ./chunks
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

The manifest is left out of the comment's source-file list (it changes on
every download). Up to 0.4.0 it was written at the repo root; that file is no
longer read and can be deleted once `input-dir` holds the new one.

---

## Generated artifacts

| Artifact | Flag | Description |
|----------|------|-----------|
| `docs_chunk_*.md` | (default) | Markdown chunks (headings, links, lists, tables, code) |
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
| `--score` | `LLM Readiness: ./chunks/llm-readiness.json`, `Grade distribution` |
| `--delta` | `Delta: N added, M modified, K removed`, `Delta manifest: ...` |
| `--bundle` | `Import guide: <path>` |
| bot-challenge pages found | `Challenge pages: N` |
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
installed along with its system libraries (see [System dependencies](#system-dependencies)).

Expected log with the cascade working:

```
INFO: [cascade] layer-3 wget --mirror: link-graph fallback
INFO: [cascade] layer-4 playwright: --mirror yielded only 1 HTML file(s) (likely client-rendered index)
INFO: SPA detected, falling back to playwright
```

### `libnspr4.so: cannot open shared object file`

Missing system libs for Chromium. Run `dograpper doctor
--check-system-libs` for the exact `apt install` command, or see
[System dependencies](#system-dependencies).

### Cross-host sub-sitemaps being rejected

Sub-sitemaps on different hosts are accepted when
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
downloaded. The failing URLs are listed at the end of the `Download complete`
summary as `Failed: N URLs (first 5 shown)`, each with its HTTP status; add
`--verbose` (before the subcommand) to list all of them. A missing
`robots.txt` is not counted. Re-running (incremental) closes transient gaps,
but a permanent 404 stays missing.

---

## Development

After [installing from source](#from-source):

```bash
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
