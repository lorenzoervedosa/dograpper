# Accepted technical debt

Review findings accepted without a fix. Every item a review accepts without
fixing it lands here, with the reason and the condition that would make it
worth fixing. A fixed item is marked, not deleted.

Status markers: ⏸ accepted · ✅ fixed (link the commit or PR).

Entry format, grouped under one heading per issue or PR:

```markdown
## <topic> (#issue or PR, YYYY-MM-DD)

- **<finding in one sentence>.** <evidence: file:line, metric>. ⏸ **accepted:
  <why now is not the time>; <what would trigger the fix>.**
```

## fire-engine headers and `--header` (#136, #156, #157, 2026-11-20)

- **`tests/test_httrack_mirror.py` keeps its own `_Silent` http.server outside the `http_server` mold of `tests/conftest.py`, and never shuts it down.** `tests/test_httrack_mirror.py` (`_Silent`, started next to the `server` fixture). ⏸ **accepted: the file belongs to another lane in this wave; fix on the next change to that test's servers, by starting `_Silent` through `http_server`.**
- **`config_note()` and `FROM_CONFIG` live in `commands/_httrack_profile.py`, though `commands/download.py` imports them for `--filter`, which is not a profile flag.** Their natural home is `lib/config_loader.py`, next to `is_explicit()`. ⏸ **accepted: `lib/config_loader.py` was outside the fire lane's zone; move them on the next change to `lib/config_loader.py`.**
- **An empty User-Agent (`--user-agent ''` or `--header 'User-Agent:'`) falls back silently to the profile's.** Under httrack that is the dograpper default UA; under fire-engine, the impersonated one with its client hints and no warning (`policy.user_agent or DEFAULT_USER_AGENT`, `if self._user_agent:` in `lib/fire_engine/fetcher.py`). HTTrack `-F ""` and `curl -H 'User-Agent:'` send no User-Agent at all. The `--user-agent ''` case predates #136. ✅ **fixed (#183): the maintainer decided an empty User-Agent sends none (2026-11-20); every source, both profiles, the client hints dropped under fire-engine.**

## `--cookies` and `--browser-login` (#169, #171, 2026-11-24)

- **The browser pass merges the context's cookies back into the jar only when its crawl loop ends normally.** `run_playwright_crawl` (`lib/playwright_crawl.py`) calls `navigator.detach(context)` after the loop, not in a `finally`: an exception outside the per-page `try`, such as a crashed browser at `page.goto("about:blank")`, skips it, and the jar is still written (`commands/_run_jar.py`) but without what the browser held. ⏸ **accepted: a `finally` re-indents the crawl loop that the browser lane also edits in this wave, and after a crash `context.cookies()` cannot be read anyway; fix when the loop is next restructured, or when a run is seen losing the browser's cookies this way.**
- **No public suffix list in the jar's Domain check.** `_claimable()` (`lib/httrack/cookies.py`) refuses a `Domain` that is an IP or has no dot, and the stdlib refuses a few two-letter-country second levels (`.co.uk`), but a `Set-Cookie: Domain=github.io` from `a.github.io` is taken, and would match `b.github.io`. The jar is bound to the start host, so such a cookie only reaches that host's own requests. ⏸ **accepted: the list would be a new dependency (maintainer decision, 2026-11-24); fix when the jar sends cookies to more than the start host, or when a crawl is seen taking a public-suffix cookie.**
- **`Origin` on CORS requests is not sent under `--browser-headers`** (HTTrack: `htslib.c:1323-1340`, its test 603 "chrome font origin"). The profile's `FetchMeta` carries no initiator to take it from; the spec lists it under "Known gaps". ⏸ **accepted: the maintainer chose a follow-up issue (2026-11-24), opened by the wave's integrator; fix there.**

## Docs site, stage 1 (#176 and this PR, 2026-11-20)

