# Session decisions

An operational log of the decisions an agent session took on its own: a choice
between two readings of a request, a deviation from the brief, a convention
picked where the repo had none, or a question left for the maintainer. It is
more granular than an ADR and cheaper to write.

- A decision that changes architecture or an inviolable contract (CLAUDE.md)
  goes to `docs/adr/` instead; an entry here can link the ADR it led to.
- A review finding accepted without a fix goes to `docs/DEBT.md`.
- Newest entry first. Never rewrite an old entry: add a new one that
  supersedes it and say so.

Entry format:

```markdown
## YYYY-MM-DD — <topic> (#issue or PR)

- **Decision:** <what was chosen>
- **Why:** <the evidence or constraint that decided it>
- **Rejected:** <the alternatives, one line each>
- **Pending:** <what the maintainer still has to answer, or "none">
```

## 2026-11-18 — HTTrack's change report ported with the payload MD5 (#132)

Supersedes the "-%d is not ported" decision of the entry below: the maintainer
picked option (a).

- **Decision:** `--changes` writes `hts-changes.json` in `-o`, in
  `htschanges.c`'s format. Each manifest record gains `payload_md5`, the MD5 of
  the body as received before `-K0`, which stands for the body HTTrack's cache
  keeps; a parsed file is compared by it.
- **Why:** HTTrack compares a parsed page by its payload because the saved copy
  carries rewritten links (`src/htschanges.c:299-345`). Comparing the saved
  bytes would report a page as changed when only its links moved.
- **Rejected:** comparing the saved bytes (option b); not porting it (option c).
- **Pending:** none. The deviations the port needs are recorded in spec §5.6
  ("Change report"):
  - `generator` names dograpper;
  - `purged` is false;
  - `url` follows the manifest's rule for the URL requested;
  - the previous payload is read from the record of the same file;
  - every page counts as parsed;
  - files not reached are listed by path, seeded files in seed order;
  - a failed run writes no report.

## 2026-11-18 — HTTrack cache and update options in the httrack profile (#132)

- **Decision:** HTTrack's cache mode is one flag, `--cache 0|1|2` (HTTrack's
  `--cache=N`), default `None` meaning HTTrack's own (`2` over a manifest,
  else `1`); no `--update` / `--continue` aliases.
- **Why:** HTTrack's two aliases are `-iC2` and `-iC1`, and `-i` resumes the
  command line saved in the cache, which dograpper has no use for (the URL is
  required); one flag gives one config key and one precedence path.
- **Rejected:** `--update` and `--continue` as extra flags; a `--cache` default
  of `1` (an explicit `1` would then be indistinguishable from the default
  that switches to `2` over a manifest).
- **Pending:** none.

- **Decision:** HTTrack's change report (`-%d` / `--changes`,
  `hts-changes.json`) is not ported in #132; it stays under the spec's "Known
  gaps".
- **Why:** HTTrack sorts a parsed page into `changed` or `unchanged` by the MD5
  of its payload, the previous one read from the body its cache holds
  (`src/htschanges.c:299-345`), because the saved copy carries rewritten
  links. dograpper keeps no cache body, and its saved pages carry `-K0` links,
  so a page whose links were rewritten differently would read as `changed`.
  Porting it faithfully needs a new manifest field, a choice for the
  maintainer rather than a deviation invented here.
- **Rejected:** comparing the saved bytes (an unapproved deviation that
  over-reports `changed`); porting it with no page comparison at all.
- **Pending:** pick one: (a, recommended) record the MD5 of each parsed page's
  payload in its manifest record (one new `RECORD_FIELDS` entry) and compare
  that, which reproduces HTTrack; (b) compare the saved bytes and record the
  deviation in spec §5.6; (c) leave `-%d` out of the profile. Either port also
  adds `hts-changes.json` to the state files `pack` and `build_manifest` skip,
  writes it only for a run that ends without a front failure (HTTrack: only a
  completed run, `src/htscore.c:2360-2367`), and reports `first_crawl: null`
  under `--cache 0`.

- **Decision:** `--cache`, `--updatehack` and `--do-not-recatch` act under
  `--downloader fire-engine` exactly as under `httrack`, through the shared
  `run_profile()` cascade (#130); no flag is refused there. Recorded in
  ADR-0011, "Fatia 2".
- **Why:** #130 gave fire-engine the update mode (the previous manifest, its
  records), and the three options are policy and engine state, not transport
  state. The one transport-specific piece, `-%s`'s `stop`, is honored in
  curl's writer.
