# dograpper download

Mirrors a documentation site to local disk.

```bash
dograpper download <url> -o <directory> [options]
```

## Discovery cascade (4 layers)

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
   The probe also tries `sitemap_index.xml` and `sitemap-index.xml`; under
   `httrack` and `fire-engine`, the `Sitemap:` lines of robots.txt (same host
   only) are probed first.
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

## Observability

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

While pages are fetched (by `download`, and so by `sync`), each fetch step
prints a `[progress]` line at most every 5 seconds and only when something
changed, plus a final line when the step ends. These are INFO lines, so
`--quiet` hides them, and their URLs are redacted like every logged URL.

A fixed URL list (`wget -i` over the llms.txt or sitemap URLs, and the httrack
profile's seeded list, shown as `httrack:`) counts URLs of the list, not saved
files: wget also fetches robots.txt, redirect targets and page requisites. The
ETA appears once 10 URLs are done:

```
INFO: [progress] wget -i: 37/120 URLs (31%) · 2.1 MB · 1m12s · ETA ~3m
```

A crawl whose total grows as it goes (`wget --mirror`, and Playwright, whose
queue keeps growing even when seeded) has no percentage and no ETA:

```
INFO: [progress] wget --mirror: 142 files · 8.3 MB · 1m12s · last: https://example.com/guide/
INFO: [progress] playwright: 23 files · 1m05s · queued 41 · last: https://example.com/api/
```

The Playwright crawl's per-page `Downloading: <url>` line needs `--verbose`.

## URL filters (`--filter`)

`--filter RULE` scopes a crawl with HTTrack's scan rules. It is repeatable, is
read from `"filter": [...]` in `.dograpper.json` (a list; explicit flags replace
it) and is forwarded by `sync`. It works with every downloader and is applied to
every discovered link before it is fetched: the llms.txt and sitemap lists,
`wget --mirror`, the Playwright crawl, and the httrack profile's seeded list,
recursive crawl and redirect targets. The start URL itself is never filtered.

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

## Downloader profiles

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
  then fetched by the new engine, which rewrites the links between the saved
  pages as the crawl below does. Each seed is a start URL: it is requested
  without `Referer`, and a redirect target as the crawl requests a start
  URL's (the seed as `Referer` for a page target, `Sec-Fetch-Site: none`). When neither layer finds a list, the
  engine crawls the site from the start URL instead of `wget --mirror`
  (below).
- **`fire-engine`** — the `httrack` crawl over a `curl_cffi` transport that
  sends a browser TLS/HTTP-2 fingerprint, for documentation behind a WAF that
  rejects the stdlib handshake even though the content is public. Same
  discovery, scope, pacing, robots.txt and link rewriting as `httrack`; only
  the wire client differs. Adds `--proxy` (one proxy for every request) and
  `--impersonate` (the `curl_cffi` browser profile, default `chrome`). Needs
  the `fire-engine` extra (below). See [ADR-0011](https://github.com/lorenzoervedosa/dograpper/blob/main/docs/adr/0011-fire-engine-downloader.md).

**Recursive crawl (`httrack`).** Breadth-first from the start URL, as
HTTrack's mirror loop:

- **Links:** `href` and HTTrack's link attributes (`src`, `srcset`,
  `data-src`, `poster`, `background`, `data`, `longdesc`, `xlink:href`...),
  `<meta http-equiv="refresh">` and CSS `url()` / `@import` (`<style>`,
  `style=` and fetched stylesheets). `<base href>` applies to the links after
  it; form `action` is never followed. A `<meta name="robots"
  content="nofollow">` stops link extraction for the rest of that page
  (ignored with `--no-robots`). Each request carries the `Referer` and the
  `Sec-Fetch-*` values HTTrack sends for that kind of link.
- **Scripts** (HTTrack `-j`, on): `<script>` and `<style>` bodies, `onXxx=`
  and `style=` values, `javascript:` URLs and fetched scripts are scanned
  statically, as HTTrack does, outside comments and strings, for
  `x.src = "…"`, `location = "…"`, `.href`, `.open("…")`, `url(…)`,
  `import "…"` and `from "…"` (nothing is executed). A script's links resolve
  against the page that loaded it, a module specifier against the script, and
  carry no `Sec-Fetch-*`. Scripts are fetched only when `js` is in
  `--include-extensions`.
- **Extended parsing** (HTTrack `-%P`, on): a quoted string after `=`, `(` or
  `,`, in a script or in an attribute that is not a link one (`data-page="a.html"`,
  `content="/og.png"`), is followed when it names a file (a known extension, or
  a scheme), except in attributes that never hold one (`alt`, `class`, `title`,
  `id`…) and framework bindings (`:x`, `v-x`, `@x`).
- **Scope:** the start host only; under the start URL's directory
  (`/docs/index.html` → `/docs/`, `/modding` → `/`, `/modding/` →
  `/modding/`) unless a `--filter` rule decides; `--depth` counts link hops
  from the start URL (0 = unlimited); `/cdn-cgi/` is never fetched; at most
  `--max-links` URLs, after which the report says `Partial`. Links whose
  extension HTTrack knows as a non-page type outside `--include-extensions`
  (images, CSS, PDF...) are not requested; any other page is fetched, its
  links followed, and kept only when its saved name passes
  `--include-extensions`.
- **Dedup and names:** a URL is fetched once per HTTrack key (fragment
  dropped, `//` collapsed, query keys sorted) and saved with the same names
  as the seeded fetch.
- **Redirects:** the target is queued as a fresh link and passes the same
  scope, filter and robots checks; links to the redirecting URL then point at
  the target's file. As in HTTrack, a page target is requested with the
  redirecting URL as `Referer` (a known non-page type, with the linking page),
  the original link's `Sec-Fetch-*` and the worst `Sec-Fetch-Site` of the
  chain (`none` after a start URL).
- **Links rewritten** (HTTrack `-K0`): once the crawl ends, every saved HTML
  page links to the files saved for its links with relative paths, other
  links become absolute URLs, and `<base href>` is emptied. The links found
  in scripts, stylesheets and quoted strings (above) are rewritten too, in
  pages and in saved stylesheets and scripts, as HTTrack writes them: the
  relative path percent-encoded, `(` `)` as `%28` `%29` inside a CSS `url()`,
  the link's query kept, `&` as `&amp;` only inside a tag; a script's links
  are written from the page that loaded it (a module specifier from the
  script). The mirror browses offline and `pack --cross-refs` resolves its
  links. No other byte of the file changes.
- **Output is deterministic:** requests run in parallel, but responses are
  handled in queue order, so names, files, report and manifest never depend on
  which request finished first.
- **Progress:** `[progress] httrack crawl: 142 files · 8.3 MB · 1m12s ·
  queued 41 · last: https://example.com/guide/`.
- **Exit 1** when the start URL (or the redirect chain it starts) is refused,
  challenged, blocked by robots.txt or leaves the host; on an update, a start
  URL whose previous copy was kept after an error is no failure (below). A
  crawl that saves at most one HTML page, or an SPA shell, falls back to
  Playwright under the profile (below).

**File times (`httrack`, `fire-engine`).** Each saved file gets the response's
`Last-Modified`, else its `Date`, as its modification and access time, as
HTTrack sets them once a file is complete (links rewritten first). The date
is read as HTTrack reads it: any zone counts as GMT, and a date that does not
read leaves the file's time alone. `pack --delta` compares content hashes, so
a file rewritten with other bytes under the same time and size still counts
as changed.

**Updates (`httrack`, `fire-engine`).** A run on an `-o` that already holds a manifest is an
update, as HTTrack's `-C2` on a finished mirror: on both paths, each file the
previous run recorded from a `200` (or a `203`), still on disk and not empty,
is requested again.

- The request starts with `If-None-Match: <etag>` and `If-Modified-Since:
  <date>` (or the one recorded), as HTTrack sends them. The date is the
  response's `Last-Modified`, else its `Date`. A file recorded with neither
  gets a plain request, and a 2xx replaces it.
- **304 Not Modified:** the file is left byte-identical (its links are not
  rewritten again) and keeps its manifest record; the crawl follows the links
  of a kept page, stylesheet or script from that copy.
- **Any other answer but a 2xx or a redirect** (404, 500, 429, a challenge):
  the previous copy is kept and the answer is not retried, as HTTrack does on
  an update. The URL is listed as `Kept the previous copy after an error` (a
  challenge under `Challenged`). A challenged start URL still exits 1.
- **A failed transfer** (timeout, connection or decoding error) is retried,
  reported as an error, and the previous copy and its record are kept (its
  links are not followed).
- **A 2xx** replaces the file and its record. A file erased or emptied since
  is fetched again in full (unless `--do-not-recatch`, below).
- The summary counts the kept files as `Files skipped: N (cached)`, the 304s
  as `Not modified (304): N`, and the files of the previous run this one did
  not reach as `Not reached this run, kept on disk: N` (`--verbose` lists
  them; nothing is deleted).
- A file the update may keep keeps its name: a page added to the site never
  takes it over. A manifest entry whose file is not named as its URL would be
  (an edited manifest) is ignored, so the manifest never decides where a page
  is written.

**Cache modes (`--cache`, HTTrack `-C`).** The default is HTTrack's: `2` (the
update above) when `-o` holds a manifest, else `1`.

