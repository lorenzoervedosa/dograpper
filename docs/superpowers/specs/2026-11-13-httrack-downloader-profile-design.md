# Design: `httrack` downloader profile

Date: 2026-11-13. Status: approved by the user on 2026-11-13.
Evidence base: [`docs/discovery/httrack-mirroring-requirements.md`](../../discovery/httrack-mirroring-requirements.md)
(requirement IDs `DL-xx` and HTTrack citations come from there).

## 1. Intent

Users of `dograpper download` should be able to pick between two downloader
profiles:

- **`wget`** (default): today's behavior, unchanged byte for byte. This covers
  the cascade, the wget flags, the spoofed Chrome/120 UA and the manifest.
- **`httrack`**: a pure-Python reimplementation of how HTTrack mirrors a site.
  It identifies itself honestly, obeys robots.txt, is polite by default
  (bounded connections, rate and bandwidth), retries only transient failures,
  honors `Retry-After`, applies scope and filters, names files without
  collisions and revalidates cheaply on updates.

**Why:** the user mirrored a Cloudflare-protected docs site with WinHTTrack
(site B in the discovery note). HTTrack fetched it with an honest UA where a spoofed
Chrome UA was challenged. The user wants dograpper to have that capability
natively, as an automated and non-aggressive download. They do not want to
lose the wget path, which works well on the sites it already serves.

## 2. Goals, non-goals, anti-goals

**Goals**

- `--downloader [wget|httrack]` on `download` and `sync` (pass-through), plus a
  `downloader` key in `.dograpper.json`. Precedence stays defaults < JSON <
  explicit CLI.
- Under `httrack`, every network path uses the profile's identity and policy:
  - layer 1 (llms.txt);
  - layer 2 (sitemap);
  - layer 3, a new Python engine that replaces *both* `wget -i` and
    `wget --mirror`;
  - layer 4 (Playwright).
- **Identical to HTTrack, on the wire and in behavior.** The user's words: "a
  implementação idêntica à do HTTrack, só que no dograpper". The only
  deviations are the ones listed in this document, each marked
  **deviation**.
- **The only deviations are where HTTrack spoils the corpus** (decided by the
  user, option "1"):
  - Error and challenge bodies are never stored as content. HTTrack's `-o`
    default stores them.
  - Bot challenges are detected and reported.
  - robots.txt `Crawl-delay` is honored. HTTrack ignores it.
  - The cascade keeps working: llms.txt/sitemap discovery and the SPA fallback
    to Playwright.
- HTTrack's session and header features:
  - `--browser-headers`: on by default, as HTTrack `-%Q` is. With
    `--no-browser-headers` to turn it off.
  - `--cookies FILE` (Netscape cookies.txt): opt-in, as in HTTrack.
  - `--browser-login`: opt-in. A headed Playwright window opens, the user
    logs in or passes a challenge, and the crawl reuses that session's
    cookies and UA.

**Non-goals**

- Changing anything in the `wget` profile, including its spoofed UA and the
  README claim about it. That is a separate decision.
- Offline-browsing fidelity beyond what `pack` needs: no footers, no index
  pages, no MHT/WARC, no asset mirroring. `--include-extensions` still decides
  what is kept.
- FTP, proxies, MPTCP, HTTP/2.
- Fixing the suspected manifest path-duplication bug (open question 7 in the
  discovery note). It gets its own issue.

**Anti-goals (a failure even if it works)**

- Automatic challenge or CAPTCHA solving, JavaScript challenge execution,
  impersonating a *browser's* TLS (JA3/JA4) or HTTP/2 fingerprint, proxy
  rotation. HTTrack has none of these either, so excluding them keeps the
  profile identical. HTTrack's *own* TLS configuration **is** reproduced; see
  §5.1.
- Any regression in the `wget` profile or in `pack` consuming either profile's
  output.
- A challenge page or error body ending up in the output directory, where
  `pack` would treat it as documentation.
- Leaking cookie values into logs, the manifest, the report or the output dir.

## 3. Constraints

- Python 3.10+. **Standard library only** for the engine (approach A, below).
  No new mandatory dependency.
- Playwright stays optional with a conditional import (CLAUDE.md rules 1 and 4).
  `--browser-login` requires the `headless` extra and a display, and fails
  loudly when either is missing.
- Encoding-tolerant reads (`errors="replace"`, rule 7).
- Config precedence through `ctx.get_parameter_source()` and
  `CLI_EXPLICIT_PARAMS` in `sync` (rule 6). `_DOWNLOAD_PASSTHROUGH` in
  `commands/sync.py` gains the new keys.