- **Rejected:** refusing the three under fire-engine (written before #130, when
  fire-engine ran no update, and dropped in the replay onto the batch).
- **Pending:** none.

- **Decision:** `--updatehack` decides at the headers through a `stop`
  predicate of `Fetcher.get`, passed to `_request` only when set;
  `CurlCffiFetcher._request` honors it too, in curl's writer (#130): at the
  first chunk it asks `stop` with the status, `Content-Type` and
  `Content-Length` curl reports (`CURLINFO`, the headers a writer can read
  mid-transfer) and aborts the transfer, so no byte of the body is kept or
  charged; a transfer that brings no chunk is asked once it ends, with the
  response's headers. Its keeps are listed apart in the report (`Kept on a
  matching size (--updatehack)`), not in `Not modified (304)`.
- **Why:** HTTrack drops the connection before the body (`deletehttp`), so
  reading the body and discarding it differs on the wire; passing `stop` only
  when set keeps every `_request` override working. A separate line says why
  a file was kept, as HTTrack's NOTICE does.
- **Rejected:** comparing sizes after the full body is read; a thread-local
  channel to `_request`.
- **Pending:** none.

- **Decision:** `--do-not-recatch` under `--cache 1` does not empty a file
  whose size changed before requesting it, where HTTrack `-%n` does
  (`src/htscache.c:796-814`). Recorded in spec §5.6 as a deviation.
- **Why:** the spec's deviations are where HTTrack spoils the corpus (user
  option "1"): emptying first loses the copy when the request then fails.
- **Rejected:** emptying it as HTTrack does.
- **Pending:** none.

- **Decision:** `--cache 0` neither reads nor writes the records: each file
  keeps the record the previous run made for its URL.
- **Why:** HTTrack `-C0` leaves `hts-cache/` untouched (`src/htscache.c:59`,
  `1174`), so its next update revalidates against the previous cache.
- **Rejected:** recording this run's validators (a deviation with no corpus
  reason); dropping all records.
- **Pending:** none.

- **Decision:** under `--cache 1` every recorded file, a page included, is
  loaded only when its size is the recorded one; otherwise it is fetched in
  full. HTTrack writes a page again from its cache body instead.
- **Why:** dograpper keeps no cache body; one rule for every type, and the
  closest outcome to HTTrack's (the site's bytes on disk), at the cost of one
  request. Recorded in spec §5.6 as a deviation.
- **Rejected:** keeping an edited page as it is without a request.
- **Pending:** none.

- **Decision:** a file time that cannot be set (`os.utime` fails) is an error
  of the run report, and the file is kept; HTTrack ignores the return value of
  `set_filetime_rfc822`.
- **Why:** the global rule is no silent fallback; the failure cannot spoil the
  corpus, so it does not stop the run either.
- **Rejected:** ignoring it as HTTrack does; failing the run.
- **Pending:** none.

- **Decision:** `pack --delta` lets the content hashes decide whenever both
  pack states carry them, and keeps the mtime fast path only for an entry
  written before hashes existed.
- **Why:** file times from `Last-Modified` let a rewrite keep size and mtime;
  `build_manifest` hashes every file anyway, so the fast path saved nothing.
- **Rejected:** not porting HTTrack's file times; a separate mtime source for
  the pack state.
- **Pending:** none.

## 2026-11-18 — fire-engine decodes in Python; its extra gains brotli and zstandard (#130)

- **Decision:** curl's decoding is off and its writer bounds the raw body;
  `Fetcher.get` decodes it with the httrack `_decode`. The `fire-engine` extra
  now also lists `brotli>=1.2` and `zstandard>=0.22` (the `httrack` extra's
  decoders, already in the lock: no new package). `--timeout` maps to curl's
  connect timeout plus a low-speed abort (no byte for `--timeout` s), not to a
  total transfer time.
- **Why:** a write callback alone still lets curl's own decoder expand a zstd
  frame with a window up to 128 MiB; the shared decoder keeps the 8 MiB cap.
  The Chrome profile advertises `br, zstd`, so without the decoders those
  pages would fail to decode. A total timeout would abort large pages that are
  paced by `--max-bandwidth` inside the writer.
- **Rejected:** keeping curl's decoding with a capped writer (zstd window
  unbounded); overriding `Accept-Encoding` to what Python can decode (breaks
  the browser fingerprint); a total-time timeout (curl_cffi's non-streaming
  default).
- **Pending:** none.

## 2026-11-18 — fire-engine sends only the request-specific httrack headers (#130)

- **Decision:** `CurlCffiFetcher` forwards to curl only `Referer`,
  `If-None-Match` and `If-Modified-Since` from the httrack header set; the
  browser identity comes from the `--impersonate` profile (ADR-0011,
  "Fatia 2").
- **Why:** the validators must reach the server for the update mode, and
  mixing HTTrack's identity headers with a Chrome TLS handshake is the
  mismatch a WAF flags.
- **Rejected:** forwarding the whole httrack set (breaks the fingerprint);
  forwarding the per-link `Sec-Fetch-*` (no site in the project needs it yet).
- **Pending:** none. `--user-agent` under `fire-engine` was resolved by the
  maintainer (2026-11-18): an explicit value replaces the profile's
  User-Agent, the rest of the identity unchanged. The exact Firecrawl
  behavior to copy is researched in #136.

## 2026-11-18 — Anti-bot evasion is no longer an anti-goal

- **Decision:** challenge or CAPTCHA solving, JavaScript challenge execution,
  browser TLS (JA3/JA4) or HTTP/2 fingerprint impersonation and proxy rotation
  are no longer anti-goals of dograpper. The `httrack` profile design listed
  them as "a failure even if it works". They are now a non-goal of that
  profile only, and another downloader may implement them.
- **Why:** maintainer decision. dograpper collects publicly available
  documentation, and its fetch paths already pace requests (connection rate,
  bandwidth, per-host gap, Retry-After, robots.txt). The target is scraping
  parity with Firecrawl-style engines.
- **Rejected:** dropping the exclusion from the `httrack` profile too. That
  profile's goal is behavior identical to HTTrack, which has none of these.
- **Pending:** confirm the `httrack` profile keeps them out, and design the
  downloader that adds them (an ADR first: a native dependency such as
  `curl_cffi` falls under contract 1).

## 2026-11-18 — Table cells in plain text, Javadoc grids in md only (#125, #120)

- **Decision:** (#125) the plain-text renderer starts each `td`/`th` with a
  tab (private marker, turned into `\t` when the prose is rendered; a `<tr>`
  also starts a block, since `</td>` and `</tr>` may be omitted); the md
  renderer does not emit it. (#120) a Javadoc `div.summary-table` with a
  `two|three-column-summary` class is a table in md: its child divs are the
  cells, N to a row, the first row the header. The plain path keeps one cell
  per paragraph for these grids.
- **Why:** `text.split()` counts ` | ` as a word, a tab is whitespace, so
  word counts (ADR-0003) change only where gluing had merged two words. The
  grid reuses the md table frame and `_pipe_table`; the plain path has no
  frames, so one line per grid row there needs a second row tracker in the
  base class, and the issue asks for md.
- **Rejected:** ` | ` in plain text (inflates counts); a space (cells with
  several words become ambiguous); a plain-text grid renderer (follow-up if
  grep over txt/jsonl needs it).
- **Pending:** whether txt/jsonl should also get one line per Javadoc grid row.

## 2026-11-18 — httrack profile update mode (#78, PR 3)

- **Decision:** a challenged start URL still exits 1 on an update (its previous
  copy kept, the manifest not rewritten), while a start URL answering 404/5xx
  is kept and the run goes on, as HTTrack does for both.
- **Why:** spec §5.4 makes a challenged start URL exit 1 with the
  `--browser-login` hint; a corpus refreshed on a schedule should fail loud
  when the site starts refusing dograpper rather than go stale with exit 0.
- **Rejected:** exit 0 with `Challenged: N`, as HTTrack masks the 403.
- **Pending:** the maintainer may prefer HTTrack's behavior; one condition in
  `crawl.fetch_url_list.keep` and `mirror.keep` decides it.

- **Decision:** the manifest gains `redirected`; the validators of a file
  reached through a redirect go to the hop whose file name is exactly that
  file's (`crawl.sends`), and that hop alone gets the name back.
- **Why:** HTTrack sends the redirecting URL plain and the target its
  validators; the manifest never records the target (it can carry a secret).
  Without the flag every redirected start URL would be refetched in full. The
  name check (added after review) stops a redirect that now leads to another
  page from getting a 304 for the old one.
- **Rejected:** validators on every hop after the first (a changed redirect
  got the old page kept as the new one's); recording the target URL (breaks
  the README's "requested URL only" rule).
- **Pending:** none.

- **Decision:** a kept page's links are read back from its saved copy and
  mapped to URLs through the previous manifest; no cache of original bodies.
- **Why:** HTTrack re-parses a 304 page from `hts-cache/`; a dograpper cache
  would be a new state directory that `pack` and `build_manifest` must skip,
  and would double the disk use. The cost is recorded in spec §5.6: a file
  with `"url": null` is not reached from a kept page.
- **Rejected:** a body cache under `-o`; refetching a 304 page to read it.
- **Pending:** none.

- **Decision:** `NameRegistry.reserve()` keeps the names of the files an update
  may keep: only the URL a file was saved from gets it back (`assign(prefer=)`,
  matched through `url_key`, so userinfo or spelling never matter), and none is
  renamed. A previous entry whose file is not named as its URL would be is
  ignored, so an edited manifest cannot direct a write.
- **Why:** names come in queue order; on a changed site a new page could take
  a kept file's name and overwrite it, and the kept pages' links (never
  rewritten) point at those names.
- **Rejected:** HTTrack's rename of a file whose name changed (breaks the
  links of kept pages).
- **Pending:** none.

- **Decision:** HTTrack's other cache options (`-C0`, `-C1`/`--continue`,
  `-%s`, `-%n`, `--changes`) and file times from `Last-Modified` are left as
  known gaps (spec), not ported in PR 3.
- **Why:** the epic scopes PR 3 to manifest records and conditional
  revalidation, and PR 2 set the precedent for listing an HTTrack feature not
  ported yet (#122). File times interact with the mtime fast path of
  `pack --delta` (ADR-0008).
- **Rejected:** porting them in the same PR (doubles its spread).
- **Pending:** an issue for the follow-up PR under #78.

## 2026-11-18 — HTTrack -j and -%P in the httrack profile (#122)

- **Decision:** two boolean `[httrack]` flags, `--no-parse-scripts` (HTTrack
  `-j4`) and `--no-extended-parsing` (`-%P0`, the same effect as `-j8`), not
  a `-j` bitmask flag.
- **Why:** of `-j`'s bits only `|4` and `|8` change anything here. `|2` and
  `-j0` switch HTTrack's external parser modules (`src/htscore.c:2020-2022`),
  plug-in callbacks dograpper has none of; the built-in `.class` parser is
  gone (`history.txt:458`). Two booleans cover every effective state, and
  match `--no-robots`'s shape.
- **Rejected:** `--parse-java N` with HTTrack's bitmask (two of its values do
  nothing here, and `-j0` would silently keep scripts scanned, as HTTrack's
  code does against its help text).
- **Pending:** the maintainer may prefer HTTrack's names or bitmask.

- **Decision:** the scans run on the contexts PR 2's HTML5 tokenizer reads (a
  tag's attributes, a `<script>`/`<style>` body), HTTrack's byte rules inside
  each; a script attribute ends at its HTML5 value, or earlier where HTTrack
  ends it (the byte after `=`, or `>`).
- **Why:** porting HTTrack's byte-level tag reader would replace PR 2's
  tokenizer, the piece that keeps parsing linear; the two read apart only
  markup such as a `>` inside a quoted event handler.
- **Rejected:** a byte-level port of HTTrack's whole loop (disproportionate,
  and it would undo PR 2's linear-time guarantee).
- **Pending:** whether this belongs in spec §5 as a deviation; recorded in
  §5.5 and the evidence doc as a convention.

- **Decision:** CSS `url()` / `@import` now go through the ported
  `hts_js_scan_link` (in CSS mode) instead of PR 2's regex, and so stop with
  `--no-parse-scripts`.
- **Why:** HTTrack has one scanner for both (`src/htsparse.c:584`, 630-640),
  so `-j4` turns CSS links off too.
- **Rejected:** keeping the regex (a second, diverging CSS rule).
- **Pending:** none.

- **Decision:** `document.write("…")` parsing (`src/htsparse.c:1828-1880`)
  is not ported, and links found by the scans are not rewritten (`-K0`).
- **Why:** the first never fires on a string with content in HTTrack 3.51
  (its closing-quote loop stops on the opening quote, lines 1847-1852); the
  second is recorded as a known gap in the spec.
- **Rejected:** none.
- **Pending:** a follow-up for the rewrite under #78.

## 2026-11-18 — Harness patterns mirrored from open-notes (#35)

- **Decision:** Phases 2–5 of the epic ship as one commit each in a single
  batch PR. Phase 1 (the `setup-matt-pocock-skills` skill) is left to the
  maintainer because it is interactive.
- **Why:** this repo's practice is one combined PR per batch of parallel
  sessions; the epic was written for one PR per phase.
- **Rejected:** one PR per phase (the batch flow already reviews them
  together).
- **Pending:** Phase 1.

- **Decision:** `block-dangerous-git.py` fails open on its own errors (bad
  JSON, an exception), unlike the open-notes original, which fails closed.
  An `--amend` whose repository it cannot tell is still blocked, as in the
  source, and so is a git command that does not tokenize (review finding):
  those are policy decisions, not errors.
- **Why:** a broken guard must never stop normal Bash work, and a hook that
  hangs is already let through by the harness timeout, so failing closed
  would only cover crashes.
- **Rejected:** fail closed (one crash would block every Bash call that
  mentions git).
- **Pending:** none.

- **Decision:** the push rule blocks any direct push to `main` or `develop`
  without user consent. There is no `GATES=green` attestation.
- **Why:** every change lands through a reviewed PR here; open-notes pushes to
  `main` after a local merge, which this repo never does.
- **Rejected:** porting the gates attestation as is.
- **Pending:** none.

- **Decision:** the living glossary is `docs/glossario.md` (pt-BR, didactic),
  separate from `GLOSSARY.md` (domain language, normative). A domain term is
  never redefined in `docs/glossario.md`; its entry points to `GLOSSARY.md`.
- **Why:** the `/explique` and `/revisao` commands read and write
  `docs/glossario.md` in a fixed format; `GLOSSARY.md` follows the
  domain-modeling format and names things in code.
- **Rejected:** merging both into `GLOSSARY.md` (two formats and two readers
  in one file).
- **Pending:** none.

- **Decision:** saved HTTP error pages (#121) are detected by `utils/error_page.py` (new module), not folded into `utils/challenge.py`; rule = `<title>` fully matches `[45]xx <reason>` AND file <= 16 KiB AND <= 40 visible words (scripts/styles dropped); wired as step 6a-1 of `pack`, a second copy of the 6a block.
- **Why:** `challenge.py` is Cloudflare-specific and shared with the httrack fetcher; the error-page rule has no fetcher use. Both layouts and `--dry-run` run after 6a, so they inherit the skip. Second copy tolerated per the project rule; a third skip class should extract the shared block.
- **Rejected:** matching "404" anywhere in the text; requiring an `<h1>` (not all servers emit one).
- **Pending:** none.

## 2026-11-18 — -K0 of the links the script scans take (#133)

- **Decision:** a link the scans take (script, stylesheet, `style=`, handler,
  `javascript:`, `-%P`) is written exactly as HTTrack writes it
  (`escape_uri_utf` path, `%28`/`%29` in a CSS `url()`, query appended, `&` raw
  in script text), while a link attribute keeps PR 2's form (`%`/`#` only, no
  query).
