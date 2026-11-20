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

## 2026-11-20 — rustdoc accepts one measured nightly build (#162)

- **Decision:** `MEASURED_VERSIONS` accepts `1.96.` and the exact prefix
  `1.102.0-nightly (6905905bb `; the notable-trait mark is dropped as
  `span.tooltip` as well as `a.tooltip`.
- **Why:** the nightly passed the ADR-0009 bar on itertools 0.14.0 (see the
  acceptance doc); the issue says to accept only measured prefixes, and a
  nightly's markup moves daily.
- **Rejected:** `1.102.` or any `-nightly` (unmeasured builds).
- **Pending:** docs.rs builds change daily, so most docs.rs pages stay
  whole; widening again means measuring another build.

## 2026-11-20 — browser lane (feat/httrack-browser-pass)

- #166: a launch error is matched on "Executable doesn't exist" in its first line; the
  install hint is only for that case (maintainer decision), any other keeps Playwright's line.
- #159: a meta refresh is read from the rendered DOM by the same `evaluate` that reads
  `a[href]`; a seeded run still follows links of its seeds (as before), it only opens no start URL.
- #167: the subresource cache is capped at 64 MiB, keyed by URL (no `Vary`, no `Range`),
  replays without `set-cookie`; a body that cannot be read is a cache miss (debug log).
- #160: the cap of the engine's response store is 128 MiB; it keeps every 2xx body (non-HTML too);
  a start URL that redirected is fetched again, since only a fetch re-bases the scope.
  `run_profile` (owner: `fire`) gained the sink creation and the `responses=` argument.

## 2026-11-20 — `--quiet` and `pack --report` / the stub scan window (#139, #163)

- **Decision:** `pack --report` under `-q` loses its terminal summary (the report
  file is still written); it goes through `say()` like the other summaries. Only
  `--dry-run` is kept as "output that is the purpose of a flag". The redirect-stub
  detector reads the first 16 KiB of a file, as the error-page one does: a larger
  page is not a stub.
- **Why:** the Agent Brief names `--dry-run` alone; a stub is a few hundred bytes.
- **Maintainer (2026-11-20):** keep it; recorded on #139.

## 2026-11-20 — `--user-agent` gets the `--header` value check (#136)