- **Output compatibility:** the `httrack` profile writes the same layout `pack`
  and the manifest already consume from wget:
  - `<output>/<host>/<path>`;
  - an `.html` extension added to HTML responses (wget `--adjust-extension`);
  - `index.html` for directory URLs;
  - links rewritten relative between saved pages (wget `--convert-links`,
    HTTrack `-K0`). `link_extractor`/`--cross-refs` depend on this.
- Observable changes need README and CHANGELOG `[Unreleased]` entries in the
  same PR, and `tests/fixtures/help_baseline.txt` is regenerated only if the
  top-level help changes. It should not change.

## 4. Approaches (chosen: A)

| | Approach | Trade-off | Verdict |
|---|---|---|---|
| **A** | Standard library: `http.client` (persistent HTTP/1.1 per host), `concurrent.futures` workers, `html.parser`, `http.cookiejar.MozillaCookieJar`, and a small robots matcher of our own. `urllib.robotparser` uses first-match, while HTTrack and RFC 9309 use longest-match with Allow winning ties. | Most code to write; full control to reproduce HTTrack exactly; zero new deps; matches `llms_txt_parser`/`sitemap_parser`, which already use `urllib`. | **Chosen** by the user. |
| B | `httpx` as a mandatory dependency. | Less plumbing (pooling, cookies, redirects), but a new dependency to save work stdlib already covers. Its main extra, HTTP/2, is irrelevant: HTTrack speaks HTTP/1.1 only. | Rejected. |
| C | Scrapy. | Heavy; the Twisted reactor fights a synchronous CLI; behavior is dictated by Scrapy defaults, not HTTrack's. | Rejected. |

## 5. Behavior of the `httrack` profile

Defaults mirror HTTrack 3.51 unless the line says **deviation**.

### 5.1 Identity

- **Default UA:** `Mozilla/5.0 (compatible; dograpper/<version>)`. This is
  HTTrack's shape **without the project URL** (user decision). It keeps the
  `Mozilla/5.0 ` prefix that HTTrack's header logic keys on.
- Configurable with `--user-agent` (DL-01).
- Default headers, as HTTrack sends them, in HTTrack's order:
  - `Accept: text/html,image/png,image/jpeg,image/pjpeg,image/x-xbitmap,image/svg+xml,image/gif;q=0.9,*/*;q=0.1`;
  - `Accept-Language: en, *`;
  - `Connection: keep-alive`;
  - `Referer` (never https→http).
  - `Sec-Fetch-Site/Mode/User/Dest` and `Upgrade-Insecure-Requests` on
    navigations, over HTTPS, exactly when HTTrack's `fetch_meta_sent` would
    send them (`src/htslib.c:873-884`, `1240-1297`). This includes the
    default UA.
- **`Accept-Encoding: gzip, deflate, identity;q=0.9`.** This is what an
  HTTrack build without brotli/zstd sends. The stdlib cannot decode `br`, and
  `zstd` only arrives in Python 3.14, so advertising them would be a lie. The
  Windows WinHTTrack build probably advertises both (unverified on the wire).
- **TLS:** the same configuration as HTTrack (`src/htslib.c:5120-5144`,
  `src/htsback.c:3445-3453`):
  - OpenSSL's `DEFAULT` cipher list, set with `SSLContext.set_ciphers`. Not
    Python's own cipher string.
  - TLS 1.2 minimum, `OP_ALL`, SNI.
  - **No ALPN.** HTTP/1.1 only.
- **Certificate verification stays ON (deviation, security).** HTTrack does not
  verify certificates unless `--check-cert` is given, and that flag is
  unsupported on Windows (`src/htscoremain.c:2376-2395`, `src/htslib.c:5451`).
  Verification happens after the ClientHello, so it does not change what the
  server sees.
- **Residual difference that code cannot close: the OpenSSL version.** Python
  uses the OpenSSL it was built with: 3.0.13 for this machine's Python 3.12.3.
  WinHTTrack 3.51 ships OpenSSL 3.6.5 (`history.txt`). OpenSSL 3.5 and later
  changed the default key-share groups, so the two ClientHellos can differ even
  with identical settings. The PR 0 spike (§8.0) measures this.

### 5.2 robots.txt (DL-02, DL-04, DL-20)

- Fetched once per host before that host's first content request, and applied
  to every layer, including seeded URL lists and Playwright navigations.