- **The sync page lost the grouped rows' "see Downloader profiles" pointer and the per-flag "(passed to download/pack)" notes.** `site/commands/sync.md` has the generated table instead of the README rows. ⏸ **accepted: the generated table keeps the profile tags and the `--downloader` detail links the section; fix at the cutover tightening.**
- **Positional arguments (`CHUNKS_DIR`, `URL`, ...) have no table row.** The `dograpper-options` directive (`site/conf.py`) lists `click.Option` only. ⏸ **accepted: the usage lines and prose cover them; fix at the cutover, or when a reader misses an argument description.**
- **No CI job builds the site.** A break in the directive or an include shows only on a local `-W` build. ⏸ **accepted: the spec defers CI to the cutover; fix at the cutover, or on the first broken local build.**
- **The generated tables show `Sentinel.UNSET` as Default for options without one, and `--help` without `-h`.** Both come from `option_cells` in `src/dograpper/commands/docs.py`, which shares `dograpper docs` behaviour under click 8.3. ✅ **fixed:** `fix(docs): show none for an option without a default` (dec4df6) and `fix(docs): list the -h alias of --help`.
- **The guide sections "More on ..." partly restate the README text above them.** `site/guides/notebooklm.md` and `site/guides/incremental.md`. ⏸ **accepted: tightening the prose is stage 2; fix at the cutover.**
- **The relative-link check in `tests/test_docs_site.py` can hide a link after a stray backtick.**
  `_relative_links` strips code spans with `` `[^`]*` ``, which pairs across lines
  and ignores CommonMark backtick runs. `CHANGELOG.md` has an odd number of
  backticks (1119), so from the stray one onward the pairing shifts, and a
  relative link placed after it could be stripped instead of checked.
  Nothing is hidden today: `CHANGELOG.md` and `docs/schema-v1.md` have no
  relative links. ⏸ **accepted: the local `-W` build still fails on such a
  link (`myst.xref_missing`); trigger: a relative link reaching the local build
  without failing the test, or a switch to CommonMark-correct backtick-run
  matching.**

## Doxygen topic pages and the source browser (#187, #189, 2026-11-25)

- **Under `SOURCE_BROWSER = YES` a topic page whose members have only a brief description is split, though the plain build keeps it whole.** The source browser's "Definition at line ..." gives every member a documentation section (`docs/discovery/doxygen-api-records-acceptance.md`, "Follow-ups"), and a topic page with member sections is split (`_kind` in `src/dograpper/utils/api_reference/doxygen.py`); the line itself is dropped (#189), so the records are right, but the page splits in one build and not in the other. ⏸ **accepted: no measured corpus has the source browser on and a brief-only group; fix when one does, by not counting a section that holds only source-browser lines.**
- **A topic page whose title ends in "Reference" (`@defgroup core Core API Reference`) is read as a page kind and kept whole as unsupported markup (`page kind API`).** `_kind` tests the " Reference" suffix before it looks for a topic page. ⏸ **accepted: no measured corpus has such a title, and the page is kept whole, not mis-split; fix when one does, by telling a topic page apart by its `g` member anchors before the suffix.**

## Doxygen API records (#168, 2026-11-20)

- **The pack helpers of the API-reference tests are copied in four files.** `_cwd`, `_pack`, `_corpus` and `_jsonl` in `tests/test_api_reference_doxygen.py` repeat those of `tests/test_api_reference.py`, `tests/test_api_reference_rustdoc.py` and `tests/test_api_reference_typedoc.py`; the Doxygen copy points at the first. ⏸ **accepted: the other three files belonged to other lanes of the wave; fix in one test refactor that moves them to a shared module, or when a fifth adapter would copy them again.**
- **`sphinx.py` and `typedoc.py` still carry their own copy of the text tap (`_tap`).** `Regions.copy_until_end()` in `utils/api_reference/_html.py` is the shared form, used by `doxygen.py` only. ⏸ **accepted: both files were outside the lane's zone; fix in a refactor that moves both to `copy_until_end()`, before any new adapter needs the tap.**

## rustdoc API records (#75, 2026-11-19)

- **A trait implementation member with its own doc comment is dropped.**
  `utils/api_reference/rustdoc.py` keeps only the `impl` headers of trait
  implementations; a documented `fmt` or `size_hint` of one type is lost with
  the members that repeat the trait's docs. ⏸ **accepted: rustdoc marks both
  kinds the same way, and none of the 22 lookups on `itertools` needed one;
  fix when a lookup misses a member documented only in a trait
  implementation.**
- **The container bound (≤ 5,000 words) is measured, not enforced.** The
  `impl` header lists have no cap; `itertools::structs::Zip` is 1,604 words,
  mostly headers. ⏸ **accepted: the largest container on the acceptance
  corpus is 2,545 words; fix when a measured corpus (e.g. the standard
  library) has a container over the bound.**

## Harness hooks (#35, 2026-11-18)

- **The contract file set lives in two places.** The `case` map of
  `.claude/hooks/harness-reminder.sh` and the regex of
  `.claude/hooks/commit-doc-check.sh` list the same files; each points at the
  other. ⏸ **accepted: two copies of a short list, pinned by
  `tests/test_claude_hooks.py`; extract a shared list file at the third
  consumer.**
- **A bare `git push` is checked against the session cwd.**
  `.claude/hooks/block-dangerous-git.py` reads the branch of the payload's
  `cwd` (plus any `git -C`), not of a `cd DIR &&` before the push, so a bare push from a worktree
  whose session sits on `main` is blocked by mistake. ⏸ **accepted: the
  message says to give the refspec, and agents here push with an explicit
  branch; fix if it blocks a real flow.**

## fire-engine body-size cap (ADR-0011, 2026-11-18)

- **The body cap is enforced in the consumer loop, not at curl's writer.**
  `src/dograpper/lib/fire_engine/fetcher.py` streams with `iter_content` and
  raises once `total > MAX_BODY_BYTES`, but curl_cffi can decode and buffer
  bytes ahead of the bandwidth-throttled drain, so peak allocation from a
  decompression bomb can pass the cap before the check fires. ~~⏸ accepted: the
  consumer cap bounds the non-adversarial case, and the correct producer-side
  bound — disable curl's auto-decode and route the raw stream through
  `httrack.fetcher._decode` (already bounded), or a WRITEFUNCTION that aborts
  past the cap — must be verified against the real curl_cffi, which slice 1 does
  not install; fix it in the curl_cffi smoke-test slice.~~ ✅ **fixed (#130):
  both. curl's decoding is off (`HTTP_CONTENT_DECODING` 0), its writer
  (`content_callback`) aborts the transfer past `MAX_BODY_BYTES` and paces the
  bandwidth, and `Fetcher.get` decodes the raw body with `_decode`. Measured on
  curl_cffi 0.17.0 with a 1 GiB bomb: peak RSS over baseline went from ~1030 MiB
  (gzip, br, zstd) to 71-130 MiB, the same as the stdlib path.**

## fire-engine silence timeout (#154, 2026-11-19)

- **After data has arrived, fire-engine can wait about nine seconds past
  `--timeout` before giving up on a silent server.** libcurl's low-speed check
  (`LOW_SPEED_LIMIT`/`LOW_SPEED_TIME`, `src/dograpper/lib/fire_engine/fetcher.py`)
  averages the rate over its last few one-second records, so the rate only drops
  to zero once they have all rolled past the last byte. Measured on curl_cffi
  0.17.0 (libcurl 8.23.0), a byte at 0.1 s then silence: aborted at 8-9 s with
  `--timeout 1` and 13-14 s with `--timeout 5`; the stdlib path aborts at 1.1 s.
  ⏸ **accepted: it only delays giving up on a stalled server, never aborts a
  live one, and libcurl has no per-receive idle timeout; an exact one needs a
  progress callback (`XFERINFOFUNCTION`), which curl_cffi does not expose. Fix
  when curl_cffi exposes it, or when a real crawl is slowed by servers that
  stall mid-body.**

## `commands/pack.py` size budget (#139, #163, 2026-11-20)

- **`commands/pack.py` is 869 lines, above the 800-line budget of the size
  sentinel** (868 before the `--quiet` and redirect-stub work; the stub stage
  now costs one call to `commands/_skip_pages.py`).
  ⏸ **accepted: the file was already over budget and the new code is a call.
  Extract the later stages (dedup, scoring, summary) into their own modules
  when the next stage lands in `pack.py`.**

## `commands/pack.py` size budget, page-layout stub links (#174, 2026-11-24)

- **`commands/pack.py` is 870 lines, above the 800-line budget** (869 before
  #174, which only passes `stub_paths` to the page layout; the logic lives in
  `lib/page_layout.py`).
  ⏸ **accepted: same reason and same trigger as the #139/#163 entry above:
  extract the later stages (dedup, scoring, summary) when the next stage lands
  in `pack.py`.**
- **A meta-refresh target with a space inside its quotes is cut at the first
  space** (`_REFRESH_URL` in `utils/redirect_stub.py`, from #163): the link is
  left as written, or points at another page when the prefix happens to match one.
  ⏸ **accepted: rare in generated stubs (rustdoc, MediaWiki write none). Fix
  (quote-aware capture) when a mirror with such a stub shows up.**

## httrack browser pass, in-memory stores (#160, #167, 2026-11-20)

- **The engine's response store also keeps non-HTML bodies.** `RunResponses.keep` (`src/dograpper/lib/httrack/crawl.py`) stores every 2xx body, so images, PDFs or stylesheets of a seeded list can fill the 128 MiB cap before the pages the browser pass needs. ⏸ **accepted: the pages of a documentation site are small and a non-HTML answer is reused too (saved as fetched); fix by keeping only `text/html` when a run is seen to hit the cap, or when memory use of a real crawl matters.**
- **The subresource cache is keyed by URL alone.** `Navigator._response`/`_route` (`src/dograpper/lib/httrack/browser.py`) ignore `Vary` and `Range`, so a GET 200 whose answer depends on a request header (or a dynamic XHR) is replayed to every later page of the run. ⏸ **accepted: the issue defines a per-run cache keyed by URL, and only GET 200 without `no-store` is kept; fix when a crawled site is seen to render differently because of a replayed answer (key by URL plus the `Vary` headers then).**
- **The engine's responses sit in memory up to 128 MiB during the engine fetch even when no browser pass follows.** `run_profile` (`src/dograpper/commands/_httrack_profile.py`) creates the store before it knows whether the result looks client-rendered. ⏸ **accepted: the cap bounds it and it is released after the run; fix by keeping only when `is_spa` is likely, or when the peak memory of a large crawl is a problem.**

## rustdoc nightly (#162, 2026-11-20)

- **The nightly lock is one exact build, so every new nightly needs a code, fixture, ADR and DECISIONS change.** `MEASURED_VERSIONS` in `src/dograpper/utils/api_reference/rustdoc.py` pins `1.102.0-nightly (6905905bb `. ⏸ **accepted: ADR-0009 and the maintainer accept only measured builds; fix (a measured range, or a refresh script) when a user mirrors docs.rs and reports pages kept whole.**
- **The nightly fixture is one struct and exercises only the notable-trait tooltip difference.** `tests/fixtures/rustdoc/nightly/`. ⏸ **accepted: the rest of the nightly markup is covered by the acceptance measurement, not a test; fix when a nightly markup change slips past the measured build.**
- **`span.tooltip` is skipped in every section, not only in signatures.** `rustdoc.py` skip rule. ⏸ **accepted: the `a.tooltip` rule was already section-wide and no measured page has another tooltip span; fix if a split record loses text to a tooltip span.**
