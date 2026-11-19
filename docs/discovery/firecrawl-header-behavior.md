# Firecrawl's handling of custom headers and User-Agent, and what dograpper's fire-engine should copy

Discovery note, 2026-11-19, for #136 (deliverable 1 only). Scope: request headers,
`User-Agent`, and what is coupled to them: client hints, header order, cookies sent
as a header, the `mobile` flag, and robots.txt matching. The implementation is a
separate PR. The maintainer picked the target behavior on 2026-11-19 (§6): Option
B, with a repeatable `--header`.

## 0. Sources and method

| Source | Pin |
|---|---|
| `github.com/firecrawl/firecrawl` | `24002c681a9b827b953ac6c4a4729c6ea9783648` (2026-11-18, `chore(python-sdk): release 4.58.0 (#5835)`), the commit the issue names. Every `path:line` without a repo prefix is at this commit. |
| `github.com/firecrawl/firecrawl-docs` (source of docs.firecrawl.dev) | `11d54c95a75c` (2026-11-19 head). Cited as `docs:path:line` plus the published page. The page URLs come from the repo's `docs.json` navigation and were not fetched. |
| Firecrawl's dependencies, at the versions its lockfiles pin | `undici` 7.30.1 (`apps/api/pnpm-lock.yaml:4639`), `robots-parser` 3.0.1 (`apps/api/pnpm-lock.yaml:4228`), source read at their git tags. `user-agents` `^1.1.669` and `playwright` `^1.65.0` (`apps/playwright-service-ts/package.json:22,24`). |
| curl_cffi | 0.17.0 in this repository's `.venv`; libcurl `8.23.0-IMPERSONATE`, BoringSSL. `chrome` resolves to `chrome152` and `chrome_android` to `chrome131_android`. Both are native curl-impersonate targets. |

Classification of every finding:

- **[code]**: verified in code, with `path:line`.
- **[docs]**: stated in the docs, with a link.
- **[observed]**: a local observation (see below).
- **[unknown]**: behind the closed fire-engine service.

Local observations ran against an echo server on `127.0.0.1` that records each
request's header lines in wire order. It speaks plain HTTP/1.1, so header names
keep their case and the order is the HTTP/1.1 order. Nothing was sent to a third
party.

- **curl_cffi:** `requests.Session(impersonate=…)` was run directly, and so was
  dograpper's real `CurlCffiFetcher` (cases A–J, §3).
- **Firecrawl's Playwright engine:** there is no local Firecrawl. Its service code
  was reproduced with Python Playwright 1.58.0 and its headless Chromium 145
  (cases P1–P4, §2 Q3): `browser.newContext({userAgent})` plus
  `page.setExtraHTTPHeaders`. Firecrawl pins Playwright `^1.65`, so its Chromium
  is newer.
- **Self-hosted Firecrawl (docker compose): not run.** The stack builds the API
  and workers, the Playwright service, Redis, RabbitMQ, NuQ PostgreSQL and
  FoundationDB (`SELF_HOST.md:45-47`). That is not cheap. Without the closed
  service it would only show the `fetch` and `playwright` engines, and both are
  covered above.

## 1. Summary

- **One free-form `headers` map, no User-Agent option.** Firecrawl's scrape schema has
  `headers: record<string,string>` (`apps/api/src/controllers/v2/types.ts:830`, v1
  `controllers/v1/types.ts:478`) and no user-agent field. The docs say the map "can be
  used to send cookies, user-agent, etc." [code][docs]
- **No open code path realigns the rest of the identity to a custom UA.** Neither
  `apps/api/src` nor `apps/playwright-service-ts` mentions `sec-ch-ua` [code].
  Per engine:
  - `fetch` has no browser identity to keep coherent.
  - `playwright` leaves Chromium's own client hints in place, `"HeadlessChrome"`
    brand included [observed].
  - fire-engine passes the map verbatim to the closed service [code], so what it
    does there is [unknown].
- **dograpper's interim rule already matches Firecrawl's open engines.** Firecrawl
  replaces the User-Agent and leaves everything else. Realigning the client hints
  would go beyond what Firecrawl's open code does. It is not needed for parity.
- **curl_cffi, the implementation hinge** [observed]:
  - A user header with the same name as a profile header replaces it in place, and
    the profile's order is kept.
  - The `sec-ch-ua*` hints stay.
  - A header set to `None` drops that profile header.
  - `default_headers=False` drops every profile header.
  - Headers never change the TLS handshake [code].