- **Group selection:** a `dograpper` UA token (case-insensitive prefix) beats
  `*`, and consecutive `User-agent:` lines form one group.
- **Matching:** longest pattern wins and Allow wins ties.
- **Missing or broken robots.txt:** a 404 means no rules. HTTrack's 500 KiB
  rule cap and 1024-byte line cap apply.
- `Sitemap:` lines feed layer 2 *before* the fixed candidate paths.
- **`Crawl-delay` is honored (deviation):** it becomes the per-host minimum
  delay, combined with `--delay` as the max of the two.
- `--no-robots` (HTTrack `-s0`) opts out explicitly.
- Meta robots `nofollow` stops link extraction from that page (DL-03).

### 5.3 Politeness (DL-05)

- **Defaults:** 4 connections (`--connections`), 5 new connections/s, 100,000
  bytes/s total bandwidth, 120 s timeout, 2 retries, 100,000 links maximum.
- **Clamps:** connections ≤ 8, new connections/s ≤ 5, bandwidth ≤ 10 MB/s.
  Each clamp logs a warning. `--disable-security-limits` lifts them.
- **Delay:** `--delay` (existing flag, ms) is the minimum gap between requests
  to the same host.
- **Every tunable is a flag** (*call*: HTTrack exposes them all as flags, and
  an unreachable clamp is useless). The flags are `--connections`,
  `--max-conn-rate`, `--max-bandwidth` (bytes/s), `--timeout`, `--retries`,
  `--max-links`, `--max-retry-after` and `--disable-security-limits`. Each has
  a matching `.dograpper.json` key.
- **`sync` forwards every `download` flag of the profile**, including
  `--browser-login`, through `_DOWNLOAD_PASSTHROUGH` (*call*: matches how
  `sync` already forwards everything).

### 5.4 Status handling (DL-06, DL-07, DL-08, DL-09, DL-10)

- **Redirects:** 301/302/303/307/308 are followed. The target passes the same
  scope, filter and robots checks as any link, and the fragment is stripped.
- **Retried within the retry budget, no exponential backoff:**
  - timeout, connection error and TLS error;
  - 408, 409, 429, 500, 502, 504;
  - 503 only when it carries `Retry-After`.
  - 401, 403, 404 and 410 are never retried.
- **`Retry-After`** (seconds or HTTP-date) pauses the **whole queue**. It is
  capped by `--max-retry-after` (default 60 s, maximum 3600 s).
- **Non-2xx bodies are never written (deviation from `-o`).** On an update, a
  failed refetch keeps the previous good copy.
- **Challenge detection (deviation):**
  - a response is classed as a challenge when it carries a `cf-mitigated`
    header, or when it is a 200 whose body has `<title>Just a moment...</title>`
    or `/cdn-cgi/challenge-platform/`;
  - challenge responses are never stored, are counted, and are listed in the
    report.
- `/cdn-cgi/` paths are excluded from discovery.
- **No automatic browser fallback on a challenge** (*call*, from the anti-goal
  on challenge execution; HTTrack runs no JavaScript).
  - Under `httrack`, a challenged start URL, or challenged seeds when layers 1
    and 2 won, stops the run with exit 1.
  - The error message points to `--browser-login`.
  - The cascade's SPA / too-shallow fallback to Playwright is **not**
    triggered by a challenge. It is triggered only by the existing SPA
    heuristics on real 2xx content.

### 5.5 Discovery, scope, filters (DL-13, DL-14, DL-15, DL-16, DL-17)

- **Links:** extracted from:
  - HTML link attributes, per HTTrack's table: `href`, `src`, `srcset`,
    `data-src`, `poster` and the rest;
  - `<base href>`;
  - `<meta http-equiv=refresh>`.
  - `action` is never followed.
- **JS/CSS scanning is on, as in HTTrack** (`-j`, `-%P`, CSS `url()` /
  `@import`).
  - It is a static scan; nothing is executed.
  - The URLs it finds go through scope, filters and `--include-extensions`
    like any other link, so assets are still dropped.