- **Decision:** a `--user-agent` value, from the command line or `.dograpper.json`, goes through the same CR/LF/NUL check as a `--header` line (`check_value()` in `utils/http_headers.py`): exit 2, naming the flag and never quoting the value. CHANGELOG lists it under Security.
- **Why:** the Agent Brief names the check for `--header` only, but both routes put the same header on the wire, and under fire-engine a line break in `--user-agent` put a header line of its own on the wire (found and measured by the branch's spec review). Guarding one route of two leaves the guard open.
- **Rejected:** checking `--header` only (the brief's letter); stripping the characters (a silent change of what the user asked for).
- **Pending:** none.

## 2026-11-20 — `--header` edge rules the Agent Brief left open (#136)

- **Decision:** three readings, all toward failing loud or keeping the user's word:
  - one name on two `--header` lines (compared without case, two `User-Agent:` lines included) is a usage error (exit 2), not a silent last-one-wins;
  - a User-Agent from `--user-agent` and one from `--header` are exit 2 whatever the level of each (command line or `.dograpper.json`): contract 6 orders the levels of one option, and these are two options that set one header;
  - under fire-engine, a `sec-ch-ua*` hint given with `--header` survives an explicit User-Agent, which drops only the profile's hints (the user's header is applied last).
- **Why:** the brief says "giving both is a usage error" without naming levels and says nothing about repeated names or user-given hints; the global "no silent fallback" rule and the research doc's "a user header always wins" (§6, the option the maintainer chose) decide them.
- **Rejected:** last line wins (silent); sending both lines as `curl -H` does (a second User-Agent confuses servers); a command-line `--header 'User-Agent'` beating a config `user-agent` (contract 6 stretched across two options); dropping user-given hints too.
- **Pending:** none; the maintainer can reverse any of the three in review.

## 2026-11-20 — Doxygen adapter: what a member record is (#168)

- **Decision:** a member Doxygen documents only by its brief description, which has no documentation section, gets a member record made of its summary row and brief (its anchor sits in that row, or in the row of its template header). Summary rows that link to a section are dropped as the ADR-0009 summary tables are.
- **Why:** the brief says the summary rows repeat the members "without their documentation", which holds only for members with a section. On libstdc++ 13 a third of the anchored members (1,143 of 1,741 on the first run) have no section; dropping their rows would drop the members.
- **Rejected:** keeping those members as names on the container only (a declared member with no record, unlike every other adapter).
- **Pending:** maintainer: confirm at PR review, since it departs from the brief's description of the summary rows.

- **Decision:** the qualified name is the page title's, Doxygen's spacing included (`std::vector< _Tp, _Alloc >`, `shapes::Box< T, N >::put`); a member of a file page is named alone (`ring_push`) with the file as `container`.
- **Why:** the title is the only place that names the symbol, and it keeps a specialization (`std::vector< bool, _Alloc >`) apart from its primary template; Doxygen's own signatures use the same form.
- **Rejected:** the `nav-path` breadcrumb (no template arguments, so a specialization and its template share a name); `ring.h::ring_push` (not a C name).
- **Pending:** none.

- **Decision:** a file page skips the brief-only members of the namespaces its "Namespaces" table lists, and keeps the others under their qualified name. A file page with no member record keeps one record.
- **Why:** Doxygen anchors such a member on both the file and the namespace page; the table lists only namespaces with a page. libstdc++'s `std` is undocumented and has no page, so its members exist only on the file pages. The brief makes a file page a container only when it documents members.
- **Rejected:** skipping every qualified member of a file page (lost libstdc++'s free operators and `swap` overloads on the first run).
- **Pending:** none.

- **Decision:** topic (group) pages, related pages and the main page keep one record, under the same reason as the listing pages ("Doxygen index, listing, source or topic page"). A page with two members under one anchor keeps one record.
- **Why:** the brief lists class, struct, union, namespace and file pages; a group page's title names no kind, so it cannot be told from a text page. Doxygen 1.9.8 gives overloads that differ only in template constraints one id (`std::optional`, `std::pair`), and two records must not share one.
- **Rejected:** splitting group pages without a measured rule for their kind; merging the records of a shared anchor.
- **Pending:** none.

- **Decision:** a friend or related symbol gets its symbol_kind from its declaration (`typedef`/`using`, `enum`, `#define`, a parameter list for a function, else a variable), named under the class that documents it (`shapes::Box< T, N >::operator!=`). A friend class (`friend class Peer`) gets no record; its name stays under `Friends`.
- **Why:** the review found a friend class and a `\relates` typedef or variable written as `function`. A friend class is a relation, documented on the class's own page.
- **Rejected:** keeping every friend a function; a friend class as a member record with symbol_kind `class` (a member kind the brief does not list).
- **Pending:** none.

- **Decision:** an enum with no name is named `anonymous enum`, as Doxygen titles its section; its summary row names its first enumerator.
- **Why:** the review found a brief-only anonymous enum named after its first enumerator; libstdc++ 13 has 13 such rows.
- **Rejected:** keeping the page whole (anonymous enums are common in C headers).
- **Pending:** none.

- **Decision:** `Regions.copy_until_end()` in `_html.py` is the shared form of the "second copy of the text" that `sphinx.py` and `typedoc.py` each implement as `_tap`; the Doxygen adapter is its first user. The two existing copies stay as they are.
- **Why:** the Doxygen adapter needed it (the name inside a summary row), which made it the third copy; the wave gave `sphinx.py` and `typedoc.py` to no lane, so this lane could not touch them.
- **Rejected:** a third private copy in `doxygen.py`.
- **Pending:** maintainer: move `sphinx.py` and `typedoc.py` to `copy_until_end()` in a follow-up refactor.

## 2026-11-20 — Docs site content copied

- **Decision:** supersedes "Docs site pages copied from the README". The README sections copied into `site/` have two copy points. `site/index.md` and `site/commands/pack.md` were copied at commit `97e4ccf` (README blob `16043b5`); every other page (the other commands, `reference/`, `install.md`, `quickstart.md`, `guides/`, `troubleshooting.md`) at commit `3799eda` (README blob `4eba1a4`). At cutover, `git diff 97e4ccf HEAD -- README.md` (the oldest point) lists what to carry over. Each guide also holds an English `## More on ...` section written from the matching Portuguese note in `docs/workflows/`; `docs/workflows/` is untouched, and its JSONL example, the only flag-bearing content, was checked against `schema-v1.md` and `--help`. The cutover diff from `97e4ccf` also re-lists the install and action hunks already copied at `3799eda`, and that is harmless.
- **Why:** the README stays untouched until the site replaces it, so the copies drift unless every copy point is recorded.
- **Rejected:** generating pages from the README at build time; translating what the README already says.
- **Pending:** none.

## 2026-11-20 — Docs site pages copied from the README

- **Decision:** each `site/commands/*.md` page is a verbatim copy of its README section (heading levels shifted, option tables replaced by the generated table, relative `docs/` links turned into GitHub URLs). The `pack` page was copied from `README.md` blob `16043b558b70fcbd396fb62ec60d1ceb122cd73a` at commit `97e4ccf`. At cutover, `git diff 97e4ccf HEAD -- README.md` lists what changed in the README since and has to be carried over to the pages.
- **Why:** the README stays untouched until the site replaces it, so the copies drift unless the copy point is recorded.
- **Rejected:** generating pages from the README at build time; re-reading the whole README at cutover.
- **Pending:** none.

## 2026-11-20 — Docs site renders options with its own directive, not sphinx-click

- **Decision:** `site/conf.py` registers a `dograpper-options` directive (argument: a command name, or `dograpper` for the root group) that builds a docutils table from the click tree with `option_cells` / `OPTION_COLUMNS` of `commands/docs.py`; `sphinx-click` is dropped from the `docs` extra.
- **Why:** sphinx-click 6.2.0 has no `:hide-header:`; under MyST its rST renders as literal text; the `{eval-rst}` fallback fails `-W` (a Duplicate ID with the page H1, and `docs_chunk_` parsed as an rST reference) and duplicates the title and docstring. The maintainer's model also asked for a table generated from click, and this one matches `dograpper docs`.
- **Rejected:** `{eval-rst}` plus sphinx-click event hooks; editing the `--prefix` help text.
- **Pending:** none.

## 2026-11-20 — Dated versions for the first release

- **Decision:** releases are versioned by date: `YYYY.M` for the release month
  (`2027.3`), `YYYY.M.N` for a further release in the same month, tagged
  `vYYYY.M`. Contract 10, the CHANGELOG header, `tests/test_changelog.py`
  (heading format and the version matching its date's month) and the release
  workflow's tag filter (`v*.*`, since `v2027.3` has a single dot) follow.
- **Why:** the maintainer chose month/year versions (2026-11-20). The month has
  no leading zero because Python packaging normalizes `2027.03` to `2027.3`, so
  `--version` would disagree with a `v2027.03` tag.
- **Rejected:** `YYYY.MM` with a leading zero, for the mismatch above. The
  old pre-1.0 semantic versioning rule.
- **Pending:** none.

## 2026-11-20 — Withdraw the published releases (#151)

- **Decision:** dograpper is treated as unreleased. The GitHub releases v0.4.0
  (deleted 2026-11-19) and v0.3.3 are gone, with the tags v0.3.0 to v0.4.0;
  every tagged commit is still on `main` and the tags were lightweight, so only
  the version markers and the v0.3.3 binary went away. The `[0.4.0]` CHANGELOG
  section is folded into `[Unreleased]`, each subsection appended after the
  unreleased entries of its type, and `pyproject.toml` says `0.0.0.dev0`.
  `v0.0.0-tooling` stays: `doctor --install` downloads busybox-wget from it.
- **Why:** the maintainer considers the project still in development, and the
  release binaries lagged far behind `main`.
- **Rejected:** keeping `version = "0.4.0"`, since `--version`, the httrack
  default User-Agent and the MCP `serverInfo` would name a release that no
  longer exists. A CHANGELOG entry for the version change: the changelog
  describes changes between releases and there is none, so the commit is a
  `chore`.
- **Pending:** none.

## 2026-11-19 — TypeDoc adapter: tests, corpus and version gate (#75)

- **Decision:** the TypeDoc tests live in their own file,
  `tests/test_api_reference_typedoc.py`, instead of growing
  `tests/test_api_reference.py`. The acceptance corpus was generated locally
  with TypeDoc from the npm sources of `@tanstack/query-core`, so no site was
  crawled. Pages without an `aria-current` crumb are kept whole, which
  rejects TypeDoc 0.25 to 0.27.
- **Why:** `tests/test_api_reference.py` already has 702 lines for two
  generators, and the structural audit flags test files over 1,000 lines. The
  brief preferred a local corpus. Without the gate, function and variable
  pages from 0.25 to 0.27 split under wrong qualified names
  (`fixture.shapes.apply`), while their class pages were kept whole.
- **Rejected:** appending to `tests/test_api_reference.py`; crawling a public
  TypeDoc site; supporting 0.25 to 0.27, which have no measured corpus.
- **Pending:** none.

## 2026-11-19 — rustdoc pages are split only from rustdoc 1.96 (#75)

- **Decision:** the rustdoc adapter reads `data-rustdoc-version` and keeps
  any page whose version is not 1.96.x as one record, with the version in
  the warning.
- **Why:** ADR-0009 says each adapter "supports only the markup versions that
  were measured", and rustdoc's markup changes between releases. Its
  structural checks catch a missing section or an unknown heading, but not a
  doc comment that moved, which would land in the wrong record silently.
- **Rejected:** structural checks only, as the Javadoc and Sphinx adapters
  do; a range of versions nobody measured.
- **Pending:** docs.rs builds with nightly rustdoc, so a docs.rs mirror keeps
  every page whole until a nightly corpus is measured and the accepted
  versions widen.

## 2026-11-19 — rustdoc adapter: corpus, test file, shared helpers (#75)

- **Decision:** the acceptance corpus is `itertools` 0.14.0 from the local
  Cargo registry, documented with `rustdoc` directly (its one dependency
  compiled to metadata first). The adapter's tests live in their own file,
  `tests/test_api_reference_rustdoc.py`. Before the third adapter, the
  helpers Javadoc and Sphinx both carried moved to shared places:
  `declared()` and `check_anchor()` to `utils/api_reference/__init__.py`,
  `line()` and `Regions.set_until_end()` to `_html.py`.
- **Why:** the `rust-docs` component is not installed, so the standard
  library's docs were not available offline. `cargo doc --offline` fails on
  dev-dependencies that are not in the registry, and running `rustdoc` on the
  crate needs no crawl and no build script. `test_api_reference.py` already
  has 702 lines and the TypeDoc lane adds to the same area in parallel. The
  repeated-anchor check guards unique record ids, so it is not copied a third
  time.
- **Rejected:** installing `rust-docs` (changes the machine's toolchain);
  crawling docs.rs (a public site when a local corpus exists); copying the
  helpers into `rustdoc.py`. The two-line `_unsupported()` message factory
  stays per adapter: it holds no logic.
- **Pending:** redirect stubs take top-5 slots in name lookups, and
  `Methods from Deref` sections keep a page whole
  ([case study](discovery/rustdoc-api-records-acceptance.md)).

## 2026-11-19 — fire-engine low-speed window is `--timeout` + 1 s (#154)

- **Decision:** the fix for the flaky
  `test_real_timeout_is_inactivity_like_the_stdlib_socket_timeout` goes in
  `lib/fire_engine/fetcher.py`, not in the test: `LOW_SPEED_TIME` is
  `ceil(--timeout) + 1`, and a second smoke test pins a 1.5 s silence passing
  `--timeout 2`.
- **Why:** the issue's open question, answered by measurement (curl_cffi
  0.17.0, libcurl 8.23.0): it is not test margin. libcurl recomputes the rate
  only when it takes a new one-second record, so a received byte reaches the
  low-speed check up to a second late. With `LOW_SPEED_TIME` 1, a body
  streaming 100 bytes every 50 ms aborted 6/25 times at 1.0 s (stdlib path
  0/25), with no CPU load needed; with `LOW_SPEED_TIME` 2, a body whose first
  byte came at 1.5 s and was still arriving at 2 s aborted 9/10 times. With the
  extra second: 0/25 and 0/30; the issue's test under 4 CPU-bound processes
  went from 5/30 to 0/30.
- **Rejected:** widening the test's gap/timeout ratio (hides a false abort
  that `--timeout 1` users hit about one transfer in five);
  `max(2, ceil(--timeout))` (removes the one-second case, keeps the late first
  byte at every `--timeout`); an exact idle timer (needs `XFERINFOFUNCTION`,
  which curl_cffi does not expose; see `docs/DEBT.md`).
- **Pending:** none.

## 2026-11-19 — Playwright under the httrack profile (#78 PR 4)

- **Decision:** every navigation of the crawled page is fetched by the
  profile's `Fetcher` (`crawl.fetch_page`) and handed to Chromium with
  `route.fulfill()`; a refusal (challenge, non-2xx, robots.txt, scope) is
  never opened. This replaces the spec's `route.fetch()` (user's choice
  between the two). The redirect chain is resolved before `page.goto`, which
  then opens the final URL; each page opens from `about:blank`, so the
  previous page cannot start a navigation that takes the armed answer. Subresources
  go to the network as the browser's own requests, with the profile's UA;
  iframes, popups and navigations a page starts itself are aborted; `/cdn-cgi/`
  is aborted for every request; service workers are blocked. Redirects of a
  seeded run use `fetch_url_list`'s rule (host and `--filter`), those of a
  crawl `mirror.outside` with the start re-base. A seeded run opens its seeds
  alone; followed links carry their page as `Referer` and pass mirror's
  extension pre-filter; a non-HTML answer is saved, never opened. After an
  engine fetch, the browser pass reports apart and is no front: the engine's
  files stand when it saves nothing, and challenges that left a crawl at one
  page do not trigger it. `--cache`, `--updatehack`, `--do-not-recatch` and
  `--changes` with `--headless` are a usage error. `fire-engine` is unchanged
  (still fails loud on `--headless` and SPAs).
- **Why:** `route.fetch()` runs in Playwright's driver (`context.request`, a
  Node client), so its TLS is neither the profile's nor Chromium's, and the
  spec's §8.0 showed the handshake decides. A spike with Playwright 1.58's
  Chromium showed that a 3xx given to `route.fulfill()` is followed without
  routing the next hop. A route handler may block (the Fetcher's pacing) but
  `page.goto`'s 10 s timeout keeps running, hence the fetch before the goto.
  The update flags steer the engine's revalidation, and `--headless` has none.
- **Rejected:** `route.fetch()` (other TLS, the policy rebuilt around it);
  a fulfilled 3xx (escapes the route); a URL match for the armed answer
  (Chromium normalizes URLs; `about:blank` makes the match positional);
  Playwright for `fire-engine` (its navigations would lose the curl_cffi
  fingerprint, and its tests are another lane's).
- **Pending:** none. The maintainer answered the four open questions
  (2026-11-19):
  - Subresources stay Chromium's own requests (its TLS, the profile's UA, no
    robots.txt, no pacing; `/cdn-cgi/` aborted). This is an approved deviation
    (spec §5.2). They are dependencies of a page the policy already let
    through, as in an ordinary browser visit, and robots.txt often forbids
    legitimate assets. The load is bounded by the paced navigations and
    Chromium's per-host connection limit; not by the HTTP cache, which
    Playwright turns off while routing is on (measured).
  - A page's own navigation (meta refresh, `location =`) is to be queued as a
    link; not implemented, tracked in #159.
  - After an engine fetch, the browser pass is to reuse the engine's body
    instead of fetching each page again; not implemented, tracked in #160.
  - The exit 2 for `--cache`, `--updatehack`, `--do-not-recatch` and
    `--changes` with `--headless` stays.

## 2026-11-18 — Root CLAUDE.md split into nested files

- **Decision:** the module tree, the "Arquivos de contexto" rows and
  "Comandos úteis" move verbatim into nested CLAUDE.md files under
  `src/dograpper/{,commands,lib,lib/httrack,lib/fire_engine,utils}/` and
  `tests/`. The root keeps the contracts (numbering unchanged), gates,
  parallel-session flow, harness maintenance, environment pitfalls, the rows
  about root files and one pointer per nested file. A row goes to the lowest
  directory that holds all the code it protects, so the 33 rows that span
  directories sit in `src/dograpper/CLAUDE.md`.
- **Why:** measured with `claude -p "/context"`. The root cost 29.1k tokens in
  every session (cl100k said 19.0k: Claude's tokenizer counts this text about
  1.5× higher). A session in `.claude/worktrees/<name>` loads only the
  worktree's copy, not the main checkout's as an ancestor. A probe with
  marker files showed that a nested file loads on the first Read (or Edit)
  of a file below it, together with those of the directories in between.
  Grep does not load it, and after compaction it comes back on the next Read,
  so anything that must hold for the whole session stays in the root. After
  the split the root measures 8.9k. Reading code in one area adds about
  2.5–3.7k per nested file, and tests/ adds 6.2k. A session that reads every
  directory costs about 31k, 2k more than before. sdist, wheel and the
  PyInstaller binary built with nested CLAUDE.md files present ship none of
  them. Probes outside the project directory (for example the scratchpad) load
  no project CLAUDE.md at all, so measure inside `.claude/worktrees/`.
- **Rejected:**
  - Spanning rows only in their main directory: an edit of
    `commands/pack.py` would miss the dedup row.
  - Spanning rows at the root: +2.4k in every session.
  - `.claude/rules/` with `paths:`: a second mechanism, not tried.
  - `claudeMdExcludes`: there is no double load to exclude.
- **Pending:** none.

## 2026-11-18 — Existing text keeps its words (#153)

Supersedes the "Pending" of the entry below.

- **Decision:** the confirmed glossary terms are not applied to text and
  identifiers that already exist. The README section "Downloader profiles",
  the `[httrack]` help labels, `PROFILE_OPTIONS` / `run_profile` and the
  `Files skipped: N (cached)` summary line keep their words; new text uses
  the terms.
- **Why:** the maintainer decided it when asked, after #153 was merged.
  Renaming the summary line or the help labels is an observable change, and
  renaming identifiers changes no behaviour.
- **Rejected:** a rename pass over the README, the help labels and the
  identifiers.
- **Pending:** none.

## 2026-11-18 — Glossary terms confirmed by the maintainer (#138)

Supersedes the "Pending" of the entry below.

- **Decision:** the picks of the `Download` section of `GLOSSARY.md` stand:
  *downloader*, *update*, *kept file* and *link rewriting* are the terms, with
  "profile", "update mode", "cached file" and a bare `-K0` under `_Avoid_`.
- **Why:** the maintainer confirmed them when asked, after the docs audit
  (#138) was merged.
- **Rejected:** none.
- **Pending:** maintainer: whether the terms are applied to text that already
  exists. The README section "Downloader profiles", the `[httrack]` help
  labels, `PROFILE_OPTIONS` / `run_profile` and the `Files skipped: N
  (cached)` summary line keep the old words. This session's recommendation is
  to leave them and use the terms in new text: renaming a summary line is an
  observable change.

## 2026-11-18 — Download-side terms picked for GLOSSARY.md (docs audit)

- **Decision:** `GLOSSARY.md` gains a `Download` section: Mirror, Downloader,
  fire-engine, Manifest, Update, Kept file, Link rewriting, Change report.
  Where the repo used two words for one thing, one was picked: *downloader*
  over "profile", *update* over "update mode", *kept file* over "cached file",
  *link rewriting* over a bare `-K0`. Flags, summary lines and existing prose
  were left as they are.
- **Why:** the maintainer asked for the terms of batches 5 and 6. The
  `--downloader` flag and the README's "Updates" section already use these
  words, and "cached file" misdescribes a design that keeps no cache beside
  the mirror (README, deviations from HTTrack). "Cache mode" stays out of
  `GLOSSARY.md`: `docs/glossario.md` explains it as jargon, and a domain term
  is never defined in both.
- **Rejected:** "update mode" and "cached file" as terms of their own (two
  names for one thing each); renaming "profile" across the README and the
  code in a docs audit.
- **Pending:** maintainer: confirm the picks, above all *downloader* against
  "profile" (the README section "Downloader profiles", `PROFILE_OPTIONS` and
  `run_profile` keep the old word) and *update* against "update mode".

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