- **`mobile`** only travels to fire-engine's `chrome-cdp` engine [code]. The docs
  admit that a site may still serve the desktop layout, and advise adding a mobile
  UA through `headers` [docs].
  - curl_cffi's `chrome_android` profile sends `sec-ch-ua-mobile: ?0` [observed].
    Its own "mobile identity" is not coherent either.
- **robots.txt is matched against a fixed product token,** `FirecrawlAgent`, never
  against the UA in `headers` [code][docs].
  - A different matching UA is the enterprise-only `robotsUserAgent` crawl option.
  - Crawls honor robots.txt by default. Scrapes do not check it unless a team flag
    is set [code].
  - dograpper has the same shape: it matches the fixed token `dograpper`, not the
    UA on the wire.

## 2. Answers to the six questions

### Q1. How does `headers` travel from the request schema to each engine?

- **Schema:** `headers` is an optional `record<string,string>` in v2
  (`controllers/v2/types.ts:830`) and v1 (`controllers/v1/types.ts:478`). The scrape
  schema has no other header or user-agent field. [code]
- **Before any engine:** only Safe Mode touches the map. With
  `safeMode.disableAuthentication`, `authorization`, `cookie` and
  `proxy-authorization` are stripped for every engine
  (`scraper/scrapeURL/index.ts:1345-1348`, `lib/safe-mode.ts:27-31,56-65`). Safe
  Mode is a team setting. Without it the map reaches the engines unchanged. [code]
- **`fetch` engine:** `undici.fetch(url, {headers: meta.options.headers, redirect:
  "follow"})` (`scraper/scrapeURL/engines/fetch/index.ts:157-162`). The map goes
  through verbatim.
  - undici adds its own `user-agent` only when the map has none (undici 7.30.1
    `lib/web/fetch/index.js:1468-1469`). The user's headers win.
  - TLS is Node's, with no browser impersonation. [code]
- **`playwright` engine:** the API forwards the map in the POST body to the
  Playwright service (`scraper/scrapeURL/engines/playwright/index.ts:16-22`). The
  service splits it:
  - **`User-Agent`**: found case-insensitively and set on the browser context
    (`newContext({userAgent})`), because Playwright ignores a UA passed through
    `setExtraHTTPHeaders` (`apps/playwright-service-ts/api.ts:409-421,178-202`).
  - **`Cookie`**: parsed into cookie-jar entries scoped to the last two host labels,
    so they survive redirects (`api.ts:426-481`).
  - **Every other header**: set with `page.setExtraHTTPHeaders` (`api.ts:483-493`).
    In the observation the extra headers landed right after `User-Agent`, and the
    rest of Chromium's header set stayed (P1–P4). [code][observed]
- **fire-engine engines:** the map goes verbatim into the payload as `headers`, for
  both `chrome-cdp` (`scraper/scrapeURL/engines/fire-engine/index.ts:497`) and
  `tlsclient` (`fire-engine/index.ts:729`).
  - Safe Mode strips the credential headers again worker-side
    (`fire-engine/index.ts:538-541,751-753`).
  - How the service merges the map with its own browser headers is [unknown].
- **Which side wins:** the user wins against `fetch`'s default UA. Against
  Playwright, the user's UA wins at the context level and the other headers are
  added, but Chromium's client hints are never removed [observed]. fire-engine:
  [unknown].

### Q2. Which fire-engine payload fields carry headers, the User-Agent or the mobile flag?

All in `scraper/scrapeURL/engines/fire-engine/scrape.ts` (the types) and
`fire-engine/index.ts` (where they are filled). [code]