- **Scope** (*call*, settling the competing definitions in the code today):
  - **Host:** same host only.
  - **Down-only:** the recursive crawl uses the *directory* of the start URL,
    as HTTrack `-D` and wget `--no-parent` do:
    - `/docs/index.html` → `/docs/`;
    - `/modding` → `/`;
    - `/modding/` → `/modding/`.
    - Seeded lists from layers 1 and 2 keep going through `url_filter`
      unchanged, because that code is shared with the `wget` profile.
  - **Depth:** `--depth` counts link hops from the start URL, which is hop 0.
    This is the same meaning as wget `--level` and the Playwright crawler.
    0 means unlimited.
  - **Start-URL redirect:** do exactly what HTTrack does. The builder confirms
    this in `src/htsmirror.c:190-215` and `283-320`.
    - A redirect to another host stops the run.
    - Same host, when HTTrack would reject the target and the mirror would
      come out empty: re-base the scope on the final URL instead. This is a
      **deviation** under the user's option "1", because an empty corpus
      spoils it.
  - Scope is applied identically to discovered links, redirect targets and
    Playwright links.
- **Filters:** `--filter` is repeatable and uses HTTrack syntax, evaluated in
  order with the last match winning:
  - required: `+pattern` and `-pattern` with `*`, `*[file]`, `*[path]`,
    `*[param]`, `*[a-z]`, `*[]`;
  - optional (builder may defer to a later PR): `*[<NN]`/`*[>NN]` size rules
    and `-mime:`.
- **URL normalization** (HTTrack `-%u`): drop the fragment, collapse `//`,
  sort query keys.
- **Run limits:** a link cap (default 100,000). When it is reached, the run
  ends with a "partial" status in the report.

### 5.6 Storage and incremental runs (DL-11, DL-12, DL-13)

- **Layout:** as in §3.
- **Naming:** a query string adds 4 hex digits of its MD5 to the filename
  (`page.html?x=1` → `page4B54.html`). Collisions get a `-2`, `-3` suffix.
- **Manifest:** written from the engine's own per-URL records (real URL, final
  URL, status, content-type, ETag, Last-Modified), not derived from disk
  paths. `ManifestEntry` gains the missing fields in a backward-compatible
  way: old manifests still load.
- **Updates:** revalidate with `If-None-Match` / `If-Modified-Since`. A 304
  keeps the file.
- **No purge (deviation from HTTrack `-X`, user decision):** local files no
  longer reachable are listed in the report, not deleted.

### 5.7 Opt-in session features (DL-19 and HTTrack §2.10)

- **`--cookies FILE`:**
  - loads a Netscape cookies.txt, including `#HttpOnly_` lines, and sends
    matching cookies;
  - at the end of the run the jar is written back to the same file, as
    HTTrack `-%K` does;
  - cookie values are never logged.
- **`--browser-headers` / `--no-browser-headers`** (HTTrack `-%Q`, on by
  default). With the default UA it amounts to the `Sec-Fetch-*` behavior of
  §5.1. When `--user-agent` names Chrome/Edge ≥ 108 or Firefox, the profile
  also sends what that browser sends, ported from HTTrack's tables:
  - per-kind `Accept`;
  - `Accept-Language: en-US,en;q=0.9`;
  - client hints with Chromium's GREASE brand list, for Chrome/Edge;
  - the recorded header order.
- **`--browser-login`:**
  1. Opens headed Chromium on the start URL.
  2. The user logs in or passes the challenge, then presses Enter in the
     terminal.
  3. dograpper takes `context.cookies()` and the page's real
     `navigator.userAgent`, and uses both for the crawl.
  4. With `--cookies FILE`, the jar is also saved there for reuse.
- **Fail loud:**
  - any `httrack`-only flag (`--user-agent`, `--no-robots`, `--filter`,
    `--cookies`, `--browser-headers`, `--browser-login` and every tunable in
    §5.3) combined with `--downloader wget` is a usage error (exit 2, click's
    convention);
  - `--browser-login` without Playwright or without a display exits 1 with the
    fix in the message.

### 5.8 Report and exit codes (DL-18)

- **End-of-run summary:** besides today's lines, it adds:
  - counts by status class;
  - challenged, robots-blocked, retried, out-of-scope and unreachable-local
    URLs;
  - the first N errors with their referrer, and the full list with `-v`.
- **Exit codes:** they follow HTTrack's "front error" rule.
  - If the start URL itself (or every seed, when layers 1 and 2 won) fails or
    is challenged, the run exits 1 under the existing "download / crawl"
    failure row.
  - Otherwise it exits 0, even with per-page errors, which the report shows.

## 6. Code layout (proposal; the plan may refine)

