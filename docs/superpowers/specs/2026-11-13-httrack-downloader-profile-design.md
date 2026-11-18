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
- Challenge or CAPTCHA solving, JavaScript challenge execution, impersonating
  a *browser's* TLS (JA3/JA4) or HTTP/2 fingerprint, and proxy rotation, **in
  this profile**: HTTrack has none of them, and the profile stays identical
  to HTTrack. HTTrack's *own* TLS configuration **is** reproduced; see §5.1.
  They are not excluded from dograpper: another downloader may add them
  (`docs/DECISIONS.md`, 2026-11-18).

**Anti-goals (a failure even if it works)**

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
  - `Referer` (never https→http), built as HTTrack builds it
    (`src/htslib.c:1136-1163`): no userinfo, no fragment, host, path and query
    escaped like the request target. One that does not parse is dropped.
  - `Sec-Fetch-Site/Mode/User/Dest` and `Upgrade-Insecure-Requests` on
    navigations, over HTTPS, exactly when HTTrack's `fetch_meta_sent` would
    send them (`src/htslib.c:873-884`, `1240-1297`). This includes the
    default UA.
- **`Accept-Encoding`: advertise only what this build can decode** (user
  decision; HTTrack does the same per build, `src/htscodec.c:114-122`).
  - Base: `gzip, deflate, identity;q=0.9`.
  - `br` is inserted when `brotli` is importable.
  - `zstd` is inserted when `zstandard`, or Python 3.14's `compression.zstd`,
    is importable.
  - With both: `gzip, deflate, br, zstd, identity;q=0.9`, which is exactly
    what WinHTTrack 3.51 sent (PR 0 capture).
  - The decoders come from a new optional extra:
    `httrack = ["brotli", "zstandard"]`. It is optional because both packages
    ship C extensions.
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
- **OpenSSL ≥ 3.5 is required for an identical handshake.** Python uses the
  OpenSSL it was built with. PR 0 measured it (§8.0).
  - **OpenSSL 3.5.3** (uv-managed CPython 3.13.7): the ClientHello matches
    WinHTTrack 3.51 (OpenSSL 3.6.5) in cipher suites, extension order, groups,
    key shares and signature algorithms. It differs only in:
    - `ec_point_formats` (`[0,1,2]` vs `[0]`, probably an OpenSSL 3.6
      change);
    - HTTrack putting an explicit port in SNI, which is not reproduced and
      only matters for non-default ports.
  - **OpenSSL 3.0.13** (system CPython 3.12.3): very different. There is no
    `X25519MLKEM768`, and the sigalgs and extension order differ.
  - It is also **decisive in practice:** site B answered 200 to the 3.5.3
    prototype and 403 `cf-mitigated: challenge` to the identical request from
    3.0.13.
  - Decision (user):
    - the profile logs a prominent warning when
      `ssl.OPENSSL_VERSION_INFO < (3, 5)`;
    - the README documents the requirement;
    - the release binary is built on a uv-managed Python (python-build-standalone
      links OpenSSL 3.5+), with a CI assertion on the version.
    - The project's dev Python is not changed.

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
    header, or when it is a 200 whose `<title>` is `Just a moment...`;
  - **never** match on `/cdn-cgi/challenge-platform/` in the body. Cloudflare
    injects its `jsd/main.js` beacon into real pages: PR 0's 200 response
    from site B (title "Overview") contained it, and the HTTrack run's 1900
    `main.js?ray=…` requests came from real pages. That rule would flag every
    page;
  - challenge responses are never stored, are counted, and are listed in the
    report.