- **Why:** the brief asks for HTTrack's form; `pack --cross-refs` reads only
  `<a href>` and resolves it as a path with no percent-decoding or query cut,
  so changing the attribute form would break it. Recorded as a deviation in
  spec §5.6.
- **Rejected:** one form for both (either breaks `--cross-refs` or deviates on
  scanned links with no reason).
- **Pending:** none.

- **Decision:** a script whose loading page has no saved file gets absolute
  links (its module specifiers stay relative to the script).
- **Why:** HTTrack writes them relative to the page's planned name; dograpper
  makes any link to an unsaved file absolute (PR 2), and with no saved page
  there is nothing to be relative to. Recorded in spec §5.6.
- **Rejected:** writing them relative to the script itself (wrong base).
- **Pending:** none.

- **Decision:** `_kept_links` reads kept stylesheets and scripts too, and
  decodes a kept link with `unquote` instead of `%25`/`%23` only.
- **Why:** once relink rewrites them, a kept copy holds saved names; reading
  them against the URL would request names that are not URLs (a regression
  the update test shows). `unquote` inverts both escapes in use.
- **Rejected:** leaving kept stylesheets and scripts unrewritten (they are
  rewritten when first saved, so the copy already holds names).
- **Pending:** none.

- **Decision:** `import "./m.js"` is written `import "m.js"`, as HTTrack does
  (`./` dropped, `src/htsparse.c:2717-2726`; `lienrelatif` adds none).
- **Why:** faithful port; a browser refuses a bare module specifier, so an
  offline mirror of module code breaks there as HTTrack's does.
- **Rejected:** prefixing `./` (an unrecorded deviation).
- **Pending:** maintainer: keep HTTrack's form, or deviate (spec §5) to keep
  module imports working offline.
