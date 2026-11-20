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

- **`commands/pack.py` is 884 lines, above the 800-line budget of the size
  sentinel.** The `--quiet` helper swap (#139) and the redirect-stub step 6a-3
  (#163) added to a file that was already at 868. The skip steps 6a to 6a-3
  repeat one block (find, warn with the listing, filter, fail when empty).
  ⏸ **accepted: moving the four steps into one module is a refactor of
  stages that other lanes' tests pin. Extract them when the next skip stage
  (a fifth) is added, or when `pack.py` crosses 900 lines.**

## httrack browser pass, in-memory stores (#160, #167, 2026-11-20)

- **The engine's response store also keeps non-HTML bodies.** `RunResponses.keep` (`src/dograpper/lib/httrack/crawl.py`) stores every 2xx body, so images, PDFs or stylesheets of a seeded list can fill the 128 MiB cap before the pages the browser pass needs. ⏸ **accepted: the pages of a documentation site are small and a non-HTML answer is reused too (saved as fetched); fix by keeping only `text/html` when a run is seen to hit the cap, or when memory use of a real crawl matters.**
- **The subresource cache is keyed by URL alone.** `Navigator._response`/`_route` (`src/dograpper/lib/httrack/browser.py`) ignore `Vary` and `Range`, so a GET 200 whose answer depends on a request header (or a dynamic XHR) is replayed to every later page of the run. ⏸ **accepted: the issue defines a per-run cache keyed by URL, and only GET 200 without `no-store` is kept; fix when a crawled site is seen to render differently because of a replayed answer (key by URL plus the `Vary` headers then).**
- **The engine's responses sit in memory up to 128 MiB during the engine fetch even when no browser pass follows.** `run_profile` (`src/dograpper/commands/_httrack_profile.py`) creates the store before it knows whether the result looks client-rendered. ⏸ **accepted: the cap bounds it and it is released after the run; fix by keeping only when `is_spa` is likely, or when the peak memory of a large crawl is a problem.**
