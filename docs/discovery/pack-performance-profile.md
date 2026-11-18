# Pack and download performance profile (#21, #24)

> Discovery, 2026-11-18. Question: where does the time of `pack` and
> `download --downloader httrack` go, and would a content-addressed extraction
> cache (#21) or a deterministic worker pool (#24) pay off? Measured at
> `eccb532` (dograpper 0.4.0) on three local mirrors. No production code was
> changed. The prototypes below were throwaway scripts outside the repository.

## Verdict

- **#21, content-addressed extraction cache: no-go as proposed. Go, but
  narrower: extract each page once per run.**
  - HTML parsing for extraction is 81-98% of pack time, so a cache would
    work.
  - But `pack` extracts every page 2 or 3 times in one run. Reusing the first
    result inside the run, with nothing persisted, cut wall time by 33-46%
    on the default pack and by about half on
    `--format jsonl --context-header --score`. The output was byte-identical.
  - A persistent cache would only save the seconds left after that change. It
    also brings key and invalidation hazards (below) that reuse within one
    run does not have.
- **#24, worker pool: no-go for the crawl. Go, but narrower: a process pool
  for page extraction in `pack`, after the change above.**
  - The httrack profile already fetches with a thread pool. Its wall time is
    set by the pacing policy: 200 s for a crawl that needs 9 s of CPU.
  - Extraction is CPU-bound pure Python, so threads cannot speed it up.
  - A process pool over the extraction step made the default pack 7.9-8.3x
    faster on pzwiki and javadoc (8-16 workers), with byte-identical output.
    On scriptsdocs it was only 2.1x faster: one 10 MB page is 70% of that
    corpus's extraction work and cannot be split.

## Method

**Machine.** Intel Core i7-14650HX, 24 logical CPUs (`nproc`), WSL2 (Linux
6.18). CPython 3.13.7 from the project's uv venv, after `uv sync --extra dev
--extra headless --extra httrack`. CPython 3.10.18, the CI minimum, was used
as a cross-check.

**Timing.**

- Each run is a fresh process. It calls the click command in-process and
  records `time.process_time()` (CPU) and `time.perf_counter()` (wall) around
  it, plus the 1-minute load average.
- Unprofiled runs were repeated 2 or 3 times. The tables give every value or
  the minimum and median.
- Stage shares come from one separate `cProfile` run per configuration. The
  profiler slows this code down about 3.5x (pzwiki default: 34 s profiled,
  9.9 s not), so profiled seconds are used only as shares.
- Per-page costs were timed outside `pack`, on the same file selection, best
  of 2.

**Noise.** Other agents were running test suites during most measurements.

- The load average was 2.5-7.5 for the CPU table and 1.4-3.3 for the pool
  table.
- Under load, CPU time goes up too, not only wall time. The same Python 3.10
  pzwiki pack took 19.2 s of CPU at load 5.4 and 11.3 s at load 0.1. The
  default packs in the pool table ran on a quieter machine, and their CPU
  time is 13-25% below the CPU table's.
- Within one table, repeats differed by 1-15%. Compare numbers within a
  table, not across tables.
- On this WSL2 kernel, `process_time()` is 4-10% above wall time even for a
  single-threaded loop.
- The pool speedups are wall-clock ratios measured while other processes
  used some of the CPUs, so they are lower bounds.
- No conclusion below depends on a difference smaller than 1.4x.

**Configurations.** Each mirror was packed with its `.docsignore` from the
reference build that consumes these packs, so the file selection matches real
use:

| Name | Flags |
|---|---|
| default | none (md, chunk layout) |
| jsonl-ctx-score | `--format jsonl --context-header --score` |
| dedup-both | `--dedup both` |
| page | `--layout page` |
| api | `--format jsonl --api-records` |
| noextract | `--no-extract` |
| build | the reference build's flags: `--no-index --max-words-per-chunk 1 --max-chunks 100000`, plus `--dedup exact` (pzwiki) or `--no-extract` (javadoc) |

## Corpora

| Corpus | Generator | Pages packed | Raw HTML | Largest page | md text written |
|---|---|---|---|---|---|
| pzwiki | MediaWiki | 146 | 15.1 MB | 0.9 MB (6% of the corpus) | 1.10 MB |
| javadoc | Javadoc 25 | 1,689 | 92.8 MB | 3.1 MB (3%) | 11.2 MB |
| scriptsdocs | Sphinx | 134 | 19.1 MB | 10.1 MB (53%) | 3.22 MB |

## Where pack time goes

CPU seconds, minimum / median of 3 unprofiled runs:

| Configuration | pzwiki | scriptsdocs | javadoc |
|---|---|---|---|
| default | 9.85 / 9.96 | 19.82 / 20.71 | 52.11 / 52.73 |
| jsonl-ctx-score | 17.84 / 17.88 | 29.54 / 33.64 | 82.12 / 83.37 |
| dedup-both | 6.15 / 6.29 | 15.88 / 15.89 | 58.31 / 59.40 |
| page | 10.14 / 10.18 | 18.34 / 18.82 | 49.88 / 50.00 |
| api | - | 16.50 / 17.39 (no page split) | 8.62 / 9.53 (1,531 pages split) |
| noextract | - | - | 20.40 / 20.42 |
| build | 5.24 / 5.57 | 18.29 / 19.39 | 19.83 / 20.00 |
| load average | 3.9-6.1 | 4.1-7.5 | 2.5-4.6 |

Repeated runs of a configuration always wrote the same files (same SHA-256
over the output tree).

Share of profiled pack time per primitive, summed over all callers.
MediaWiki cleaning runs inside `extract_content` and is counted in both
columns:

| Profile | `extract_content` calls per page | `extract_content` | MediaWiki clean | `strip_html` | headings | `page_metadata` | `split_api_pages` | `deduplicate` | html.parser, all |
|---|---|---|---|---|---|---|---|---|---|
| pzwiki default | 2.0 | 92% | 54% | 8% | - | - | - | - | 98% |
| pzwiki jsonl-ctx-score | 3.0 | 78% | 46% | 11% | 2% | 9% | - | - | 97% |
| pzwiki dedup-both | 1.0 | 80% | 46% | 8% | - | - | 0% | 11% | 87% |
| pzwiki page | 2.0 | 91% | 54% | 8% | - | - | - | - | 98% |
| pzwiki build | 1.0 | 89% | 52% | 10% | - | - | 0% | 1% | 97% |
| scriptsdocs default | 2.0 | 66% | 0% | 34% | - | - | - | - | 98% |
| scriptsdocs jsonl-ctx-score | 3.0 | 65% | 0% | 26% | 9% | 0% | - | - | 95% |
| scriptsdocs dedup-both | 1.0 | 48% | 0% | 32% | - | - | 3% | 17% | 81% |
| scriptsdocs page | 2.0 | 65% | 0% | 35% | - | - | - | - | 97% |
| scriptsdocs api | 2.0 | 70% | 0% | 28% | - | - | 2% | - | 96% |
| scriptsdocs build | 2.0 | 64% | 0% | 36% | - | - | - | - | 98% |
| javadoc default | 2.0 | 67% | 0% | 33% | - | - | - | - | 96% |
| javadoc jsonl-ctx-score | 3.0 | 63% | 0% | 27% | 9% | 0% | - | - | 94% |
| javadoc dedup-both | 1.9 | 57% | 0% | 28% | - | - | 15% | 0% | 96% |
| javadoc page | 2.0 | 67% | 0% | 32% | - | - | - | - | 95% |
| javadoc api | 0.2 | 4% | 0% | 1% | - | - | 92% | - | 95% |
| javadoc noextract | 0.0 | - | - | 99% | - | - | - | - | 89% |
| javadoc build | 0.0 | - | - | 99% | - | - | - | - | 89% |

### F1. Extraction is the pack

- Pure-Python `html.parser` passes take 94-98% of the profiled time in every
  configuration except two groups. With dedup they take 81-97%, because the
  dedup itself takes up to 17%. With `--no-extract` they take 89%.
- Everything else in a default pack takes 0.07-0.23 s of wall time. That
  includes walking and filtering, chunking, writing, sidecars and the
  summary. It was measured with every extraction answered from memory
  (prototype below).
- Listing and filtering the 1,948 javadoc files took 0.02 s. Detecting
  bot-challenge pages took 0.11 s, and detecting MediaWiki redirect aliases
  0.05 s.
- One extraction pass is `extract_content` plus the md `strip_html`. It costs
  0.35-0.56 µs per input byte, linear in page size.

### F2. Every page is extracted 2 or 3 times per run

Each stage re-reads and re-extracts the source page instead of reusing the
text that the previous stage produced:

| Configuration | Work per page | Callers |
|---|---|---|
| default, page, scriptsdocs build | 2 `extract_content`, 2 `strip_html` (plain, md) | word count for chunk sizing (`count_words_file`), then the writer (`read_source_text`) |
| jsonl-ctx-score | 3 `extract_content`, 3 plain `strip_html` (one of them over the raw page), 1 heading parse | word count; heading stage in `commands/pack.py`; scorer (`pack_scoring._read_page`), which also strips the raw page for its "before extraction" count |
| dedup-both, pzwiki build (`--dedup exact`) | 1 `extract_content`, 1 `strip_html` | dedup reads each page once and gives its text and word count to the chunker and the writer |
| api, split pages | one pass of the adapter's own reader | `utils/api_reference/_html.py` |

- That is why `--dedup both` is faster than the default on pzwiki (6.2 s
  against 9.9 s of CPU): it does more work per page, but it extracts each
  page once.
- On MediaWiki pages, `--context-header` and `--score` also call
  `page_metadata`, which repeats the cleaning scan (`mediawiki._Scan`). With
  jsonl-ctx-score that makes 4 scans per page.
- `--api-records` on javadoc is the fastest configuration (8.6 s against
  52.1 s), because it parses each split page once.

### F3. MediaWiki cleaning is 63% of pzwiki extraction

`mediawiki.clean` makes two full parses of its own: `_Scan`, then
`_drop_empty_headings`. The generic extractor then makes two more (semantic
container, then blacklist removal). On pzwiki, `clean` takes 3.0 s of one
4.8 s pass of `extract_content`.

### F4. The page layout is not 40x slower

A previous session saw `--layout page` on pzwiki run about 40 times slower
than the default pack. At `eccb532` that no longer happens:

- CPython 3.13.7: 10.1 s against 9.9 s of CPU.
- CPython 3.10.18: 11.3-12.8 s against 11.3-11.6 s on a quiet machine.

The page layout does the same two extraction passes as the default (F2). Its
own work (titles, link rewriting, swapping in `pages/`) is under 1% of the
profile. The acceptance run of the same day also measured at most 1.23x
(`docs/discovery/claude-code-target-acceptance.md`). On pzwiki, both Python
versions wrote byte-identical packs.

### F5. Download time is set by the pacing policy

The scriptsdocs mirror was served by `python -m http.server --bind
127.0.0.1` and crawled recursively from its start URL (137 pages, 18.3 MB):

| Policy | Connections | Wall s | CPU s |
|---|---|---|---|
| default (100 KB/s, 5 connections/s) | 4 | 200.2 | 9.1 |
| limits lifted | 1 | 9.08, 9.14 | 9.58, 9.56 |
| limits lifted | 4 | 8.62 | 9.15 |
| limits lifted | 8 | 8.09, 8.34 | 8.61, 8.94 |

- Under the default policy, the floor is 18.3 MB / 100 KB/s = 183 s. CPU time
  is 4.6% of the wall time, and it runs while the other threads wait on the
  pacing.
- With the limits lifted, the crawl is CPU-bound: CPU time is close to wall
  time. Going from 1 to 8 threads saves 10% of wall time, because the GIL
  serialises the work.
- All seven runs wrote byte-identical files.
- Where the crawl's CPU goes (cProfile, 1 connection, limits lifted): link
  extraction during the crawl 21%, the final `-K0` relink pass 32%, the SPA
  check over every saved page after the crawl 31%, fetching and decoding 8%.

## #21: content-addressed extraction cache

The issue lists three assumptions:

1. **Extraction is expensive enough to pay for a cache.** True: 81-98% of
   pack time (F1).
2. **Normalization edge cases do not corrupt the cache.** False with a key
   made of the content hash alone. A correct key needs all of these:
   - **The file name.** The md writer drops a link to the page itself
     (`page.html#x` is how mirrors rewrite in-page anchors). So the same bytes
     under another name give another text. Rendering each page again under a
     different name changed the md output of 134 of 134 Sphinx pages and of
     10 of 73 sampled Javadoc pages. It changed none of the 166 pzwiki pages.
   - **The output variant.** The text differs between md and plain output,
     with and without `--no-extract`, and for the plain heading parser. The
     scorer also strips the raw page.
   - **A hash of the extraction code, not the version.** 15 commits changed
     the extraction modules (`content_extractor`, `html_stripper`,
     `mediawiki`, `heading_extractor`, `code_fence`) after the version became
     0.4.0 on 2026-08-15. A key with the version would have served stale text
     through all of them.
   - **The Python version.** The extractor is `html.parser`, which changed
     in CPython's 2025 patch releases. No difference was observed here: on
     pzwiki, 3.10.18 and 3.13.7 wrote byte-identical packs. The key still
     cannot assume there is none.
   - Some steps depend on other pages or on the relative path: dedup,
     page-layout link rewriting, cross-refs and API record URLs. They would
     have to stay downstream of the cache.
3. **The cache size is manageable.** True.
   - The md text is 7-17% of the raw HTML (1.1, 11.2 and 3.2 MB here), and
     the plain text is 4-11%.
   - Hashing the raw bytes with SHA-256 takes 0.06 s for the 93 MB of
     javadoc, 0.1-0.2% of one extraction pass.

**What a cache could save.** The default pack, wall seconds on a quieter
machine (load 1.4-3.3). "Perfect cache" is the rest of the pack with every
extraction answered from memory. It is the most any cache can achieve, before
the cost of hashing and reading the entries.

| Corpus | Unmodified | Extract once | Extract once + 8-process pool | Perfect cache |
|---|---|---|---|---|
| pzwiki | 7.68, 7.69 | 4.13-4.37 | 0.93-1.06 | 0.08 |
| scriptsdocs | 13.14, 14.28 | 8.77-9.31 | 6.26-6.52 | 0.07 |
| javadoc | 39.33, 39.88 | 25.57, 26.00 | 5.58-5.78 | 0.21-0.23 |

With jsonl-ctx-score, extracting once took pzwiki from 11.9 s to 5.6 s and
javadoc from 61.2 s to 31.3 s, with byte-identical output.

**When a cache would be used.**

- `--delta` already skips a re-pack of an unchanged corpus (ADR-0008).
- A cache pays off only for pages that did not change, in three cases: a
  re-pack after a partial change, a re-pack with different non-extraction
  flags, and projects that share pages.
- The reference build re-packs all three corpora from scratch. Its three
  packs take about 43 s of CPU in total (build row, under load).

**Recommendation: no-go as proposed. Go, narrower.**

- Compute each page's text once per run and give it to every stage, the way
  the dedup path already does (F2). This needs no key, no invalidation and no
  storage. It removes a third to a half of the pack's wall time.
- Caveat: the dedup path counts words in the md text, and the default path
  counts them in the plain text. These counts differ on 4 of 1,969 pages (3
  pzwiki, 1 javadoc), and the count decides chunk boundaries. The prototype
  shared only the `extract_content` result and kept both strips, so its
  output stayed byte-identical.
- Revisit the persistent cache only if both of these hold:
  - the extract-once change and the pool below are in;
  - large, mostly unchanged corpora are re-packed often enough that the
    remaining seconds matter.
- If that happens, the key is: SHA-256 of the raw bytes, file name, output
  variant, hash of the extraction source, Python version. A corrupt entry
  must fail the run, not be recomputed silently.

## #24: deterministic worker pool

**Crawl: no-go.**

- Both httrack paths already fetch with a `ThreadPoolExecutor` sized by
  `--connections`.
- The recursive crawl handles responses in queue order, and it wrote
  byte-identical files with 1, 4 and 8 connections (F5). The seeded fetch
  was not measured.
- wget is an external process with its own pacing.
- Under the default policy, the crawl waits on pacing, not on CPU (F5).
  Raising `--connections` does not lift the bandwidth cap, and the pacing
  policy is a fixed constraint.
- The CPU tail after the crawl (relink and SPA check) is about 6 s here,
  estimated from the profile shares. That is 3% of the default-policy wall
  time.

**Extraction: go, narrower.** The extraction work is CPU-bound pure Python,
so only separate processes can run it in parallel.

How the throwaway prototype worked:

- Before `pack` ran, a `ProcessPoolExecutor` computed `extract_content` and
  both `strip_html` variants for every page. It used the fork start method
  and handed out the largest pages first.
- `pack` then ran unchanged, and those functions returned the precomputed
  results.
- "Extract once" is the same run without the pool: each result is computed
  once, serially, the first time a stage asks for it.

The default configuration, wall seconds (load 1.4-3.3):

| Corpus | Unmodified | Extract once | Pool, 1 process | 4 | 8 | 16 | Rest of pack |
|---|---|---|---|---|---|---|---|
| pzwiki | 7.68, 7.69 | 4.13-4.37 | 4.23, 4.30 | 1.31-1.36 | 0.93-1.06 | 1.07, 1.08 | 0.08 |
| scriptsdocs | 13.14, 14.28 | 8.77-9.31 | 9.51, 9.94 | 6.34-6.92 | 6.26-6.52 | 6.66, 6.80 | 0.07 |
| javadoc | 39.33, 39.88 | 25.57, 26.00 | - | 8.36, 8.43 | 5.58-5.78 | 4.99, 5.03 | 0.21-0.23 |

- **Same output.** Every run wrote a pack whose SHA-256 over all output files
  equals the unmodified pack's. An ordered `map` keeps the output
  deterministic without any extra sorting.
- **Speedup against the unmodified pack:** pzwiki 8.3x at 8 processes,
  javadoc 7.9x at 16, scriptsdocs 2.1x at 8. Against the extract-once run,
  the pool's own share is 4.5x, 5.1x and 1.4x.
- **The cap is the largest page.** With perfect scheduling, the largest page
  alone limits the extraction step to 1.4x on scriptsdocs (one page is 70% of
  the work), 10.6x on pzwiki at 16 workers, and 16x on javadoc. The measured
  values follow these limits.
- **Overhead.** Forking and pickling cost 0.1-0.7 s (pool of 1 against
  extract once).
- More than 8 processes gave little. Children's CPU time grew from 34 s at 4
  processes to 84 s at 16 for the same javadoc work. The likely cause is
  shared physical cores (2 threads per core).

A real implementation also has costs the prototype did not cover:

- The standalone binary (`dograpper.spec`, PyInstaller) needs
  `multiprocessing.freeze_support()` in its entry point. Without it, worker
  processes run the CLI again.
- macOS and Windows use the spawn start method. Each worker imports
  dograpper again (0.1 s here) and receives its pages by pickling.
- A failure must stay confined to its page and keep the policy each stage has
  today: `count_words_file` returns 0 on any exception, and the writer logs
  the error and writes a placeholder. Logging from workers must reach the
  parent.
- The parent holds every page's text, as the dedup path already does: 11 MB
  of md for javadoc.
- A worker count is a new flag or config key, so it needs a CHANGELOG entry.
  Its default must not oversubscribe CI runners.

Make the extract-once change first. Without it, the pool would run
duplicated work in parallel. It also halves the work on every machine,
including single-core runners.

## Other hotspots

Described here, not filed:

1. **Redundant extraction passes** (F2). This is the narrower form of #21
   above, and the change with the best return. The jsonl-ctx-score path also
   strips each raw page once only to count its words for `noise_ratio`.
2. **Repeated MediaWiki parses** (F3). Cleaning parses each page twice more,
   and `page_metadata` repeats the `_Scan` that `clean` already ran.
   Returning the banner and categories from the scan done for cleaning would
   remove one full parse per page in jsonl-ctx-score on MediaWiki.
3. **`--dedup` on Javadoc costs more than it gives.** Every Javadoc page is
   exempt from dedup (#68), but the flag still runs API-page detection over
   every page (15% of the profiled run). The exempt pages then take the
   two-pass path, and the output equals the default pack's (same SHA-256).
4. **The download's post-crawl tail** (F5). The relink pass and the SPA check
   each parse every saved page again: about 63% of the crawl's CPU. This
   matters only with the limits lifted.

## Reproduction

The scripts are not in the repository. The commands below rebuild them. `$W`
is the worktree, `$M` the mirrors, `$IG` the `.docsignore` files.

```bash
uv sync --extra dev --extra headless --extra httrack
# One timed pack (CPU, wall, load average) in a fresh process: a wrapper that
# calls dograpper.cli.cli.main(["-q", "pack", ...], standalone_mode=False)
# between process_time()/perf_counter() reads, optionally under cProfile.
$W/.venv/bin/python -I prof.py [--profile out.prof] -- \
  $M/pzwiki -o out/pzwiki-default --ignore-file $IG/wiki.docsignore
# Stage shares: pstats over out.prof, the cumulative time of each callee of
# commands/pack.py:pack and of extract_content / strip_html / mediawiki.clean,
# split by caller.
# Per-page costs: pack's selection (os.walk, split_by_extension, filter_files,
# find_challenge_files, find_redirect_aliases), then process_time() around
# each primitive, best of 2.
# Same output: find OUT -type f -print0 | sort -z | xargs -0 sha256sum | sha256sum
# Local crawl:
python3 -I -m http.server --bind 127.0.0.1 18731 \
  --directory $M/scriptsdocs/pz-wiki-modding.github.io
dograpper download http://127.0.0.1:18731/PZ-API-Docs/ -o out --downloader httrack \
  [--disable-security-limits --connections N --max-conn-rate 10000 --max-bandwidth 1000000000]
```

The pool prototype replaces `extract_content` and `strip_html` in
`utils/content_extractor`, `utils/html_stripper`, `lib/chunker`,
`utils/word_counter` and `lib/pack_scoring` with lookups in a dict. The dict
is keyed by the input text, plus `markdown` and the file name for
`strip_html`. Before `pack` runs, `ProcessPoolExecutor.map` fills it over the
HTML files, largest first.