| File | Change |
|---|---|
| `src/dograpper/lib/httrack/` (package) | New engine. Each module is small and stdlib-only: `robots.py`, `policy.py` (UA, headers, limits, clamps), `fetcher.py` (connections, retries, Retry-After gate, bandwidth), `links.py`, `scope.py` (scope + HTTrack filters), `naming.py`, `crawl.py` (seeded list + recursive crawl, `CrawlResult`-compatible return), `challenge.py`, `cookies.py`. |
| `src/dograpper/commands/download.py` | `--downloader` and profile-only flags. The cascade picks the layer-3 engine per profile and passes the profile policy to layers 1, 2 and 4. |
| `src/dograpper/commands/sync.py` | New keys in `_DOWNLOAD_PASSTHROUGH` and options. |
| `src/dograpper/lib/llms_txt_parser.py`, `sitemap_parser.py` | Accept an optional policy (UA, robots, `Sitemap:` hints). When it is absent, behavior is exactly today's. |
| `src/dograpper/lib/playwright_crawl.py` | Optional policy: UA, robots check, skip non-2xx, challenge check, query-hash naming. When it is absent, behavior is today's. |
| `src/dograpper/lib/manifest.py` | Backward-compatible new fields, and build from engine records. |
| `README.md`, `CHANGELOG.md`, `.dograpper.json.example`, `CLAUDE.md` (tree + test table) | Docs for every observable change. |
| `tests/test_httrack_*.py` | Unit tests per module, plus cascade tests against a local `http.server` fixture. No external network. |

## 7. Delivery

Five PRs, in order. Each PR is shippable alone and carries its own tests,
README and CHANGELOG.

1. **Profile switch + fetch core.**
   - `--downloader`;
   - identity and headers;
   - robots, including `Crawl-delay` and `Sitemap:`;
   - politeness and clamps;
   - retry and `Retry-After`;
   - the status, non-2xx and challenge policy;
   - seeded-list fetch, which replaces `wget -i` under the profile;
   - layers 1 and 2 under the policy;
   - the report.
2. **Recursive crawl.** Links, scope, filters, normalization, naming, link
   rewriting, meta nofollow and `/cdn-cgi/` exclusion. This replaces
   `wget --mirror` under the profile.
3. **Incremental.** Manifest records and conditional revalidation, with the
   previous copy kept on failure.
4. **Playwright under the profile.**
   - Navigations go through `page.route` + `route.fetch()`.
   - A response carrying `cf-mitigated` or challenge markup is aborted
     *before* it renders, so no challenge script runs (*call*, same reason as
     §5.4).
5. **Opt-in session features.** `--cookies`, `--browser-headers` and
   `--browser-login`.

**Before PRs 2 and 4 land** (*call*, no silent fallback): when
`--downloader httrack` needs a path that does not exist yet (recursive crawl,
or Playwright under the profile), it fails loudly with exit 1 and names the
missing piece. It never falls back to wget or to Playwright without the
policy. Release timing between PRs is the user's call; CHANGELOG entries
accumulate under `[Unreleased]`.

## 8. Open decisions (owner: user)

0. **Done criterion and a premise check before PR 1.** Two things are unproven:
   - That the honest UA is why HTTrack got through Cloudflare. In the one real
     run it did not prevent challenges.
   - That a stdlib `ssl` handshake will be treated like HTTrack's OpenSSL one.
     The anti-goals forbid TLS impersonation, so the engine cannot be adjusted
     to match.

   Proposed "PR 0" spike, in two parts:
   - **(a) Offline, measures "identical":** a local TLS/HTTP server logs the
     raw ClientHello and request headers. The user's installed `httrack.exe`
     and a stdlib prototype configured per §5.1 both hit it, and the two
     captures are diffed. No external site is involved.
   - **(b) Online, run by the user** (site A blocks AI agents by name): the four curl
     variants from the discovery note plus the stdlib prototype, against
     site B.

   Done = (a) differs only where §5.1 documents it, and (b) gets 200 where
   HTTrack did. If (b) fails, the README promises nothing about Cloudflare.

   **Status: decided.** The spike runs first. (Earlier the user asked why
   matching HTTrack's TLS was "out of scope". That was a wording error, now
   fixed in §5.1 and §2.)
1. **Default UA content:** decided. No project URL (§5.1).
2. **Purge:** decided. Report only (§5.6).

## 9. Left to the builder

- Thread vs. per-host worker model inside the 4-connection budget.
- How the bandwidth throttle is implemented (token bucket or similar).
- Size and MIME filter rules timing (PR 2 or later).
- Exact report formatting, within §5.8.