- `--cache 2` (HTTrack `--update`): each recorded file is revalidated, as
  above.
- `--cache 1` (HTTrack `--continue`): a file recorded from a 2xx and still on
  disk at its recorded size is not requested at all; the crawl follows its
  links from that copy, and the summary counts it as `Loaded from cache
  without a request: N`. A file whose size changed is fetched in full, with no
  validator.
- `--cache 0`: the manifest's records are neither used nor written. Every file
  is fetched in full, with no validator, and keeps the record the previous run
  made for its URL (a file that run did not record gets none), so a later
  `--cache 2` run revalidates against the previous records, as HTTrack's next
  update revalidates against the cache a `-C0` run left alone. No file is
  listed as not reached.

**Update hacks (`--updatehack`, HTTrack `-%s`, off).** For a recorded file
that is not a page, a script or a stylesheet, a `200` whose `Content-Length`
is the size of the copy on disk (and, when validators were sent, the size the
manifest recorded) keeps that copy and its record, as a 304 would: the body is
never read and the connection is dropped, as HTTrack drops it. The summary
counts these as `Kept on a matching size (--updatehack): N`.

**Change report (`--changes`, HTTrack `-%d`, off).** The run writes
`hts-changes.json` in `-o`, in HTTrack's format, and prints its summary
(`Change report: 2 new, 1 changed, 40 unchanged, 1 gone (hts-changes.json)`;
on a first crawl `Change report: first crawl, N files mirrored, nothing to
compare against (hts-changes.json)`, and under `--cache 0` `Change report: no
mirror index (the cache is off), N files mirrored, deletions not detected
(hts-changes.json)`). Each file is listed once, with its `url`, its `file`
(the path under `-o`) and its `size`:

