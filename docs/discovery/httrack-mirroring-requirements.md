# HTTrack mirroring behavior and download requirements for dograpper

Discovery note, 2026-11-13. Scope: how HTTrack mirrors a site, what of that
dograpper's `download` should adopt, and what it should not.

## 1. Summary

- HTTrack 3.51-0 identifies itself by default as `Mozilla/5.0 (compatible; HTTrack/3.x; +https://www.httrack.com/)`. It obeys robots.txt (`-s2`) and throttles itself to 4 connections, 5 new connections/s and about 100 KB/s. Hard caps of 8 connections, 5/s and 10 MB/s apply unless you pass `-%!`.
- **Is the UA/Cloudflare hypothesis right? Unresolved.**
  - **Confirmed:** HTTrack sends an honest UA (the code, plus the `-F` in the local run's `doit.log`).
  - **Not confirmable from these sources:** that Cloudflare challenged the curl request because a Chrome UA did not match a non-Chrome fingerprint. None of the sources describes how Cloudflare decides, and no HTTrack project for site A (§2.0) was found on disk. The curl and HTTrack requests also differ in more than the UA: header set, HTTP version, TLS stack and target zone.
- **The honest UA did not prevent challenges.** The only HTTrack run found on disk targets site B, a Javadoc site behind Cloudflare, and was crawled with the default UA. It got 3842×200, plus 5×403 with `cf-mitigated` and 1900×302 on `/cdn-cgi/challenge-platform/…`.
- **Challenge pages were saved as content.** HTTrack wrote the 5 challenge bodies (`<title>Just a moment...</title>`) at the real page filenames. This is because it keeps server error pages by default (`-o`), and it logs only one "Bot protection challenge" warning per crawl.
- **No deep anti-bot evasion.** HTTrack does no TLS or HTTP/2 impersonation, runs no JavaScript and solves no challenges. It does have opt-in browser-header mimicry (`-%Q`, effective when `-F` names a browser) and a browser-login cookie+UA transplant. Both are flagged in §2.10 and excluded from the requirements.
- **Biggest dograpper gaps:** a spoofed Chrome/120 UA on every layer, no robots.txt handling, no challenge detection or status-aware retry, Playwright saves any response body, and there is no real per-URL fetch ledger.

**Update, 2026-11-13 (PR 0 spike).** The UA hypothesis below is **refuted** for
site B. curl was challenged with every UA, HTTrack's included. A stdlib request
that reproduces HTTrack's headers got 200 on OpenSSL 3.5.3 and a 403 challenge
on OpenSSL 3.0.13. The TLS handshake decides. Details are in
`docs/superpowers/specs/2026-11-13-httrack-downloader-profile-design.md` §5.1
and §8.0. DL-09's body marker `/cdn-cgi/challenge-platform/` is wrong: real
pages carry Cloudflare's injected `jsd` beacon. Use only `cf-mitigated` and the
`Just a moment...` title.

## 2. HTTrack behavior by area

### 2.0 Sources and citation conventions

- **Engine source:** `https://github.com/xroche/httrack` at commit
  `06ada4a69745577e87a0f2526c12bb1ea2c55580` (shallow clone, 2026-11-13). A
  path such as `src/htslib.c:5383` is relative to that repository at that SHA.
  Permalink form: `https://github.com/xroche/httrack/blob/06ada4a69745577e87a0f2526c12bb1ea2c55580/<path>#L<line>`.
- **The installed build is not that commit.** The installed WinHTTrack 3.51-0 declares engine commit
  `b0972289468f41652f88708300d6fa0e33472b3f`
  (`C:\Program Files\WinHTTrack\source.txt`). That commit was not fetched,
  because network access was limited to the one clone. The two share the same
  `history.txt` (identical apart from CRLF line endings, with 3.51-0 at the
  top). HEAD's docs differ from the installed ones in `httrack.man.html`,
  `cmdguide.html`, `faq.html` and `login.html`; for example, HEAD adds
  `-@c/--check-cert` and rewords the `-C` default. A claim that rests only on
  code describes HEAD. Corroboration from the installed docs or the local run is
  noted inline.
- **Installed docs:** `C:\Program Files\WinHTTrack\html\*.html`, cited as
  `WinHTTrack html/<file> §<section>`.
- **Local run:** one WinHTTrack 3.51-0 project was found at
  a project folder under the user profile (start URL: **site B**, a Javadoc
  site behind Cloudflare). It was read without modification, as a
  snapshot taken at 2026-11-13 22:43 -03 while the crawl was still running
  (`hts-in_progress.lock` present). It is cited as `run: <file>`.
  - No project was found for **site A**, the MediaWiki behind Cloudflare
    that first triggered this note; its robots.txt denies AI agents by name.
    The searches covered the user profile and `hts-log.txt` files on the
    local drives.
- **GNU Wget 1.21.4's local `wget(1)` man page** is cited only for defaults
  that dograpper inherits.
- **`WhttBrowserLogin.dll`** was inspected with `strings`, never executed. Its
  source lives in `xroche/httrack-windows`
  (`c4d01391e909c0c73e24fcfb742813eb5eb6ae0d`), which was not cloned.

### 2.1 Identity and request headers

- **Default User-Agent:** `Mozilla/5.0 (compatible; HTTrack/3.x; +https://www.httrack.com/)`.
  - It is defined in `src/htsglobal.h:291-294`; `HTTRACK_AFF_VERSION` is `"3.x"` (`src/htsglobal.h:49`). The source comment calls it an honest crawler UA with no fake OS or browser.
  - It is set by default in `src/htslib.c:5396-5397`, and a self-test asserts it is honest (`src/htsheader_selftest.c:647-659`).
  - The installed build confirms it: `run: hts-cache/doit.log` passes exactly this `-F`, and `run: hts-cache/winprofile.ini` has `UserID=` set to the same string.
- **Configuring the UA:** `-F/--user-agent` (`src/htscoremain.c:2630-2634`); `-F ""` sends no UA at all (WinHTTrack `html/cmdguide.html` §7). A `User-Agent:` line given through `-%X/--headers` replaces the engine's own line (`src/htslib.c:1249-1253`).
- **Protocol:** HTTP/1.1 requests (`src/htslib.c:1096-1101`); `-%h` forces HTTP/1.0. There is no HTTP/2 or ALPN code. The only `--http2` string in `src/` is a list of curl flags that the login-bundle parser recognizes (`src/htsbundle.c:1274`).
- **TLS:** stock OpenSSL with `TLS_client_method`, TLS 1.2 minimum, `SSL_OP_ALL` and SNI. It does not customize ciphers, extensions or ALPN (`src/htslib.c:5120-5144`, `src/htsback.c:3445-3453`). The Windows build ships OpenSSL 3 (`libssl-3-x64.dll`; `history.txt` 3.51-0 says "OpenSSL 3.6.5").
- **Headers built by `http_sendhead`** (`src/htslib.c:979-1420`):
  - `Referer`: the linking page. It is never sent from https to http (`src/htslib.c:1137-1172`).
  - `Connection: keep-alive`, unless `-%k0` or HTTP/1.0 is used (`src/htslib.c:1185-1191`).
  - `Host` (`src/htslib.c:1196-1202`).
  - `From`: only with `-%E`.
  - `Accept`: by default `text/html,image/png,image/jpeg,image/pjpeg,image/x-xbitmap,image/svg+xml,image/gif;q=0.9,*/*;q=0.1` (`src/htsfetch.h:127-130`, `src/htslib.c:5464`). It changes per link kind only with `-%a KIND=` or a browser table (`src/htsfetch.c:629-648`).
  - `Accept-Language`: `en, *` by default (`src/htsfetch.h:134`, `src/htslib.c:5463`). WinHTTrack passed `pt_BR, en, *` (`run: hts-cache/doit.log`).
  - `Accept-Encoding` (`src/htscodec.c:114-122`, `src/htslib.c:1311-1321`):
    - over TLS: `gzip, deflate[, br][, zstd], identity;q=0.9`, depending on build;
    - over cleartext: `gzip, deflate, identity;q=0.9`;
    - on Range resumes and updates: `identity`.
    - The Windows install ships `brotlidec.dll` and `zstd.dll`, so it presumably advertises `br` and `zstd`. This is inferred, not observed on the wire.
  - `Sec-Fetch-Site/Mode/User/Dest`, plus `Upgrade-Insecure-Requests` on navigations. These are sent only when all of the following hold (`fetch_meta_sent`, `src/htslib.c:873-884`; emission at `src/htslib.c:1240-1297`):
    - `-%Q` is not off (default `HTS_DEFAULT`, `src/htslib.c:5450`);
    - the URL is https or loopback;
    - the UA starts with `Mozilla/5.0 `;
    - the link kind can be classified.
    - The default UA also starts with `Mozilla/5.0 `, so by code reading the default profile sends `Sec-Fetch-*` over HTTPS. This was not verified on the wire (§4, open question 4).
  - Client hints (`sec-ch-ua*`): sent only when the UA parses as Chrome/Edge ≥108 (`src/htslib.c:728-811`, `1214-1235`), so never with the default UA.
  - `Authorization: Basic` from `user:pass@` in the URL (`src/htslib.c:1364-1393`).
  - `Cookie`: last (`src/htslib.c:1401-1414`).

### 2.2 robots.txt

- **Default mode `-s2`:** "always" obey (`src/htslib.c:5414`; enum in `src/htsopt.h:352-355`; man page `-sN`).
  - `-s0` ignores robots.txt.
  - `-s1` lets an explicit `+` filter override a disallow (`src/htswizard.c:153-170`).
  - `-s3` also obeys strict rules.
  - Per the docs, a 403 is "a server refusal, not a robots rule" (WinHTTrack `html/cmdguide.html` §3).
- **Group selection:** a `User-agent:` value starting with `httrack`, `winhttrack` or `webhttrack` (case-insensitive) takes precedence. Otherwise the `*` group applies, and consecutive `User-agent:` lines form one group, as in RFC 9309 §2.2.1 (`src/htsrobots.c:231-255`).
- **Matching:**
  - The longest pattern wins, and `Allow` wins ties (`src/htsrobots.c:132-166`).
  - `Disallow: /` is honored. `IGNORE_RESTRICTIVE_ROBOTS` is not defined anywhere in `src/` or `configure.ac`, so `keep_root` is always true (`src/htscore.c:1928-1934`).
  - Rules are capped at 500 KiB and lines at 1024 bytes. A truncated `Allow` is dropped, a truncated `Disallow` is kept, and a warning is logged (`src/htsrobots.h:50-53`, `src/htsrobots.c:262-293`).
- **Missing robots.txt:** a 404 is logged at debug level as "No robots.txt rules" (`src/htsmirror.c:483-487`). Observed: the first request of the run was `/robots.txt` → 404 (`run: hts-cache/new.txt`, line 2).
- **`Sitemap:` lines** are collected whatever the group (`src/htsrobots.c:220-230`) and feed the opt-in `-%m`.
- **`Crawl-delay`: not supported.** The string does not occur in `src/`, `html/` or `man/` at HEAD.
- **Meta robots:** while robots handling is on, `<meta name="robots" content="…nofollow…">` stops link extraction from that page (`src/htsparse.c:2045-2068`). `noindex` has no handling.

### 2.3 Politeness and flow control

- **Defaults:**
  - `-c4` connections (`src/htslib.c:5383`);
  - `-%c5` new connections per second (`src/htslib.c:5490`);
  - `-A` 100000 bytes/s (`src/htslib.c:5489`), divided across sockets (`src/htsback.c:3301-3302`). The docs say "about 100 KB/s even without this flag" (WinHTTrack `html/cmdguide.html` §4).
  - `-T120` second timeout (`src/htslib.c:5392`);
  - `-R2` retries (`src/htslib.c:5408`);
  - `-H0`: hosts are never abandoned (`src/htslib.c:5407`);
  - 100000 links maximum (`src/htslib.c:5484`);
  - random pause `-%G` of 0 (`src/htslib.c:5457-5458`).
- **Security clamps** (`src/htscoremain.c:2955-2978`; WinHTTrack `html/cmdguide.html` §4 "The security clamps"; man page `-%!`). Unless `-%!/--disable-security-limits` is given:
  - `-c` is clamped to ≤8;
  - `-A` to ≤10,000,000 B/s;
  - `-%c` to ≤5/s;
  - each clamp logs a warning.
- **Scheduler gates** in `back_pluggable_sockets_strict` (`src/htscore.c:3283-3327`), applied in this order:
  1. the Retry-After gate;
  2. the connections-per-second limiter;
  3. the randomized inter-file pause (`-%G MIN[:MAX]`).
- **Host control:** `-H1/2/3` bans a host after timeouts or slow transfers once its retries are exhausted (`src/htsmirror.c:398-425`). `-J` sets a minimum transfer rate, and `-E`, `-M` and `-G` set time and size limits (man page "Limits options", "Flow control").
- **Abuse guidance:** `abuse.html` is advice only: limit connections, bandwidth, size and time; do not disable robots.txt lightly; ask the webmaster before large mirrors (WinHTTrack `html/abuse.html` "Advice & what not to do"). The enforcement mechanisms are the clamps above.
- **Backoff:** the only adaptive backoff is Retry-After (§2.4). There is no exponential backoff between retries.

### 2.4 HTTP status handling

- **Redirects:** `HTTP_IS_REDIRECT` covers 301, 302, 303, 307 and 308 (`src/htslib.h:814-820`).
  - Each redirect is logged as a warning and the `#fragment` is removed from the `Location` (`src/htsmirror.c:144-160`).
  - The target goes through the same acceptance check as any link (`hts_acceptlink`, `src/htsmirror.c:191-215`).
  - An HTML page that moved to a different URL is saved as a stub with a meta refresh to the target, which the parser then follows (`src/htsmirror.c:283-320`).
  - If the start URL redirects to another host, the crawl stops under the default same-host scope (WinHTTrack `html/cmdguide.html` §2).
- **Retried, within the `-R` budget** (`src/htsmirror.c:398-450`):
  - timeouts, slow transfers, connection errors, non-fatal errors and TLS handshake errors;
  - 408, 409, 500, 502, 504 and 429;
  - 503 only when it carries Retry-After.
  - Everything else is not retried, including 401, 403, 404 and 410.
- **Retry-After:**
  - Both RFC 9110 forms are parsed (`src/htslib.c:1806-1809`, `2952-2954`).
  - It is obeyed up to `--max-retry-after`: 60 s by default, 3600 s maximum (`src/htsglobal.h:295-297`; man page `-%J`).
  - It acts as a global gate that holds every queued link, not just the one that failed (`src/htsmirror.c:536-540`, `src/htscore.c:3262-3294`).
- **Other statuses:**
  - 203 is treated as 200, and a 100 Continue response is skipped (`src/htsback.c:4224-4240`).
  - 406 is treated as 200 so that links inside the choice page are scanned (`src/htsback.c:4262-4264`).
  - 412 and 416 on a resume re-fetch the whole file once (`src/htsmirror.c:326-390`).
- **Error bodies are saved by default.** `-o` defaults to on (`src/htslib.c:5409`; man page "-o *save the server's error pages (404..)").
  - For a link that is not a start URL, the error body is kept and stored (`store_errpage`, `src/htsmirror.c:494-499`, `579-585`) and is not parsed for links (`src/htscore.c:1648`, `1849`).
  - A failed start URL is not stored and counts as a "front" error. This prevents an update from wiping a mirror whose site vanished (`src/htsmirror.c:491-516`).
- **Update safety:** if a revalidation fails, the existing file is kept and the status is masked as 304 (`src/htsback.c:4266-4280`).
- **Cloudflare challenges.** When an error response carries the `cf-mitigated` header:
  - HTTrack logs one warning per crawl, naming the URL and advising to pass a browser's cookies and exact UA (`src/htsback.c:4199-4216`). The once-per-crawl latch is `bot_challenge_noted`, `src/htscore.h:178`.
  - The response is not handled in any other way: it continues through the normal error path above.
- **Observed in the run** (snapshot): `hts-cache/new.txt` counted 3842×200, 1900×302, 5×403 and 2×404.
  - All 1900×302 were `GET /cdn-cgi/challenge-platform/scripts/jsd/main.js?ray=…`. They were logged as errors and no files were saved.
  - `hts-log.txt` holds one "Bot protection challenge" warning and five `"Forbidden" (403)` lines.
  - All 5 challenged URLs are on disk under their real names, each carrying `<title>Just a moment...</title>`. None of the other 1901 saved `.html` files carries that title.
- **Answer: did HTTrack save challenge pages as content?** Yes. Two things determine it:
  - the `-o` default (`errpage`) together with the `store_errpage` path;
  - the fact that the challenge arrived with an error status.
  - A challenge served with a 200 status would be saved and parsed like any page; nothing in the source detects one.
- **Logging:**
  - `hts-log.txt` records each error with its referrer ("(from …)", `src/htsmirror.c:462-482`).
  - `hts-cache/new.txt` holds one line per URL with time, size, flags, status, message, MIME, ETag/Date, URL, local file and referrer (column header at `run: hts-cache/new.txt`, line 1).

### 2.5 Cookies, authentication, browser login

- **Cookies:**
  - Accepted by default (`-b1`, `src/htslib.c:5419`); `Set-Cookie` is parsed at `src/htslib.c:1832`.
  - Every matching stored cookie is sent (`src/htslib.c:1401-1414`; `history.txt` 3.51-0 fixed a limit of 8 cookies).
  - Cookie scope uses the built-in Public Suffix List (`history.txt` 3.51-0).
- **cookies.txt:**
  - A Netscape `cookies.txt` in the project folder or the working directory is loaded automatically (`src/htscore.c:955-962`; WinHTTrack `html/faq.html` "I can not access several pages").
  - `-%K/--cookies-file` names a cookie jar and rewrites it at the end of the crawl, keeping a `.bak` copy.
  - It also reads `#HttpOnly_` lines and pasted `document.cookie` strings (`history.txt` 3.51-0; man page `-%K`).
- **Authentication:**
  - HTTP Basic only, from `user:pass@` in the URL. Digest is not supported (WinHTTrack `html/cmdguide.html` §7; `src/htslib.c:1364-1393`).
  - `-b0` disables both cookies and Basic-credential reuse.
- **Login bundles:**
  - `<URL>#httrack-bundle=<name>` loads `<name>.hts` (UA, headers, cookies, scope) from the project folder (man page; `src/htsbundle.h:45-66`).
  - The bundle's headers go only to hosts within the registrable domains of its URLs (man page).
- **`WhttBrowserLogin.dll`** (Windows only):
  - Its strings show an embedded Microsoft Edge WebView2 (`ICoreWebView2Environment/Controller`, `startBrowser`, `LoginWindow`) that collects cookies through the WebView2 `GetCookies` API (`beginHarvest`).
  - The UI strings say: "Log in to the site in a browser, and crawl with the cookies and the browser identity it was given" and "Cookies collected: %d" (`C:\Program Files\WinHTTrack\lang\English.txt:1099-1115`).
  - `history.txt` 3.51-0: "WinHTTrack and the Android app have a browser login too. The cookies and headers are saved as a login bundle".
  - Not verified, since the source was not read: that it also captures the WebView's UA. "Browser identity" in the UI suggests it does.
- **What the docs say about logins and challenges:**
  - HTTrack "cannot fill in a login form and cannot solve a CAPTCHA". For a "checking your browser" page, the advice is to pass a browser's cookies and exact UA (WinHTTrack `html/login.html` "When to use this method").
  - The same page warns that Cloudflare ties its clearance cookie to the browser and "can refuse HTTrack even with the right cookies and User-Agent" (WinHTTrack `html/login.html` "Limits").
  - These features are flagged in §2.10.

### 2.6 Link discovery

- **HTML attributes:**
  - `href`, with `<base href>` recognized (`src/htsparse.c:1898-1903`).
  - An attribute table (`src/htsparse.c:191-232`) covers:
    - link attributes: `src`, `srcset`, `data-src`, `data-srcset`, `background`, `data`, `poster`, `lowsrc`, `dynsrc`, `usemap`, `longdesc`, `xlink:href`, `archive`, `profile`, `url`, `swurl`;
    - `<meta http-equiv=refresh content=…>`;
    - `onXxx` event handlers and `style`, when scripts are parsed.
  - `action` is deliberately left alone, so forms are never submitted.
  - Attributes that never hold links are skipped (`src/htsparse.c:160-167`), and so are framework bindings such as `:x`, `@x`, `v-`, `x-bind:` (`src/htsparse.c:172-187`).
- **Extended parsing:** `-%P`, on by default (`parseall`, `src/htslib.c:5425`), scans unknown tags and script text for URL-shaped strings (`src/htsparse.c:2160-2276`).
- **JavaScript:**
  - `-j` is on by default (`src/htslib.c:5406`). It is a static scan of strings, `import` specifiers and `import()` (`history.txt` 3.50-4).
  - Nothing is executed. The docs: "It does not run JavaScript … There is no flag that fixes this" (WinHTTrack `html/cmdguide.html` §6).
- **CSS:** `url()`, `@import`, and `image-url()`-style functions are handled (`src/htsparse.c:455-632`). Since 3.51-0, every font and image a stylesheet names is mirrored (`history.txt`).
- **Query strings** are part of the URL and kept by default (`includequery`, `src/htslib.c:5417`).
- **Sitemap seeding** is opt-in (`-%m`/`--sitemap-url`):
  - Sources are robots.txt `Sitemap:` lines, then `/sitemap.xml`; nested `sitemapindex` files and `.gz` are followed.
  - The URLs found still pass scope and filters.
  - A declared or named sitemap is fetched even when robots.txt disallows its path (WinHTTrack `html/cmdguide.html` §2).
  - `-%L` adds start URLs from a file.

### 2.7 Scope control

- **Defaults:**
  - stay on the same host (`-a`, `src/htslib.c:5372`);
  - only go down into subdirectories (`-D`, `src/htslib.c:5375`);
  - depth 9999 (`src/htslib.c:5373`), with the start page counted as level 1 (WinHTTrack `html/cmdguide.html` §2);
  - external depth 0 (`src/htslib.c:5374`).
- **Travel options:**
  - host scope: `-a/-d/-l/-e` (same address, same principal domain, same TLD, everywhere);
  - directory scope: `-D/-U/-S/-B`;
  - `-n` fetches non-HTML files near a followed page, `-%e` sets external depth, `-%C` declares host aliases, and `-t` tests out-of-scope links with HEAD (man page; WinHTTrack `html/cmdguide.html` §2).
- **Filters** (WinHTTrack `html/filters.html` §1.a, §1.b, §2):
  - Syntax is `+pattern` and `-pattern`; filters are evaluated in order and the later rule wins.
  - Wildcards: `*`, `*[file]`, `*[path]`, `*[param]`, `*[a-z]`, and `*[]` as an end anchor.
  - Size rules: `*[<NN]`, `*[>NN]`, in KB.
  - MIME rules: `-mime:type/*`, checked only after a link has been scheduled.
  - `--why`/`-%Y` explains which rule decided (man page).
- **Limits:**
  - `-m` sets per-file size limits for HTML and non-HTML; `-M` caps total bytes, `-E` wall time, `-#L` links.
  - Type probing: `-u`, and delayed type checking `-%N` (default `%N2`) (man page).

### 2.8 Local storage and link rewriting

- **Layout:** `-N0` original structure, template `%h%p/%n%q.%t` (`src/htslib.c:5401`; `run: hts-cache/winprofile.ini` `BuildString`). The file extension follows the MIME type unless `-%t` is given (man page).
- **Query strings:** the first 4 hex digits of the query string's MD5 are added to the file name. The man page example: `foo.cgi?q=45` → `foo4B54.html` (`src/htsname.c:1964-2011`). Observed in the run: `main.js?ray=…` → `main418a.js`, `mainca6a.js`, …
- **Name collisions** get `-2`, `-3`, … (`_` in ISO9660 mode) (`src/htsname.c:490-548`, `1902-1910`).
- **Link rewriting:** `-K0` by default rewrites links relative so the copy browses offline (`src/htslib.c:5376`); `-K`, `-K3`, `-K4` and `-K5` are variants (man page). HTML pages also get a footer comment (`src/htsglobal.h:288-290`; man page `-%F`).
- **Dedup by URL** (man page):
  - `-%u` url hacks are on by default (`src/htslib.c:5430`): collapse `//`, treat `www.foo.com` as `foo.com`, ignore query-key order. Each part can be disabled.
  - `-%g` strips query keys; `-%C` aliases hostnames.
  - There is no content-hash dedup in the fetch path.

### 2.9 Cache, incremental update, resume

- **Cache format:** `hts-cache/new.zip` holds one ZIP entry per URL, errors included. Its metadata carries `X-StatusCode`, `Content-Type`, `Last-Modified`, `Etag`, `Location` and `X-Save` (WinHTTrack `html/cache.html`). `new.txt` is a human-readable ledger, and `doit.log` stores the command line so a later run can replay it (`run: hts-cache/readme.txt`, `doit.log`).
- **Update mode:**
  - For each cached 200, HTTrack sends `If-None-Match` plus `If-Modified-Since` (or whichever validator exists) and disables compression (`src/htsback.c:2556-2601`).
  - `--update` revalidates every page; `--continue` trusts the cache (WinHTTrack `html/cmdguide.html` §9).
  - The installed man page gives `-C1` ("cache is prioritary") as the default. HEAD rewords it as C1, or C2 when a finished mirror is in the folder.
- **Resume:** a partial file is resumed with `Range: bytes=N-` plus `If-Match` / `If-Unmodified-Since` (`src/htsback.c:2610-2640`).
- **Purge:** `-X` is on by default (`src/htslib.c:5388`). An update deletes local files that are no longer part of the mirror, which the docs call "the purge trap" (WinHTTrack `html/cmdguide.html` §9).
- **Update hacks:** `-%s` keeps a file whose size is unchanged (`src/htsback.c:4283-4380`). If a refetch fails during an update, the good copy is kept (§2.4).

### 2.10 Anti-bot-related features (reported and flagged; not dograpper requirements)

- **F1: browser-header mimicry (`-%Q/--browser-headers`).** On by default, with full effect once `-F` names a browser:
  - Chrome/Edge client hints, with brand lists built by Chromium's GREASE algorithm (`src/htslib.c:728-811`);
  - the browser's own `Accept` tables per link kind (`src/htsfetch.c:629-648`) and `Accept-Language: en-US,en;q=0.9` (`src/htsfetch.h:135`);
  - `Origin` on CORS requests;
  - the header order recorded from Chrome 155 and Firefox 158 (`src/htslib.c:913-966`, `1214-1340`).
  - The docs justify it as sending what a browser sends, because "a wrong value can get it refused" (WinHTTrack `html/cmdguide.html` §7). **This is header-level fingerprint impersonation.**
- **F2: UA-spoof recipe.** The docs include "Get past a crawler-UA block" with a browser `--user-agent` (WinHTTrack `html/cmdguide.html` §11), and the FAQ suggests changing the UA when HTTrack is filtered (WinHTTrack `html/faq.html`).
- **F3: clearance transplant.**
  - The `cf-mitigated` log message and `login.html` advise solving the challenge in a browser and passing its cookies and exact UA (`src/htsback.c:4207-4215`; WinHTTrack `html/login.html` "Limits").
  - `WhttBrowserLogin.dll` automates collecting those cookies and that identity (§2.5).
- **Absent:**
  - TLS (JA3/JA4) or HTTP/2 fingerprint impersonation (stock OpenSSL, HTTP/1.1; §2.1);
  - JavaScript execution (§2.6);
  - CAPTCHA or challenge solving (WinHTTrack `html/login.html`);
  - proxy rotation (one `-P` proxy).
  - `-%G` (random pause between files) is politeness, not evasion.

## 3. Requirements for dograpper

"dograpper current status" values are Has / Partial / Missing / Unverified, with references into
this repository.

| ID | Requirement | Rationale | HTTrack evidence | dograpper status |
|---|---|---|---|---|
| DL-01 | **MUST** use a default User-Agent that honestly identifies dograpper (product token, version, project URL). It is configurable via a `--user-agent` flag and the config file. Every fetch path uses the same value: llms.txt, sitemap, robots, wget, Playwright. | Robots group matching (DL-02) needs a stable token. The README's stated benefit of the spoof is not supported by the only local evidence. Mixed identities across layers make failures impossible to reproduce. | `src/htsglobal.h:291-294`, `src/htslib.c:5396-5397`, `-F` | **Missing.** Chrome/120 UA in `src/dograpper/lib/wget_mirror.py:15-21,101,197`, `llms_txt_parser.py:32` and `sitemap_parser.py:35-40`. Playwright context sets no UA (`playwright_crawl.py:63-64`). README claims the spoof avoids WAF blocks (`README.md:264-265`). |
| DL-02 | **MUST** fetch `/robots.txt` once per host before the first content request. Pick the group naming dograpper's token (case-insensitive prefix), else `*`. Apply longest match, with Allow winning ties (RFC 9309). A 404 means no rules. Enforce it on every path, including seeded URL lists. Provide an explicit, documented opt-out. | Baseline crawler etiquette. The same check in every layer keeps seeded and crawled URLs consistent. | `src/htsrobots.c:132-166`, `231-255`; default `-s2` `src/htslib.c:5414`; 404 handling `src/htsmirror.c:483-487` | **Missing.** No `robots` reference in `src/dograpper/`. wget honors robots only in recursive mode (wget(1) DESCRIPTION). The `wget -i` (`wget_mirror.py:189-199`), urllib and Playwright paths have no check. |
| DL-03 | **SHOULD** not follow links from a page whose meta robots contains `nofollow`. | Same intent as DL-02 at page level. | `src/htsparse.c:2045-2068` | **Missing** in Playwright, which follows every `a[href]` (`playwright_crawl.py:137-150`). Unverified for wget. |
| DL-04 | **SHOULD** read `Sitemap:` lines from robots.txt as the first layer-2 source, before guessing paths. | Sites declare their sitemap there, which beats fixed-path guessing. | `src/htsrobots.c:220-230`; man page `-%m` | **Missing.** Only the fixed `CANDIDATE_PATHS` are tried (`sitemap_parser.py:31`). |
| DL-05 | **SHOULD** apply politeness defaults with hard ceilings: bounded concurrency per host, a non-zero default delay or request-rate cap, and ceilings that need an explicit unsafe flag to exceed. | Defaults decide behavior for most users, and HTTrack's clamps exist to stop accidental floods. | Defaults `src/htslib.c:5383`, `5489-5490`; clamps `src/htscoremain.c:2955-2978` | **Partial.** One wget process (`wget_mirror.py:129`) and one Playwright page at a time (`playwright_crawl.py:67-115`), but `--delay` defaults to 0 (`commands/download.py:252-253`), wget gets no `--wait` then (`wget_mirror.py:110-112`), and urllib fetchers never wait. |
| DL-06 | **MUST** retry by status: only transient outcomes (timeout, connection reset, 408, 429, 500, 502, 504, and 503 with Retry-After), with a small bound. Never retry 401, 403, 404 or 410. | Retrying refusals adds load and never succeeds. Not retrying 429 or 503 loses pages. | `src/htsmirror.c:398-450`; `-R2` `src/htslib.c:5408` | **Partial.** The whole wget run is retried on exit codes other than 0 and 8, with 2^n backoff (`wget_mirror.py:118-145`, `207-229`). Exit 8 (server errors) counts as success (`wget_mirror.py:135-138`, `221-224`). wget does not retry 429/503 by default (wget(1) `--retry-on-http-error`). urllib and Playwright never retry. |
| DL-07 | **MUST** honor `Retry-After` (seconds or HTTP-date) on 429/503 by pausing all queued requests, globally or per host. Cap the wait (HTTrack: 60 s default, 3600 s maximum) and log it. | This is the server's explicit backoff signal. A per-request wait alone still lets queued requests keep hitting the server. | `src/htslib.c:1806-1809`, `2952-2954`; `src/htscore.c:3262-3294`; `src/htsmirror.c:536-540`; `src/htsglobal.h:295-297` | **Missing.** |
| DL-08 | **MUST** never write a non-2xx response body into the corpus. On incremental runs, keep the previous good copy when a refetch fails. | Error and challenge bodies become "documentation" chunks downstream. HTTrack's `-o` default shows the failure mode: challenge pages were saved at real filenames. | `-o` default `src/htslib.c:5409`; `src/htsmirror.c:494-499`, `579-585`; keep-on-update `src/htsback.c:4266-4280`; run: 5 stored challenge pages | **Partial.** urllib layers drop non-200 (`llms_txt_parser.py:36-38`, `sitemap_parser.py:43-45`). The wget path relies on wget not saving error bodies by default (wget(1) `--content-on-error`, not passed). Playwright ignores the response status and saves `page.content()` for any status (`playwright_crawl.py:109-132`). |
| DL-09 | **MUST** detect bot-challenge responses and classify them apart from generic errors. Primary signal: the `cf-mitigated` response header. Secondary signal, for interstitials returned with 200: challenge markup such as `<title>Just a moment...</title>` or `/cdn-cgi/challenge-platform/` in the body. Count every occurrence, list the URLs in the end-of-run summary, never store them as content, and exit non-zero above a configurable share. Detection and reporting only. | The run shows a mirror that looks successful (3842×200) while containing challenge pages, and HTTrack's single warning hides how many there were. | `src/htsback.c:4199-4216` (header only, warned once via `src/htscore.h:178`); run: 5 challenged pages, 1 warning | **Missing.** No `challenge`, `cf-mitigated` or `Just a moment` in `src/` or `tests/`. |
| DL-10 | **SHOULD** exclude `/cdn-cgi/` paths from discovery by default. | Run: 1900 of 5749 recorded requests (33%) were `cdn-cgi/challenge-platform/.../main.js?ray=…` → 302, with no content. | HTTrack has no such default (run: `hts-cache/new.txt`) | **Unverified.** wget `--reject` lists `js` (`wget_mirror.py:30-37`), but whether it rejects `main.js?ray=…` is untested. Playwright only follows `a[href]` (`playwright_crawl.py:137-139`). |
| DL-11 | **SHOULD** write a per-URL fetch ledger with: requested URL, final URL after redirects, status, content-type, ETag, Last-Modified, local path, referrer, discovery layer, timestamp. | Needed for DL-08/09/12, audits and reproducible debugging. dograpper's manifest is its existing audit artifact. | `hts-cache/new.txt` columns (run); `new.zip` metadata (WinHTTrack `html/cache.html`) | **Partial.** `ManifestEntry` has `etag`/`last_modified` (`lib/manifest.py:16-28`), but `build_manifest` always writes `None` (`manifest.py:111-114`), derives `url` from the on-disk path (`manifest.py:98-105`) and records no status. |
| DL-12 | **SHOULD** revalidate conditionally on incremental runs (`If-None-Match` / `If-Modified-Since`, from the DL-11 ledger) on every fetch path. | Cheap updates without trusting a stale copy forever. | `src/htsback.c:2556-2601` | **Partial.** wget uses `--timestamping` (`wget_mirror.py:94`, `191`). Playwright skips any URL found in the manifest without revalidating (`playwright_crawl.py:81-100`). |
| DL-13 | **MUST** map URLs to files deterministically and without collisions: keep query-distinguished pages apart (e.g. a short hash of the query string) and add suffixes on collision. | Silent overwrites lose pages, which breaks the determinism dograpper promises. | `src/htsname.c:1964-2011` (query hash), `490-548` (collision suffix) | **Partial.** wget names its own files. Playwright builds the path from `urlparse().path` only, so `?page=1` and `?page=2` overwrite one file (`playwright_crawl.py:117-132`). |
| DL-14 | **SHOULD** normalize URLs before queueing: drop the fragment, collapse `//`, sort query keys, and strip configured tracking keys; folding `www.` is optional. | Fewer duplicate fetches and duplicate chunks. | `-%u` default on `src/htslib.c:5430`; `-%g`, `-%C` (man page) | **Partial.** Only fragments are stripped, in Playwright (`playwright_crawl.py:146-147`). `url_filter.py:34-80` does no normalization. |
| DL-15 | **SHOULD** enforce the same scope on every layer, including links found by Playwright and redirect targets. Default: same host, path prefix (down only) and depth. Add user include/exclude URL patterns where the last matching rule wins. | Today scope depends on which layer won. | Defaults `src/htslib.c:5372-5375`; redirect targets checked `src/htsmirror.c:190-215`; filters (WinHTTrack `html/filters.html` §1.a) | **Partial.** `url_filter.py:34-80` applies only to layer-1/2 lists (`commands/download.py:83`, `95`). wget gets `--no-parent` (`wget_mirror.py:99`). Playwright checks only the host (`playwright_crawl.py:141-150`). There are no user patterns. |
| DL-16 | **COULD** add MIME and size limits: per-file maximum, total maximum, and MIME accept/deny after headers arrive. | Extension filters miss extensionless URLs and dynamic pages. | `-m`, `-M`, `-mime:`, `*[<NN]` (WinHTTrack `html/filters.html` §1.b, §2) | **Partial.** Extension filters only (`wget_mirror.py:40-66`). Playwright uses extensions only for naming (`playwright_crawl.py:122-123`). |
| DL-17 | **COULD** add run limits (maximum pages, time, bytes) that end with a "partial" status in the summary. | Bounded runs on unknown sites. | `-#L` 100000 default `src/htslib.c:5484`; `-E`, `-M` (man page) | **Missing.** Only `--depth` exists (`commands/download.py:248-249`). |
| DL-18 | **SHOULD** print an end-of-run report: counts by status class plus challenged, robots-blocked, retried and out-of-scope URLs, and per-URL errors with their referrer. | Failures should be visible without re-running at debug level. | Error lines with "(from …)" `src/htsmirror.c:462-482`; run: `hts-log.txt` | **Partial.** Only downloaded/skipped/size are printed (`commands/download.py:304-310`). wget's stdout/stderr is captured but never surfaced (`wget_mirror.py:129-131`). |
| DL-19 | **COULD** import a Netscape `cookies.txt` (opt-in) for docs the user is entitled to read. Never log the file, never copy it into the output, and never document it as a way past bot challenges. | Private or internal docs behind a login. | `src/htscore.c:955-962`; man page `-%K` | **Missing.** |
| DL-20 | **COULD** honor robots.txt `Crawl-delay` for dograpper's group as a minimum per-host delay. | A cheap politeness signal. HTTrack is not the model here, because it ignores the directive. | Not supported (no occurrence in `src/`, `html/`, `man/`) | **Missing.** |

## 4. Out of scope, non-goals, open questions

### Non-goals

- **Header-level browser impersonation** (§2.10 F1): client hints, `Sec-Fetch-*` synthesized to look like a browser, browser `Accept` tables, browser header order. DL-01 deliberately goes the other way.
- **UA spoofing as a WAF workaround** (§2.10 F2). This includes the current README claim (`README.md:264-265`), which DL-01 replaces.
- **Clearance transplant:** embedded-browser cookie/UA harvesting, and documenting cookies.txt as a way past challenges (§2.10 F3). DL-19 is limited to sessions the user is entitled to.
- **Evasion HTTrack does not have either:** TLS or HTTP/2 fingerprint impersonation, challenge or CAPTCHA solving, proxy rotation.
- **Offline-browsing fidelity:** link-rewriting modes (`-K`), footers, index pages, MHT/WARC/single-file output, and asset mirroring. dograpper skips assets by design (`wget_mirror.py:28-37`) and its consumer is `pack`, not a browser.
- **FTP, proxy chains, MPTCP, bandwidth caps in bytes per second.** Politeness is expressed as request rate (DL-05).

### Open questions

1. **Where is the site A mirror?** The verdict rests on the site B run. If that mirror exists, check its `hts-log.txt` for "Bot protection challenge" and grep its HTML for `<title>Just a moment...</title>` to learn whether it actually contains content.
2. **Decisive experiment** for the hypothesis (needs network, one request each, run by the user). From the same WSL host, in the same minute, against site A and site B, record the status and `cf-mitigated` for curl with:
   - (a) HTTrack's default UA;
   - (b) the Chrome/120 UA;
   - (c) curl's default UA;
   - (d) the Chrome/120 UA plus `--http1.1`.

   How to read the results:
   - (a) passes and (b) fails on the same zone → supports "the UA claim is what's penalized".
   - (d) passes where (b) fails → points at protocol/fingerprint.
   - Everything fails → IP or zone policy, and the UA is irrelevant.
3. **Citations are at HEAD** (`06ada4a`), not at the installed engine (`b0972289`). Re-check the cited lines against `b0972289` (needs one more fetch, outside this task's network allowance).
4. **Default UA and `Sec-Fetch-*`:** code reading says the default UA sends `Sec-Fetch-*` over HTTPS (`src/htslib.c:873-884`). Confirm with `-%H` (debug headers) against a local server.
5. **wget behavior to confirm:**
   - Does `--reject=…js…` reject `main.js?ray=…`?
   - Does `wget -i … --page-requisites` consult robots.txt? wget(1) only promises that for recursive retrieval.
6. **Measure before changing the default UA (DL-01).** Compare success on a fixed list of docs sites with the current and the honest UA. Some sites may currently pass only because of the spoof; no evidence either way.
7. **Manifest URL for start URLs with a path.** `build_manifest` with a base URL that has a path appears to repeat it (`https://x/docs` + `/docs/a.html`; `lib/manifest.py:85-105`). The Playwright cache lookup compares that value with real URLs (`playwright_crawl.py:84-86`). Code reading only; tests cover only an empty base URL or a bare host (`tests/test_delta_manifest.py:18`, `tests/test_delta_artifacts.py:221`).
8. **Build or wrap?** Option: wrap the `httrack` CLI as an optional external layer, the way wget is wrapped (separate GPL-3 binary, process boundary), instead of reimplementing DL-02/06/07/13 in Python. This needs a decision, including a license review.