| Field | Engines | Source | Meaning visible in the open code |
|---|---|---|---|
| `headers` | `chrome-cdp`, `tlsclient` | `scrape.ts:42`; `index.ts:497,729` | The user's map, verbatim. |
| `mobile` | `chrome-cdp` only | `scrape.ts:121`; `index.ts:505` | The scrape option. `tlsclient` has no such field (`scrape.ts:126-131`). |
| `mobileProxy` | both | `scrape.ts:59`; `index.ts:508,735` | Set from the `stealthProxy` feature flag: a proxy tier, not a device. |
| `geolocation` | both | `scrape.ts:57`; `index.ts:504` | `{country, languages}`. Its effect on `Accept-Language` is [unknown]. |
| `behaviorOverrides.useHeadlessUserAgent` | both | `scrape.ts:70`, filled by `safeModeParams` `scrape.ts:77-91` | A Safe Mode switch. Its existence implies that the service normally does not send a headless UA, i.e. it picks one itself. [unknown] |
| `behaviorOverrides.disablePlatformSelection`, `disableCountrySelection`, `disableAutomaticReferrer` | both | `scrape.ts:71-73` | The names imply that the service selects a platform (OS), a country and an automatic `Referer` by default. [unknown] |

What the docs say:

- `headers`: "Headers to send with the request. Can be used to send cookies,
  user-agent, etc." (`docs:api-reference/v2-openapi.json:9897`,
  <https://docs.firecrawl.dev/api-reference/endpoint/scrape>). [docs]
- `mobile`: "Set to true if you want to emulate scraping from a mobile device.
  Useful for testing responsive pages and taking mobile screenshots."
  (`docs:api-reference/v2-openapi.json:9907`). [docs]
- "If the site still serves a desktop layout despite `mobile: true`, add a mobile
  User-Agent via `headers`" (`docs:advanced-scraping-guide.mdx:171-179`,
  <https://docs.firecrawl.dev/advanced-scraping-guide>). The docs do not promise
  that `mobile` changes the UA. [docs]
- The docs say nothing about how the service treats a custom UA, client hints or
  header order. [unknown]

### Q3. With a custom User-Agent, what happens to the TLS/HTTP-2 fingerprint, `sec-ch-ua*` and header order?

- **Firecrawl `fetch`:**
  - TLS and HTTP: Node's, the same with or without a custom UA (no impersonation
    in `fetch/index.ts:157-162`).
  - Client hints: none are ever sent.
  - Header order: the map's insertion order plus undici's defaults, not observed.
  - A custom UA only replaces `undici`. Nothing is incoherent, because nothing
    claims to be a browser. [code]
- **Firecrawl `playwright`:** the observation reproduced the service's calls
  [observed]:

  | Case | `User-Agent` sent | `sec-ch-ua` | `sec-ch-ua-mobile` | `sec-ch-ua-platform` |
  |---|---|---|---|---|
  | P1: no UA override | `… HeadlessChrome/145…` (Linux) | `"Not:A-Brand";v="99", "HeadlessChrome";v="145", "Chromium";v="145"` | `?0` | `"Linux"` |
  | P2: Chrome/120 Windows string | as given | same as P1 (HeadlessChrome 145) | `?0` | `"Windows"` |
  | P3: `Custom-UA/1.0` | as given | same as P1 | `?0` | `"Windows"` |
  | P4: iPhone Safari string | as given | same as P1 | `?0` | `"iOS"` |

  - Client hints: Playwright realigns only `sec-ch-ua-platform` from the UA string.
    The brand list keeps `HeadlessChrome` and the real version. `sec-ch-ua-mobile`
    stays `?0` even for an iPhone UA. Hints are sent even when the UA claims to be
    Safari, which never sends them.
  - Header order: Chromium's own, with the user's extra headers inserted after
    `User-Agent`.
  - TLS: real Chromium, unchanged by the UA.
  - So Firecrawl's Playwright engine ships an incoherent identity on every request,
    because its default UA is random too (Q4).
  - Caveat: the observation used Playwright 1.58 with Chromium 145 headless shell;
    Firecrawl's service pins `^1.65`.
- **Firecrawl fire-engine** (`chrome-cdp`, `tlsclient`): [unknown]. The open code
  sends the map and nothing about client hints. The `useHeadlessUserAgent` and
  `disablePlatformSelection` overrides (Q2) suggest that the service chooses the
  identity itself, but nothing shows whether it realigns that identity to a custom
  UA.
- **dograpper fire-engine today** [observed], case J in §3:
  - User-Agent: `--user-agent` replaces the profile's `user-agent` line in place,
    and the order is the profile's.
  - Client hints: `sec-ch-ua` (Chrome 152), `sec-ch-ua-mobile: ?0` and
    `sec-ch-ua-platform: "Windows"` stay.
  - TLS: unchanged [code, §3].