- `new`: no copy before this run;
- `changed` (with `previous_size`): a page whose payload, the body as
  received before its links were rewritten, differs from the one its manifest
  record holds (`payload_md5`), or another file whose bytes differ;
- `unchanged`: a file left as it was, or rewritten with the same payload or
  bytes;
- `gone`: a file of the previous run no link reached this run (a URL the run
  requested without keeping it is `unchanged`).

`first_crawl` is `true` without a previous manifest, and `null` under
`--cache 0`, which lists nothing as gone. `purged` and `partial` are always
`false`; `schema`, `generator`, `date` and `counts` (files per bucket) head the
document. A URL is written as the manifest writes it (`""` when the manifest
records none); a `gone` file, and a file of the previous run that was
requested without being kept, has `"url": ""`, and a `gone` file has no
`size`. A run that fails leaves the previous report as it was.

**`--do-not-recatch` (HTTrack `-%n`, off).** A recorded file other than a
page, a script or a stylesheet that was erased or emptied since is not fetched
again: a missing one is created empty, and its URL is listed under `Errors` as
`null-size file not recaught`, as HTTrack logs it. A page, script or
stylesheet is fetched again in full (HTTrack restores it from the body its
cache holds).

`[httrack, fire-engine]` flags (see [Options](#options)) (an error under `--downloader wget` when given on the
command line, or set away from its default in `.dograpper.json`). Their
`.dograpper.json` keys get the same type and range checks as the flags, so
`"no-robots": "false"` means false and `"retries": 1.5` is rejected.

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
- A start URL that redirects out of its directory on the same host moves the
  crawl scope to the target's directory (HTTrack would mirror nothing).
- A `--filter` rule never widens the crawl to another host.
- No asset mirroring: the crawl does not request links whose extension is a
  known non-page type left out of `--include-extensions`.
- Link rewriting: a link to a file the run did not save is made absolute
  (HTTrack writes the name it planned); an absolute link is left as written;
  a link attribute (`href`, `src`...) escapes only `%` and `#` of a saved name
  and drops the query, so `pack --cross-refs` resolves it.
- Updates keep no cache beside the mirror (HTTrack's `hts-cache/`), so:
  - the manifest never records a redirect target: the validators of a file
    reached through a redirect go to the hop whose file name is that file's;
  - the links of a kept page are read from the saved copy and mapped back
    through the manifest: a file recorded with `"url": null` is not reached
    from a kept page and never revalidated;
  - a kept file is never renamed nor rewritten, and a kept script's links are
    read against the page that loads it in this run;
  - robots.txt is fetched in full on every run;
  - under `--cache 1`, the redirecting URL of a file reached through a
    redirect is still requested (its target is not), and a page, script or
    stylesheet whose size changed is fetched in full, where HTTrack loads both
    from its cache.
- Under `--cache 1 --do-not-recatch`, a file whose size changed is fetched in
  full and left as it was if that fails; HTTrack empties it before the request.
- A `Retry-After` on a revalidation still pauses the whole queue, and a
  challenged start URL still exits 1 on an update (HTTrack treats both as a
  304).

**OpenSSL >= 3.5.** The TLS handshake only matches HTTrack's on OpenSSL 3.5
or newer; on older builds `dograpper` warns and some CDNs may reject the
connection. Run on a uv-managed Python (`uv python install 3.13`), whose
interpreter bundles a recent OpenSSL. The release binary is built that way.

**Brotli and zstd.** `uv sync --extra httrack` (or `pip install
'dograpper[httrack]'`) installs `brotli>=1.2` and `zstandard>=0.22`, which let
the profile advertise and decode `br` / `zstd` over TLS. Without them it
advertises only what it can decode. Python 3.14's stdlib `compression.zstd`
is used when available. The release binary includes this extra.

**Playwright under the profile (`httrack`).** With `--headless`, or when the
engine's result looks client-rendered (an SPA shell, or a crawl that saved at
most one HTML page), the cascade's layer 4 runs under the profile, never as
the `wget` cascade's Playwright:

- **Every navigation is fetched by the profile.** The browser asks, the
  profile's own client fetches it (same TLS, headers, pacing, retries,
  `Retry-After`, robots.txt before each hop) and hands the response to
  Chromium. A redirect is resolved by the profile before the page opens, its
  target in the crawl's scope and checked against robots.txt.