- `/cdn-cgi/` paths are excluded from discovery.
- **No automatic browser fallback on a challenge** (*call*: HTTrack runs no
  JavaScript, and this profile executes no challenge; see §2).
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
  - They are rewritten like any other link (§5.6, "Link rewriting").
  - Turned off as in HTTrack, with `[httrack]` flags (usage errors under
    `wget`, like §5.7's): `--no-parse-scripts` is `-j4`, which also stops CSS
    `url()` / `@import` (one scanner in HTTrack); `--no-extended-parsing` is
    `-%P0`, the same effect as `-j8`. `-j`'s other bits only switch HTTrack's
    external parser modules, which 3.51 no longer ships (#122).
  - Contexts (tags, attribute values, `<script>` / `<style>` bodies) are the
    ones PR 2's HTML5 tokenizer reads; inside each, HTTrack's byte rules
    apply. The two differ only on markup HTTrack's byte parser reads apart,
    such as a `>` inside a quoted event handler.
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
  - Shipped by #96 for **both** profiles (`lib/url_filter.py`), ahead of PR 2.
    Under `wget` the rules also scope `wget --mirror` as
    `--accept-regex`/`--reject-regex`; a rule order those cannot express is a
    usage error. PR 2's recursive crawl should reuse the same `UrlFilters`.
  - **Deviation:** a rule never widens the host scope above (HTTrack's
    `+other.host/*` crosses hosts).
- **URL normalization** (HTTrack `-%u`): drop the fragment, collapse `//`,
  sort query keys.
- **Run limits:** a link cap (default 100,000). When it is reached, the run
  ends with a "partial" status in the report.

### 5.6 Storage and incremental runs (DL-11, DL-12, DL-13)

- **Layout:** as in §3. An IPv6 literal host keeps its brackets and its colons
  become `_`, as in HTTrack (`src/htsname.c:1436`, `1579-1600`; `[` and `]` are
  legal on NTFS, APFS and ext4). A non-default port is appended as for any
  host: `http://[::1]:8080/a` → `[__1]:8080/a.html`.
- **Naming:** a query string adds 4 hex digits of its MD5 to the filename
  (`page.html?x=1` → `page4B54.html`). Collisions get a `-2`, `-3` suffix.
  Names are compared case-insensitively, as HTTrack's save-name hash does
  (`src/htshash.c:65-78`, `strcasecmp`), so `/Page` and `/page` never share
  a file on NTFS or default APFS. **Deviation:** the fold is Unicode
  (`str.casefold`), not ASCII-only, so `/Été` and `/été` collide too; both
  filesystems fold them, and an overwrite spoils the corpus.
- **HTML extension:** an HTML response replaces any extension HTTrack knows
  (its MIME table, a dynamic or an HTML-family type: `notes.txt` →
  `notes.html`) and is appended to an unknown one (`article-1.884291` →
  `article-1.884291.html`), as `src/htsname.c:1200-1215` does.
  **Deviation (shortcut):** HTTrack keeps a contested extension when the body's
  magic bytes prove it (`src/htsname.c:289-321`, `src/htssniff.c`): a real PDF
  at `/doc.pdf` served as `text/html` stays `doc.pdf`. dograpper does not sniff
  and names it `doc.html`.
- **Manifest:** written from the engine's own per-file records, not derived
  from disk paths: the URL requested, the status, `Content-Type`, `ETag` and
  `Last-Modified` of the response the file was saved from, and whether that URL
  reached the file through a redirect. ETag and Last-Modified are kept as HTTrack
  keeps them: under 64 characters, with the response's `Date` standing for a
  missing `Last-Modified` (`src/htslib.c:1632-1653`). `ManifestEntry` gains
  `status`, `content_type` and `redirected` in a backward-compatible way: old
  manifests still load.
- **Link rewriting (`-K0`, #133):** once every name is known, every saved page,
  stylesheet and script is written again with each link HTTrack records
  rewritten: the link attributes, and the links the script scans and `-%P`
  take (§5.5), under the same switches. HTTrack writes the buffer it parsed
  for every hypertext file (`src/htsparse.c:1223`, `3807-3852`), with each
  link in its place (`2400-2406`, `3379-3502`).
  - A link to a saved file becomes its relative path; any other relative link
    becomes its absolute URL; `<base href>` is emptied; no other byte changes.
  - A link the scans took is written exactly as HTTrack writes it: the path
    through `escape_uri_utf` (lower-case `%xx`, `src/htslib.c:4613-4618`),
    `(` and `)` as `%28`/`%29` in a CSS `url()` (`src/htsparse.c:851-870`),
    then the link's query (`includequery`, `3475-3480`); an absolute URL with
    `" ' < >` percent-encoded (`1000-1033`); `&` as `&amp;` in a tag, never in
    `<script>`/`<style>` text or a saved file (`977-988`, `history.txt:151`).
    A script's links are written from the page that loaded it, a module
    specifier's from the script (`src/htscore.h:276-283`).
  - **Deviation:** a link attribute keeps PR 2's form: only `%` and `#` of a
    saved name are escaped and the query is dropped, where HTTrack escapes the
    path with `escape_uri_utf` and appends the query (`src/htsparse.c:3389`,
    `3475-3480`). `pack --cross-refs` (`utils/link_extractor.py`) resolves an
    `<a href>` as a path, neither percent-decoding it nor cutting a query, so
    HTTrack's form would leave those links unresolved. `pack` never reads a
    scanned link, which keeps HTTrack's form.
  - **Deviation:** a link to a file the run did not save (an error, a type
    `--include-extensions` leaves out) is made absolute, where HTTrack writes
    the name it planned for it before the fetch; a local link to a missing
    file browses nowhere. For the same reason, a script loaded by a page that
    has no saved file gets absolute links (a module specifier still relative).
  - **Deviation:** an absolute link is left as written, where HTTrack writes
    back its own normalized form (`sink_add_absolute_url`).
  - **Deviation:** the final URL of a redirect is not recorded, where HTTrack's
    cache keeps every hop. It can carry a secret, and the manifest is meant to
    be shared (README "Incremental"); `redirected` says a chain was taken.
- **Updates (HTTrack `-C2`).** A run whose `-o` already holds a manifest is an
  update, as HTTrack switches to `-C2` on a folder with a finished mirror
  (`src/htscoremain.c:1283-1285`; dograpper saves the manifest only at the end
  of a run). Each file recorded from a 200 with a validator, still on disk and
  not empty, is revalidated (`src/htsback.c:2557-2607`, `2414-2492`). A record
  whose file is not named as its URL would be (an edited manifest) is ignored,
  so the manifest never chooses where a page is written.
  - the request starts with `If-None-Match` then `If-Modified-Since`, or the
    one whose validator exists, right after the request line; every other
    header, `Accept-Encoding` included, is unchanged (`src/htslib.c:1113-1115`);
  - **304:** the file stays byte-identical and keeps its record; a page's
    links are followed from it (`src/htsback.c:4437-4494`);
  - **any other answer but a 2xx or a redirect** (4xx, 5xx, a challenge): the
    file is kept the same way, the URL is listed as kept after an error, and
    the answer is not retried (`src/htsback.c:4266-4280`, masked as a 304
    before `htsmirror.c`'s retry switch); a kept start URL is no front error;
  - **a failed transfer** (timeout, connection, decoding): retried, reported as
    an error, and the file and its record are kept, its links not followed
    (`src/htsback.c:1307-1321`, `src/htscache.c:200-232`);
  - **a 2xx** replaces the file and its record;
  - a file erased or emptied since, or one whose record has no validator, is
    fetched in full.
  - **Deviations**, each because dograpper keeps no cache beside the mirror
    (HTTrack's `hts-cache/`) or to protect the corpus:
    - A `Retry-After` on a revalidation still holds the whole queue
      (politeness). HTTrack masks the answer as a 304 first and never sets
      its gate (`src/htsmirror.c:536-540`).
    - A challenged start URL still ends the run with exit 1 (§5.4), its copy
      kept and the crawl stopped there. HTTrack masks the challenge's 403 like
      any error and goes on.
    - The target of a redirect is not recorded, so the validators of a file
      reached through one go to the hop whose file name is that file's (the
      redirecting URL itself is sent plain, as in HTTrack). HTTrack finds the
      target by the URL its cache recorded; a redirect that now leads to
      another URL is fetched in full by both.
    - A kept page's links are read back from the saved copy, whose links to
      saved files `-K0` made relative: each is mapped back to the URL the
      previous manifest recorded for that file, any other link read as
      written. HTTrack parses the original page from its cache. A file whose URL the manifest withholds (a query
      off the allowlist) is therefore not reached from a kept page, and is
      never revalidated. A kept stylesheet or script is read back the same
      way, a script against the page that loads it in this run: when that is
      not the page that loaded it last time, its rewritten links do not map
      back and are read as written. A kept file is not relinked either, where
      HTTrack writes it again from its cache.
    - A file an update may keep keeps its name: no other URL takes it, and
      it is never moved. HTTrack computes names again and renames a file
      whose name changed (`src/htsback.c:2425-2456`); moving one would break
      the links of the kept pages.
    - robots.txt is fetched in full on every run. HTTrack caches and
      revalidates it too (`src/htsback.c:2396-2400`).
- **Cache modes** (`--cache N`, HTTrack `-C`, `src/htsalias.c:194-195`; #132).
  The default is HTTrack's: `2` when `-o` holds a manifest, else `1`
  (`src/htscoremain.c:1263-1285`).
  - `--cache 2` (HTTrack `--update`, `src/htsalias.c:271`) is the update above.
  - `--cache 1` (HTTrack `--continue`, `src/htsalias.c:272`): a file recorded
    from a 2xx, still on disk at its recorded size, is loaded without a
    request, and a kept page's links are followed from it ("File immediately
    loaded from cache", `src/htsback.c:2497-2556`). A file whose size changed
    is requested in full, with no validator (`src/htscache.c:729-806`,
    `src/htsback.c:2549-2554`).
  - `--cache 0`: the manifest's records are neither read nor written, as
    HTTrack touches no cache then (`src/htscache.c:59`, `1174`). Each file is
    fetched in full and keeps the record the previous run made for its URL; no
    file is listed as not reached (no `new.lst`, `src/htscore.c:2147`).
  - **Deviations**, because dograpper keeps no cache beside the mirror: under
    `--cache 1` the redirecting URL of a file reached through a redirect is
    still requested (HTTrack loads the cached 3xx too), and a hypertext file
    whose size changed is fetched in full, where HTTrack writes it again from
    the body its cache holds (`src/htscache.c:264-272`).
- **Update hacks** (`--updatehack`, HTTrack `-%s`, off as in HTTrack,
  `src/htslib.c:5429`; #132). At the headers of a 200 for a recorded file whose
  type is no hypertext (`src/htslib.h:884-905`), the copy on disk and its
  record are kept, as a forced 304, the body unread and the connection dropped
  (`src/htsback.c:4281-4357`, `back_keep_existing`): on a revalidation when
  `Content-Length` is both the recorded size and the size on disk; without
  validators when it is the size on disk. A recorded 200 with no validator is
  therefore part of the update (sent plain, its name kept). HTTrack's third
  hack, for `Range` resumes, has nothing to apply to: the profile sends no
  `Range`.
- **Do not recatch** (`--do-not-recatch`, HTTrack `-%n`, off as in HTTrack,
  `src/htslib.c:5427`; #132). A recorded 2xx file whose type is no hypertext,
  missing or empty since, is not requested: a missing one is created empty,
  and the URL is an error at its link, "null-size file not recaught"
  (`src/htsback.c:2466-2480`, `2653-2694`; `src/htsmirror.c:476-482`). It is
  kept with its record, so the next run without the option fetches it again.
  A hypertext file never reaches this branch in HTTrack (its body is in the
  cache) and is fetched in full.
  - **Deviation (protects the corpus):** under `--cache 1`, HTTrack `-%n`
    empties a file whose size changed before requesting it in full
    (`src/htscache.c:796-814`); the profile requests it without emptying it,
    so a failed request leaves the copy as it was.
- **File times:** each saved file gets its recorded `Last-Modified` (else the
  `Date`) as access and modification time, once its links are rewritten, read
  as HTTrack reads the date (`src/htscore.c:451-452`, `src/htsback.c:2119-2128`,
  `src/htsdate.c:53-157`). `pack --delta` lets content hashes decide when both
  pack states carry them, so a file rewritten with the same size and time is
  still a change (#132).
- **No purge (deviation from HTTrack `-X`, user decision):** local files no
  longer reachable are listed in the report ("Not reached this run, kept on
  disk"), not deleted.

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
  - any `httrack`-only flag (`--user-agent`, `--no-robots`, `--cookies`,
    `--browser-headers`, `--browser-login` and every tunable in §5.3) combined
    with `--downloader wget` is a usage error (exit 2, click's convention).
    `--filter` left this list with #96, which made it shared;
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

## Known gaps (temporary)

These are not deviations. Each is an HTTrack behavior the profile does not have
yet and will get; none is approved as a difference from HTTrack.

- **HTTrack's change report** is not ported yet (#132):
  - `-%d` `--changes` (off, `src/htslib.c:5441`) writes `hts-changes.json`
    (discovery note §2.9, "Cache modes and update options");
  - Pending a follow-up PR under #78. Evidence: discovery note §2.9.

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
   - **Status: implemented (wave 5).** Behavior and deviations in §5.6; the
     opt-in cache options left are under "Known gaps".
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
     This profile does not impersonate a browser's TLS (§2), so the engine
     cannot be adjusted to match.

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

   **Status: done (2026-11-13).**
   - (a) Headers match except UA (by design) and `Accept-Encoding` (fixed by
     the extra). The TLS result is in §5.1.
   - (b) Site B, one request per variant, 3 s apart:
     - curl gets `403 cf-mitigated: challenge` with the HTTrack UA, the
       Chrome/120 UA, the default UA, and Chrome/120 + `--http1.1` alike;
     - the stdlib prototype on OpenSSL 3.5.3 gets `200` with both the
       dograpper and HTTrack UAs;
     - the same prototype on OpenSSL 3.0.13 gets `403 challenge`.
   - **Verdict:** the UA is irrelevant here, and the TLS handshake decides.
     This refutes the discovery note's UA hypothesis.
   - Site A was not tested by the agent (it blocks Claude by name); the user
     may run `run_online.sh` against it.
   - (Earlier the user asked why matching HTTrack's TLS was "out of scope".
     That was a wording error, fixed in §5.1 and §2.)
1. **Default UA content:** decided. No project URL (§5.1).
2. **Purge:** decided. Report only (§5.6).

## 9. Left to the builder

- Thread vs. per-host worker model inside the 4-connection budget.
- How the bandwidth throttle is implemented (token bucket or similar).
- Size and MIME filter rules timing (PR 2 or later).
- Exact report formatting, within §5.8.