### Q4. Which User-Agent does each engine send by default, and how does `mobile` change it?

- **`fetch`:** `undici`.
  - Firecrawl imports the `undici` package (`fetch/index.ts:1`) and builds with
    `tsc`, not a bundler (`apps/api/package.json:37`).
  - undici's default is `'undici'` outside Node's bundled copy (undici 7.30.1
    `lib/web/fetch/index.js:76-78`).
  - [code] (not observed).
- **`playwright`:** a random UA per request. `new UserAgent().toString()` from the
  `user-agents` package, generated for every new context unless the request carries
  a UA (`apps/playwright-service-ts/api.ts:185`). [code]
- **fire-engine:** [unknown].
- **`mobile`:**
  - It becomes the `mobile` feature flag (`scraper/scrapeURL/index.ts:351-353`), with
    priority 10 (`engines/index.ts:113,140`).
  - Only the `chrome-cdp` variants support it (`engines/index.ts:306` and its
    retry/stealth siblings). `playwright` (`:416`), `tlsclient` (`:438`) and `fetch`
    (`:482`) do not.
  - An engine has to cover half of the requested flags' priority
    (`engines/index.ts:954-957,1006`). A request with only `mobile: true` drops
    every engine without `mobile` support.
  - Self-hosted without `FIRE_ENGINE_BETA_URL` (`engines/fire-engine/available.ts:3-5`),
    nothing is left to run. Not run: I expect `NoEnginesLeftError`
    (`scraper/scrapeURL/index.ts:1176`).
  - What `chrome-cdp` does with `mobile` (UA, viewport, hints, TLS) is [unknown].
  - The docs' advice to add a mobile UA by hand (Q2) means it does not reliably
    change what the site sees. [code][docs]
- **dograpper fire-engine:** the profile's UA. `--impersonate chrome` (the default)
  sends Chrome 152 on Windows. There is no `mobile` option, but
  `--impersonate chrome_android` selects a whole mobile profile. That profile is
  itself inconsistent: it sends an Android UA with `sec-ch-ua-mobile: ?0` (case G).
  [observed]

### Q5. Does Firecrawl expose arbitrary headers rather than a user-agent special case? Should dograpper mirror it?

- **Firecrawl:** yes, arbitrary headers through one map, with cookies sent as a
  `Cookie` header (Q1) [code][docs]. The only special cases are inside engines:
  - Playwright moves the UA to the context and the `Cookie` header to the jar.
  - Safe Mode strips credential headers.
- **dograpper today:** no way to send an arbitrary header or a cookie.
  - Under fire-engine, only `Referer`, `If-None-Match`, `If-Modified-Since` and the
    `--user-agent` reach curl (`src/dograpper/lib/fire_engine/fetcher.py:26,118-120`).
  - Under httrack, the headers are the fixed HTTrack set
    (`src/dograpper/lib/httrack/policy.py:263-290`).