- **A challenge never renders.** A response with `cf-mitigated` or the
  "Just a moment..." title, a non-2xx, a URL robots.txt forbids or one out of
  scope is aborted before the browser sees a byte of it, so no challenge
  script runs; the report lists it as the engine's would. `/cdn-cgi/` is
  never requested, not even by a script of a page.
- **Subresources** (scripts, styles, XHR the page needs to render) are the
  browser's own requests, with the profile's User-Agent, neither checked
  against robots.txt nor paced: they are dependencies of a page the policy
  already let through, as in an ordinary visit (a decided exception to the
  profile's rule that every request goes through it). Routing every request
  turns Chromium's HTTP cache off, so each page fetches them again. An
  iframe, a popup or a navigation the page starts itself (meta refresh,
  `location =`) is not followed yet ([#159](https://github.com/lorenzoervedosa/dograpper/issues/159)),
  and service workers are blocked.
- **Scope, names, links:** a seeded run opens its seeds alone, as the seeded
  fetch does; links of a rendered page follow the crawl's scope (start host,
  start directory, `--filter`, `--depth`, `--max-links`, a known non-page type
  outside `--include-extensions` never requested) and are requested with the
  page as `Referer`. Pages are saved with the engine's names, from the final
  URL, and their links rewritten as the crawl rewrites them. A response that
  is no HTML page is saved as it came, never opened in the browser. File
  times and manifest records are the response's.
- **Each page in full.** `--headless` skips the engine's fetch, so no page is
  revalidated: `--cache`, `--updatehack`, `--do-not-recatch` and `--changes`
  with `--headless` are a usage error (exit 2). After an engine fetch that
  looked client-rendered, the browser fetches every page again (reusing the
  engine's copy is planned, [#160](https://github.com/lorenzoervedosa/dograpper/issues/160)); a crawl that
  saved one page because the rest was challenged is no trigger (no browser
  run, the report lists the challenges).
- **Report and exit.** After an engine fetch, the browser's own report follows
  the engine's under `Playwright pass:`; if the browser saves nothing, the
  engine's files stand and the run exits 0. Under `--headless` the run exits 1
  when the browser saves no page (the start URL, or every seed, refused,
  challenged or failing), with the report printed first. Needs the `headless`
  extra and `dograpper doctor --install` for Chromium, as the `wget` cascade's
  Playwright does.

### fire-engine

`--downloader fire-engine` runs the `httrack` crawl with its wire client
replaced by `curl_cffi`, which sends a real browser's TLS/HTTP-2 fingerprint so
a WAF that checks the handshake (common in front of public docs) accepts the
request. All `[httrack, fire-engine]` flags in [Options](#options) apply, plus `--proxy` and `--impersonate`.

Needs the `fire-engine` extra: `uv sync --extra fire-engine` (or `pip install
'dograpper[fire-engine]'`), which installs `curl_cffi` plus the `br` / `zstd`
decoders of the `httrack` extra: curl hands the body over as it came, and the
profile decodes it with the `httrack` decoder, under the same size and zstd
window limits. `--timeout` is the time to connect, then the longest silence
while receiving, as under `httrack`, but measured by libcurl's low-speed check,
which counts bytes in one-second records: a silence shorter than `--timeout`
never aborts the transfer, a server that sends nothing is given up one to two
seconds after `--timeout` (rounded up to whole seconds), and a silence after
data has arrived can run up to about nine seconds longer, since libcurl
averages the rate over its last few records. Without the extra, the
profile fails loud with an install hint; the release binary does not bundle
this extra, so `fire-engine` needs a source install. `--headless` is rejected
(the profile has its own transport), and a result that looks client-rendered
exits 1 pointing at `--downloader wget --headless`, since the profile runs no
JavaScript. `--proxy`, or an `--impersonate` other than the default, is a
usage error (exit 2) under any other downloader. If the site still challenges the request after the
browser fingerprint, the run exits 1 and suggests `--proxy` with a different
IP or `--downloader wget`; a manual-login browser solver is planned
([ADR-0011](https://github.com/lorenzoervedosa/dograpper/blob/main/docs/adr/0011-fire-engine-downloader.md)). Automatic challenge or
CAPTCHA solving is a non-goal. robots.txt, the pacing flags and the update
mode ("Updates" above) apply exactly as under `httrack`.

On the wire, the browser profile sends its own identity headers
(`User-Agent`, `Accept`, `Accept-Language`, `Accept-Encoding`, `Sec-Fetch-*`,
client hints) in its own order; of the `httrack` header set only the
request-specific ones are sent: `Referer` and, on an update, `If-None-Match` /
`If-Modified-Since`. A `--user-agent` you give (on the command line or in
config) replaces the profile's `User-Agent`; the rest of the identity stays the
profile's. How this should match Firecrawl exactly is open in
[#136](https://github.com/lorenzoervedosa/dograpper/issues/136).

## Incremental

A `.dograpper-manifest.json` manifest is generated after each download,
recording mirrored files with MD5 content hashes and mtimes. Future re-runs
use this manifest + `wget --timestamping` to fetch only files that
changed on the server; under `--downloader httrack` or `fire-engine` they revalidate each
file with the validators the manifest recorded (see "Updates" under
[Downloader profiles](#downloader-profiles)). For the files it saves, the
httrack and fire-engine profiles also record the response's `status`, `content_type`, `etag`
and `last_modified` (the `Date` when the server sent no `Last-Modified`), and
`redirected` when the requested URL reached the file through a redirect, and
`payload_md5`, the MD5 of the body as received (before its links were
rewritten), which `--changes` compares; the other downloaders leave these
`null`. A file a run did not touch keeps what
an earlier run recorded.

The manifest lives in the output directory: a relative `--manifest`
resolves against `-o`, an absolute one is used as is, so a re-run from any
directory finds it and two mirrors never share one. It never lists itself,
`delta_manifest.json`, `pack_state.json` or `hts-changes.json`. `pack` reads it the same way,
relative to `INPUT_DIR` (its [`--manifest`](pack.md#--manifest) row says how a subdirectory of a
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
built from it are meant to be shared. When several httrack seeds (or crawled
links) reach one file, the one that needed no redirect wins, else the
smallest URL.
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
(httrack, Playwright under the profile included) in the file name.

## Examples

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

## Options

```{dograpper-options} download
```

## Options in detail

### `--headless`

Skip wget (or the `httrack` engine's fetch) and use playwright directly

### `--manifest`

Manifest file for incremental downloads. A relative path resolves against `-o` (so the default lives in the output directory); an absolute path is used as is

### `--filter`

URL rule, repeatable: `+pattern` accepts, `-pattern` refuses, the last match wins (see [URL filters](#url-filters---filter))

### `--downloader`

Download backend: `wget`, `httrack` or `fire-engine` (see [Downloader profiles](#downloader-profiles))

### `--proxy`

One proxy URL for every request (`http://user:pass@host:port`); its credentials go to curl apart from the URL, so no error or report line shows them

### `--max-conn-rate`

Max connections opened per second (clamped to 5)

### `--max-bandwidth`

Max bytes/second (clamped to 10000000)

### `--max-retry-after`

Max seconds honored from `Retry-After` / `Crawl-delay` (hard cap 3600)

### `--no-extended-parsing`

Do not follow quoted strings that look like links (HTTrack `-%P0`, or `-j8`)