- **Recommendation:** yes, mirror it with a repeatable `--header 'Name: value'`.
  - One flag covers Firecrawl's `headers` map and HTTrack's own `-%X/--headers`
    (a `User-Agent:` line there replaces the engine's own:
    `docs/discovery/httrack-mirroring-requirements.md`, citing `src/htslib.c:1249-1253`).
    So it applies to both profiles.
  - `--user-agent` stays as a shorthand for `--header 'User-Agent: …'`.
  - With curl_cffi it is one rule: a user header replaces the same-named profile
    header in place, and any other header is added (cases B, D).
  - The cost is a CLI flag, a config key, the README and a guard under the wget
    path (map it to wget's `--header`, or reject it there).

### Q6. Which User-Agent does Firecrawl match robots.txt groups against, and is robots.txt honored by default?

- **Matching token:** the fixed tokens `FireCrawlAgent` and `FirecrawlAgent`
  (`apps/api/src/lib/robots-txt.ts:143-185`, default at `:146`). A URL is allowed
  if either token allows it.
  - robots-parser 3.0.1 lowercases the token and cuts it at `/`, so both are
    `firecrawlagent`. It picks that exact group, else `*` (`Robots.js:64-74,364-377`).
  - The UA in `headers` is never used for matching. The docs say so outright:
    "`FirecrawlAgent` is the token Firecrawl matches against … Do not assume it is
    also the `User-Agent` header on the fetch itself"
    (`docs:advanced-scraping-guide.mdx:683-684`). [code][docs]
- **Fetching robots.txt:** without the crawl's `headers`, unless `robotsUserAgent` is
  set (`scraper/WebScraper/crawler.ts:502-522`). It goes through the `fetch` engine
  first (`lib/robots-txt.ts:45-63`), so the UA on the robots.txt request is
  normally `undici`. [code]
- **Custom matching UA:** only `robotsUserAgent`, a crawl option
  (`controllers/v2/types.ts:1389`).
  - With it, robots.txt is fetched with that UA and the groups are matched against
    it (`crawler.ts:509-517,548-551,861-869`).
  - It is enterprise-only: rejected unless the team flag `customRobotsAgent` is
    `allowed` (`lib/permissions.ts:107-116`, `lib/zdr-helpers.ts:107-112`). [code][docs:
    `features/crawl.mdx:343`, <https://docs.firecrawl.dev/features/crawl>]
- **Default, crawl:** robots.txt is honored.
  - `ignoreRobotsTxt` (`controllers/v2/types.ts:1388`) takes effect only when the
    team's `ignoreRobots` flag allows it (`lib/crawl-redis.ts:1054-1058`); otherwise
    it is rejected as enterprise-only (`lib/permissions.ts:89-105`).
  - Self-hosted teams have `flags: null` (`controllers/auth.ts:182-187`), so the
    same rejection applies to them.
  - [code][docs: `features/crawl.mdx:308`]
- **Default, scrape:** robots.txt is not checked. `shouldCheckRobots` is true only
  under Safe Mode's `enforceRobots` or the team flag `checkRobotsOnScrape`
  (`scraper/scrapeURL/shouldCheckRobots.ts:8-19`, used at
  `scraper/scrapeURL/index.ts:1473`).
  - When it is checked, the match uses the default tokens
    (`scraper/scrapeURL/index.ts:1514-1517`). [code]
- **dograpper, compared:** robots.txt groups are matched against the fixed token
  `dograpper` (`src/dograpper/lib/httrack/robots.py:82,126-127`, called without a
  token from `src/dograpper/lib/httrack/fetcher.py:342`).
  - This holds whatever goes on the wire: the httrack UA, the impersonated Chrome UA
    or `--user-agent`.
  - robots.txt is honored unless `--no-robots` is given, under both profiles.
  - It has Firecrawl's shape: one honest product token that site owners can
    address, separate from the wire UA.
  - **Divergence from the issue:** #136 says dograpper matches robots.txt "against
    the profile's User-Agent". The code matches the token `dograpper` instead.

## 3. curl_cffi: how `impersonate` combines with user headers

How it works in code (curl_cffi 0.17.0, `.venv/lib/python3.13/site-packages/curl_cffi/`):

- **User headers** become header lines in `CURLOPT_HTTPHEADER`
  (`requests/utils.py:747-769`):
  - `None` writes `Name:`, which disables that header (`utils.py:749-750`);
  - `""` writes `Name;`, an empty header (`utils.py:751-752`).
- **Native target** (`chrome`, `chrome_android`, `safari_ios`, …):
  `c.impersonate(target, default_headers)` (`utils.py:951-953`) calls
  `curl_easy_impersonate` in libcurl-impersonate (`curl.py:585-598`). That sets the
  TLS options, HTTP/2 settings, the browser's base headers and their order inside
  libcurl.
- **Non-native fingerprint target**: the Python path merges the headers. "default
  headers will not override user-defined headers" (`utils.py:560-574`).
- **TLS:** the TLS and HTTP/2 options are set by `impersonate` independently of the
  header lines (`utils.py:421-559` for the Python path, `curl_easy_impersonate` for
  the native one). A custom UA therefore cannot change the ClientHello. This was not
  observed, because the echo server is plain HTTP.

Observed at the echo server, HTTP/1.1 [observed]:

| Case | Request | Result on the wire |
|---|---|---|
| A | `impersonate="chrome"`, no user headers | Profile set in profile order: `sec-ch-ua` (Chromium/Google Chrome 152), `sec-ch-ua-mobile: ?0`, `sec-ch-ua-platform: "Windows"`, `upgrade-insecure-requests`, `user-agent` (Chrome 152, Windows), `accept`, `sec-fetch-*`, `accept-encoding`, `accept-language`, `cache-control`; then `Host`, `Upgrade: h2c`, `HTTP2-Settings`, `Connection`. |
| B | + `User-Agent: Custom-UA/1.0` | UA replaced in its slot (5th line), written with the user's casing. All `sec-ch-ua*` unchanged. Order unchanged. |
| C | + `user-agent` (lowercase) | Same as B, with the line in lowercase: a match is case-insensitive. |
| D | + `X-Extra`, `Cookie`, `Accept`, `User-Agent` | `Accept` and `User-Agent` replaced in place. `Cookie` lands after `cache-control`. `X-Extra` is appended near the end. |
| E | + UA, `sec-ch-ua`/`-mobile`/`-platform` = `None` | The three hints are gone. Everything else as in B. **Realigning by dropping the hints is possible.** |
| F | `default_headers=False` + UA | Only `User-Agent`, curl_cffi's own `Accept-Encoding: gzip, deflate, br`, `Host` and the h2c upgrade lines. All profile headers are dropped. |
| G | `impersonate="chrome_android"` | Android UA (Chrome 131), `sec-ch-ua-platform: "Android"`, **`sec-ch-ua-mobile: ?0`**. `Host` goes first and the names are capitalized: a different order rule from `chrome152`. |
| H | + `Referer`, `If-None-Match` (dograpper's `_FORWARDED`) | `Referer` goes in the profile's slot (after `sec-fetch-dest`). `If-None-Match` is appended near the end. |
| I | dograpper `CurlCffiFetcher`, no `--user-agent` | Identical to A. |
| J | dograpper `CurlCffiFetcher`, `--user-agent Custom-UA/1.0` | Identical to B: the interim rule, with an incoherent identity. |

Limits of the observation:

- **HTTP/2:** on HTTPS with h2, the names are lowercased and sent in the profile's
  order. This was not captured; the HTTP/1.1 order shown follows the same list.
- **Plain `http://` targets:** curl_cffi adds `Upgrade: h2c`, `HTTP2-Settings` and
  `Connection: Upgrade, HTTP2-Settings`, and puts `Host` last. Chromium sends `Host`
  first and never asks for an h2c upgrade (P1). See follow-up 1.

The comment's leads, re-checked at the pinned commit:

- **Lead 1 holds:** `impersonate` sets the TLS/HTTP-2 fingerprint and the default
  headers as one identity, and the interim rule makes it incoherent (case J).
- **Lead 2 holds:**
  - Only `fetch` and `playwright` are open: the fire-engine engines exist only
    with `FIRE_ENGINE_BETA_URL` (`engines/index.ts:78-99`,
    `engines/fire-engine/available.ts:3-5`).
  - Playwright's payload is `url`, `wait_after_load`, `timeout`, `headers` and
    `skip_tls_verification` (`engines/playwright/index.ts:16-22`). Its features
    are `waitFor` and `skipTlsVerification` (`engines/index.ts:403-424`).
  - `mobile` is a priority-10 feature flag (`engines/index.ts:140`).
- **Lead 3, answered:**
  - A same-named user header overrides the default in place and keeps the order (B).
  - `default_headers=False` drops all impersonation headers, UA and `sec-ch-ua*`
    included (F), but keeps the TLS profile.

## 4. Comparison table

| Aspect | Firecrawl `fetch` | Firecrawl `playwright` | Firecrawl fire-engine (`chrome-cdp`, `tlsclient`) | dograpper fire-engine today |
|---|---|---|---|---|
| **Header input** | `headers` map [code] | `headers` map [code] | `headers` map, in the payload verbatim [code] | `--user-agent` only, plus the engine's `Referer` and validators [code] |
| **Default UA** | `undici` [code] | Random from `user-agents`, per request [code] | [unknown] | The profile's (Chrome 152, Windows) [observed] |
| **Custom UA** | Replaces the default [code] | Set on the browser context [code][observed] | Sent in `headers` [code]; then [unknown] | Replaces the profile's line in place [observed] |
| **`sec-ch-ua*` with a custom UA** | Never sent | Kept. The brand stays `HeadlessChrome`; only the platform is realigned [observed] | [unknown] | Kept: Chrome 152, Windows [observed] |
| **Header order** | Insertion order plus undici defaults (not observed) | Chromium's; extra headers after UA [observed] | [unknown] | The profile's; unknown headers appended [observed] |
| **TLS / HTTP-2** | Node, no impersonation [code] | Real Chromium (`api.ts:164`) [code] | [unknown] (tlsclient implies an impersonating client) | The profile's, independent of headers [code] |
| **Cookie** | As a header [code] | Moved to the cookie jar, last two host labels [code] | In `headers` [code]; then [unknown] | Not possible |
| **Arbitrary headers** | Yes | Yes (`setExtraHTTPHeaders`) | Yes (payload) | No |
| **`mobile`** | Not supported: dropped from the waterfall [code] | Not supported [code] | `chrome-cdp` only, `mobile` field [code]; effect [unknown] | No flag; `--impersonate chrome_android` (sends `sec-ch-ua-mobile: ?0`) [observed] |
| **robots.txt token** | `FirecrawlAgent`, or the enterprise `robotsUserAgent` [code] | (same: per crawl) | (same) | `dograpper` [code] |
| **robots.txt request UA** | `undici` via the `fetch` engine, or `robotsUserAgent` [code] | (same) | (same) | The impersonated identity, plus `--user-agent` [code] |
| **robots.txt by default** | Crawl: honored. Scrape: not checked [code] | (same) | (same) | Honored unless `--no-robots` [code] |

## 5. What "copy Firecrawl" can and cannot mean here

- **The contract is copyable:** a free-form header map, user values winning, a fixed
  robots token. These are verified in code. The interim rule already copies the
  open engines' User-Agent behavior.
- **Firecrawl's fire-engine identity handling is not copyable:** the closed service
  is where a browser identity meets a custom UA, and its behavior is [unknown].
  Whatever dograpper does with client hints is dograpper's own decision. ADR-0011
  must record it as such, not as parity.
- **The open engines are no model for coherence:** Firecrawl's Playwright engine
  sends incoherent identities by default: a random UA with HeadlessChrome hints.

## 6. Target behavior

**Decided by the maintainer, 2026-11-19: Option B, with the repeatable `--header`
from Q5.** The robots.txt part of the recommendation below (keep the fixed token
`dograpper`) was not part of that answer, so it stays a recommendation until it is
confirmed.

The fork. In both options, the default with no `--user-agent` stays as it is: the
profile's coherent identity.

### Option A: the identity is a coherent profile

- **Rule:**
  - The UA follows from `--impersonate` and is never free text.
  - Under fire-engine, `--user-agent` is a usage error (exit 2) that points to
    `--impersonate`.
  - Mobile means a mobile profile (`--impersonate chrome_android`, `safari_ios`).
    There is no separate `mobile` flag.
- **What it buys:**
  - curl_cffi never sends a UA that contradicts its TLS fingerprint.
  - It is the smallest implementation: a guard plus docs.
- **What it costs:**
  - It breaks Firecrawl's contract, where `headers` can carry any UA. ADR-0011 must
    record the deviation.
  - Users who need a given UA string (a site that allow-lists a UA, or an
    identifying UA) lose it under fire-engine.
  - Coherence is only as good as the profile. `chrome_android` already sends
    `sec-ch-ua-mobile: ?0` (case G).
  - It conflicts with `--header` (Q5): a user `User-Agent:` header would have to be
    refused too.

### Option B: free `--user-agent` with the hints realigned

- **Rule:**
  - An explicit UA, from `--user-agent` or `--header 'User-Agent: …'`, replaces the
    profile's UA in place. This is today's rule.
  - Whenever an explicit UA is given, dograpper also drops `sec-ch-ua`,
    `sec-ch-ua-mobile` and `sec-ch-ua-platform` (`None`, case E). Those values
    describe the profile's UA. dograpper cannot tell whether a given UA matches the
    profile without reading the profile's headers out of libcurl-impersonate, so
    the rule does not try.
  - The user can add hints back explicitly with `--header`, and a user header
    always wins.
  - The TLS profile stays. dograpper warns once per run that the TLS fingerprint
    still says `<profile>`, and ADR-0011 records that residual mismatch.
- **What it buys:**
  - It keeps Firecrawl's contract: the user's UA gets sent.
  - It removes the one inconsistency that can be removed, without inventing hint
    values (no UA parsing, no brand rewriting).
- **What it costs:**
  - The TLS-vs-UA mismatch remains, and a WAF that cross-checks the two can still
    reject the request.
  - A Chromium-family UA loses hints that a real Chrome would send, even one equal
    to the profile's. That is a milder anomaly, and `--header` can put the hints
    back.
  - A little more code and tests: the hint drop, the warning, and the real
    curl_cffi checks at the local server.
  - This realignment goes beyond Firecrawl's open engines. It is a recorded
    dograpper choice, not parity (§5).

### Recommendation

**Option B, together with the repeatable `--header` from Q5, and robots.txt kept as
it is:**

- **Keep the fixed token `dograpper`.** It is Firecrawl's shape, and site owners can
  address it. ADR-0011 should state that the token is not the wire UA, as
  Firecrawl's docs do.
- **No `robotsUserAgent` equivalent** until someone needs it.
- **Why B:**
  - The maintainer's rule is to copy the reference tool. Firecrawl's verifiable
    contract lets the user's UA through.
  - Option B honors that contract, and only removes values that are known to be
    false.
  - Option A would make dograpper stricter than Firecrawl on its own contract.
  - The point of fire-engine is to pass WAFs. Under B, the user who sets a UA takes
    that risk knowingly, after the warning, and the default stays coherent.
- **For the implementation PR:**
  - Replace `_FORWARDED` plus the UA special case with one rule: user headers
    replace in place, and an explicit UA also drops the three hints.
  - Test at a local server with the real curl_cffi: cases B, E and J become
    assertions.

## 7. Follow-up candidates (out of scope here)

1. **Plain-`http://` fingerprint:** curl_cffi's HTTP/2 setting makes curl send an h2c
   upgrade (`Upgrade: h2c`, `HTTP2-Settings`) and put `Host` last on `http://`
   targets (cases A–J). Chromium does neither (P1). dograpper's fire-engine on
   plain-HTTP sites therefore carries a non-browser marker. A candidate fix is to
   use HTTP/1.1, or curl's `2TLS` mode, for `http://`.
2. **curl_cffi `chrome131_android`** sends `sec-ch-ua-mobile: ?0` (case G). Compare
   with a real Chrome Android capture before overriding it, and report it upstream.
3. **dograpper's own Playwright layer** (`--headless`, `lib/playwright_crawl.py`) may
   leak `HeadlessChrome` in `sec-ch-ua` the way P1–P4 do. Not checked.
4. **fire-engine service defaults that dograpper lacks:** an automatic `Referer`
   (`disableAutomaticReferrer`), platform and country selection, and `geolocation`
   languages (Q2). All [unknown]. dograpper sends HTTrack's `Referer` and the
   profile's `Accept-Language`.
5. **`mobile` in the waterfall:** `mobile: true` drops every non-`chrome-cdp` engine
   (Q4). This belongs to engine selection, which #136 leaves out of scope.
6. **Robots matching details:** Firecrawl also blocks `/path` when `/path/` is
   disallowed (`lib/robots-txt.ts:162-176`). It picks groups by exact token
   (robots-parser), where dograpper uses a prefix match (`robots.py:126`). Both
   differ from dograpper's HTTrack/RFC 9309 rules. The ADR-0011 note should state
   which side dograpper follows.
7. **Firecrawl's Playwright cookie scope** (the last two host labels) is wrong for
   multi-part public suffixes such as `co.uk` (`api.ts:447-449`). This matters only
   if dograpper ever seeds a browser jar from `--header 'Cookie: …'`.
8. **`--user-agent` help text** says `[httrack] … (default: dograpper identifier)`
   (`src/dograpper/commands/download.py:300-301`). Under fire-engine it also
   applies, and the default there is the profile's UA. Fix it with the
   implementation PR.
9. **Firecrawl Local** (`apps/local`, a separate Rust product) sends a Chrome-like UA
   with an identifying `FirecrawlLocal/<version>` suffix, and has a robots token of
   the same name (`apps/local/src/fetch.rs:17-24`). It is a different design point:
   an honest, identifying UA. It is not one of the API's engines.
10. **Header-name case:** a user header keeps the user's spelling (`User-Agent` in
    case B, next to the profile's lowercase lines). The mix is visible on HTTP/1.1
    only; HTTP/2 lowercases every name. Whether to normalize it depends on the
    profile (`chrome152` is lowercase, `chrome131_android` is capitalized, case G).
