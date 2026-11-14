# httrack profile, PR 1 (fetch core + profile switch): Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `dograpper download --downloader httrack`. It fetches the URLs
that llms.txt or the sitemap discovered, with HTTrack-identical identity, TLS,
headers, robots.txt, politeness, retry and status policy. Paths that later PRs
build fail loudly.

**Architecture:**
- A new stdlib-only package, `src/dograpper/lib/httrack/`, holds the policy,
  robots, fetcher, challenge and naming modules, plus a seeded-list crawl that
  returns a `CrawlResult`-compatible result.
- `commands/download.py` picks the layer-3 engine per profile. It passes the
  profile's fetch function to layers 1 and 2 through a new optional parameter;
  when that parameter is absent, behavior is byte-identical to today.
- Two PRs: **1a = Tasks 1–6** (library only, no CLI surface) and
  **1b = Tasks 7–10** (CLI, layers, docs, release).
- **Link rewriting lands in PR 2** (spec §3). Until then, pages fetched by
  the httrack profile keep absolute links, so `pack --cross-refs` finds fewer
  references. Task 10's README states this limitation.

**Tech Stack:** Python ≥ 3.10 stdlib (`http.client`, `ssl`, `threading`,
`concurrent.futures`, `html.parser`, `zlib`, `hashlib`), click, pytest. There
is an optional extra `httrack = ["brotli>=1.1", "zstandard>=0.22"]`.

**Spec:** `docs/superpowers/specs/2026-11-13-httrack-downloader-profile-design.md`
(§ refs below point there). Evidence lives in
`docs/discovery/httrack-mirroring-requirements.md`.

## Global Constraints

- The `wget` profile must stay byte-for-byte unchanged: flags, UA, cascade and
  manifest. All 10 existing `tests/test_download_cascade.py` tests must pass
  untouched.
- No new mandatory dependency. `brotli` and `zstandard` are imported
  conditionally, only inside `policy.py`.
- Playwright is never imported in `lib/httrack/` (CLAUDE.md rule 4).
- **Default UA:** `Mozilla/5.0 (compatible; dograpper/<version>)`, where
  `<version>` comes from `importlib.metadata.version("dograpper")`. That is a
  second copy of `cli.py:18`; comment it as such.
- **Defaults:**
  - connections 4;
  - new connections/s 5;
  - bandwidth 100000 B/s;
  - timeout 120 s;
  - retries 2;
  - max links 100000;
  - max-retry-after 60 s (hard maximum 3600).
- **Clamps:** connections ≤ 8, conn/s ≤ 5, bandwidth ≤ 10000000. Each clamp
  logs a warning. `--disable-security-limits` lifts them; it never lifts the
  3600 s maximum.
- **No silent fallback.** A missing PR 2 or PR 4 path raises
  `click.ClickException` (exit 1) and names the missing piece.
- Reads use `errors="replace"`. Files are written atomically through
  `utils/atomic_write.py` (Task 1).
- Every file write stays inside `output_dir`; path traversal is rejected
  (Task 5).
- Logs, reports and errors never include cookie values. (No cookies exist in
  PR 1; the rule still binds the report code.)
- Each PR ships its tests, README section, `[Unreleased]` CHANGELOG entry and
  the CLAUDE.md tree and test-table rows (`tests/test_claude_md_inventory.py`
  enforces the tree). `tests/fixtures/help_baseline.txt` must NOT change
  (top-level help is untouched).
- **Before each commit:** `uv run pytest tests/ -q`, all green.

## Review Focus

1. **Every seed is challenged or refused** (403 `cf-mitigated`). Expect exit
   1 and a message naming bot protection, with no file written. PR 1 has no
   `--browser-login`, so the message must not mention it. Test in Task 7.
2. **`/robots.txt` returns 200 HTML** (soft-404) or is unreachable. Expect "no
   rules", as HTTrack does: any failure means no rules. Test in Task 2.
3. **`Retry-After: 86400` or a past HTTP-date.** Expect it capped at
   max-retry-after with a warning, or 0 s. Test in Task 4.
4. **Seed URL path with `..`, `%2e%2e` or a backslash.** Expect the file to
   stay inside `output_dir`, or the URL to be skipped and reported, never
   written outside. Test in Task 5.
5. **Ctrl+C mid-download.** Expect no truncated HTML file at its final path,
   thanks to the atomic write. Test in Task 1.

---

## PR 1a: library (no CLI surface, no CHANGELOG entry)

### Task 0: Pin HTTrack wire fixtures

**Files:**
- Create: `tests/fixtures/httrack_wire/capture.py`. Copy it from the spike's
  `tls_capture.py` and keep its `shortcut:` docstring. It is not collected by
  pytest.
- Create: `tests/fixtures/httrack_wire/README.md`. Explain how the fixtures
  were captured: `httrack.exe` 3.51-0 with OpenSSL 3.6.5, the command line,
  and the date.
- Create: `tests/fixtures/httrack_wire/httrack_3.51_requests.json`. Use the
  shape `{"robots": {...}, "start": {...}, "linked": {...}}`. Each entry has
  `request_line`, `headers` (ordered list) and `client_hello` (the parsed
  dict).

- [ ] **Step 1:** Serve a two-page local site (`/` links to `/a.html`) with
  `capture.py`. Run
  `"/mnt/c/Program Files/WinHTTrack/httrack.exe" "https://localhost:8443/" -O "<win temp>" -r3 -q`.
  Save the three captured records (robots, start, linked) into the JSON.
  Expected: three records, with `Sec-Fetch-*` present on `/` and recorded for
  `/a.html`, whatever values HTTrack sends.
- [ ] **Step 2: Commit** `test: pin HTTrack 3.51 wire captures as fixtures`

If `httrack.exe` is not available (not on WSL), stop. A human must capture the
fixtures. Do not hand-write them.

### Task 1: Atomic write helper

**Files:** Create `src/dograpper/utils/atomic_write.py`. Test in
`tests/test_atomic_write.py`.

**Interfaces:** Produces `atomic_write_bytes(path: str, data: bytes) -> None`.
It creates parent dirs, writes to a temp file in the same directory, then
`os.replace`s it into place.

- [ ] **Step 1: Tests.**
  - `test_atomic_write_creates_parents_and_content`
  - `test_atomic_write_failure_leaves_no_final_file`: monkeypatch `os.replace`
    to raise `KeyboardInterrupt`; assert the final path does not exist and no
    `*.tmp` is left behind.
- [ ] **Step 2:** Run `uv run pytest tests/test_atomic_write.py -v`. Expected:
  FAIL (ImportError).
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Rerun. Expected: PASS.
- [ ] **Step 5: Commit** `feat: add atomic file write helper`

### Task 2: robots.txt parser

**Files:** Create `src/dograpper/lib/httrack/__init__.py` (empty) and
`src/dograpper/lib/httrack/robots.py`. Test in `tests/test_httrack_robots.py`.

**Interfaces:**
- Produces a frozen dataclass
  `RobotsRules(groups_rules: tuple[tuple[str, str], ...], crawl_delay: float | None, sitemaps: tuple[str, ...])`.
- Produces `RobotsRules.allowed(path_and_query: str) -> bool`.
- Produces `parse_robots(text: str, agent_token: str = "dograpper") -> RobotsRules`.
- Produces `NO_RULES: RobotsRules`, which allows everything.

Rules (spec §5.2; HTTrack `src/htsrobots.c`):
- **Group selection:** a group whose `User-agent` value, lowercased, starts
  with `agent_token` beats `*`. Consecutive `User-agent:` lines form one
  group.
- **Matching:** `*` matches any run of characters and `$` anchors the end. The
  longest pattern wins (by pattern length), and `Allow` wins ties. An empty
  `Disallow:` is ignored. `/robots.txt` is always allowed.
- **Crawl-delay:** a float, taken from the selected group only.
- **Sitemap:** lines are collected from anywhere in the file.
- **Caps:** text is cut at 500 KiB and lines at 1024 bytes. A truncated
  `Allow` is dropped, a truncated `Disallow` is kept, and a warning is logged.

- [ ] **Step 1: Tests.** Each asserts the exact boolean or value.
  - `test_specific_group_beats_star`: `User-agent: dograpper` /
    `Disallow: /x` plus `User-agent: *` / `Disallow: /`;
    `allowed("/y") is True` and `allowed("/x") is False`.
  - `test_consecutive_user_agents_share_group`
  - `test_longest_match_wins`: `Disallow: /a` + `Allow: /a/b`;
    `allowed("/a/b/c") is True`.
  - `test_allow_wins_tie`: `Allow: /p` + `Disallow: /p`; True.
  - `test_wildcard_and_end_anchor`: `Disallow: /*.pdf$`; `/x.pdf` False,
    `/x.pdf?y` True.
  - `test_crawl_delay_from_selected_group_only`
  - `test_sitemaps_collected_globally`
  - `test_html_soft404_body_yields_no_rules` (Review Focus 2): an HTML page
    parsed gives `allowed("/anything") is True` and `crawl_delay is None`.
  - `test_oversized_rules_truncated_with_warning` (use `caplog`).
- [ ] **Step 2:** Run. Expected: FAIL (ImportError).
- [ ] **Step 3:** Implement `parse_robots` and `RobotsRules.allowed`.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5: Commit** `feat(httrack): add RFC 9309 robots.txt parser`

### Task 3: Policy, headers, TLS context

**Files:** Create `src/dograpper/lib/httrack/policy.py`. Test in
`tests/test_httrack_policy.py`.

**Interfaces (produces):**
- `DEFAULT_USER_AGENT: str`.
- `ACCEPT = "text/html,image/png,image/jpeg,image/pjpeg,image/x-xbitmap,image/svg+xml,image/gif;q=0.9,*/*;q=0.1"`.
- `ACCEPT_LANGUAGE = "en, *"`.
- A frozen dataclass `HttrackPolicy` with fields:
  - `user_agent: str`
  - `connections: int`
  - `max_conn_rate: float`
  - `max_bandwidth: int`
  - `timeout: float`
  - `retries: int`
  - `max_links: int`
  - `max_retry_after: int`
  - `delay_ms: int`
  - `obey_robots: bool`
- `build_policy(*, user_agent: str | None = None, connections: int = 4, max_conn_rate: float = 5.0, max_bandwidth: int = 100_000, timeout: float = 120.0, retries: int = 2, max_links: int = 100_000, max_retry_after: int = 60, delay_ms: int = 0, obey_robots: bool = True, disable_security_limits: bool = False) -> HttrackPolicy`.
  It applies the clamps and logs one warning per clamp.
- `accept_encoding() -> str`:
  - base `gzip, deflate, identity;q=0.9`;
  - `br` is inserted after `deflate` when `brotli` imports;
  - `zstd` is inserted after `br` (or after `deflate`) when `zstandard` or
    `compression.zstd` imports.
- `request_headers(policy: HttrackPolicy, host: str, *, kind: str, referer: str | None) -> list[tuple[str, str]]`.
  - `kind` is `"robots" | "navigate" | "linked"`.
  - It returns the exact HTTrack order and values from the Task 0 fixture,
    with only `User-Agent` and `Accept-Encoding` substituted.
- `make_ssl_context() -> ssl.SSLContext`:
  - `PROTOCOL_TLS_CLIENT`;
  - `set_ciphers("DEFAULT")`;
  - `minimum_version = TLSv1_2`;
  - `options |= OP_ALL`;
  - default certs loaded and verification ON;
  - no ALPN.
- `warn_if_old_openssl() -> bool`: logs a WARNING and returns True when
  `ssl.OPENSSL_VERSION_INFO < (3, 5)`. The message names the requirement and
  points to the README section.

- [ ] **Step 1: Tests.**
  - `test_clamps_apply_and_warn`:
    `build_policy(connections=20, max_conn_rate=50, max_bandwidth=10**9)` gives
    8 / 5.0 / 10_000_000, and `caplog` holds 3 warnings.
  - `test_disable_security_limits_lifts_clamps_not_retry_after_cap`: with
    `max_retry_after=99999` the value is 3600.
  - `test_headers_match_httrack_fixture_<kind>`, for robots, navigate and
    linked: the list equals the fixture's `headers` after the UA and
    Accept-Encoding values are replaced. Order is part of the assertion.
  - `test_accept_encoding_variants`: monkeypatch import availability across
    the 4 combinations.
  - `test_ssl_context_config`: `minimum_version`, `verify_mode == CERT_REQUIRED`,
    and `OP_ALL` bits set.
  - `test_client_hello_matches_httrack_fixture`.
    - Skip unless `ssl.OPENSSL_VERSION_INFO >= (3, 5)`.
    - Start the Task 0 `capture.py` handler in-process on an ephemeral port.
      The test context trusts the fixture cert.
    - Compare the parsed ClientHello to the fixture's `start.client_hello`.
      Ignore `ec_point_formats` and the SNI length; spec §5.1 documents both.
  - `test_warn_if_old_openssl` (monkeypatch `OPENSSL_VERSION_INFO`).
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run with system Python (the ClientHello test skips), then
  with `uv run --python 3.13 pytest tests/test_httrack_policy.py -v` (it
  runs). Expected: PASS for both.
- [ ] **Step 5: Commit** `feat(httrack): add HTTrack-identical request policy and TLS context`

### Task 4: Fetcher (connections, pacing, retries, Retry-After, decoding, challenge)

**Files:** Create `src/dograpper/lib/httrack/challenge.py` and
`src/dograpper/lib/httrack/fetcher.py`. Tests in
`tests/test_httrack_fetcher.py`, with a threaded `http.server` fixture on
127.0.0.1 in `tests/conftest.py` or local to the test file.

**Interfaces:**
- **`challenge.py`:** `is_challenge(status: int, headers: Mapping[str, str], body: bytes) -> bool`.
  - It returns True iff `cf-mitigated` is present, or the status is 200 and
    the `<title>` (case-insensitive, whitespace-stripped) equals
    `Just a moment...`.
  - It never matches on `/cdn-cgi/challenge-platform/` (spec §5.4).
- **`fetcher.py`:** a dataclass `FetchResult` with fields:
  - `url: str`
  - `status: int | None`
  - `headers: dict[str, str]` (lowercased keys)
  - `body: bytes` (decoded)
  - `location: str | None`
  - `error: str | None`
  - `challenged: bool`
  - `attempts: int`
- **`fetcher.py`:** class `Fetcher(policy: HttrackPolicy, *, clock=time.monotonic, sleep=time.sleep)`.
  - `get(url: str, *, kind: str, referer: str | None = None) -> FetchResult`.
    It never follows redirects; callers decide.
  - `robots_for(scheme_host: str) -> RobotsRules`. It is cached per host and
    fetched with `kind="robots"`. Any non-200 or error returns `NO_RULES`.
  - It is thread-safe. One persistent `http.client` connection per (thread,
    host).
- **Pacing.** The `clock` and `sleep` injection is there so tests need no real
  waiting.
  - New connections/s: a token bucket at `policy.max_conn_rate`.
  - Bandwidth: a shared token bucket over body bytes read.
  - Per-host minimum gap: `max(policy.delay_ms / 1000, robots.crawl_delay or 0)`.
- **Retries.** Up to `policy.retries` extra attempts, with no backoff.
  - Retried: timeout, `OSError`, `ssl.SSLError`, and the statuses 408, 409,
    429, 500, 502 and 504.
  - 503 is retried only when it carries `Retry-After`.
  - Never retried: 401, 403, 404, 410.
- **Retry-After.**
  - Both delta-seconds and HTTP-date are parsed.
  - The value is capped at `policy.max_retry_after`, with a warning when
    capped. A past date means 0.
  - It holds a **global gate**: every worker waits before its next request.
- **Decoding** follows `content-encoding`: gzip and deflate (zlib), br and
  zstd when available. An unknown encoding is a `FetchResult.error`.

- [ ] **Step 1: Tests.**
  - `test_is_challenge_header`
  - `test_is_challenge_title`
  - `test_real_page_with_jsd_beacon_is_not_challenge`: a 200 whose body has
    `<title>Overview</title>` and a `/cdn-cgi/challenge-platform/scripts/jsd/main.js`
    script gives False.
  - `test_retries_429_then_200` (attempts == 2)
  - `test_no_retry_on_403_404`
  - `test_503_without_retry_after_not_retried`
  - `test_retry_after_gate_blocks_all_workers`: fake clock; a second
    `get()` issued from another thread sleeps for the gate's remaining time.
  - `test_retry_after_capped_and_past_date` (Review Focus 3)
  - `test_gzip_and_deflate_decoded`
  - `test_crawl_delay_paces_same_host` (fake clock: gaps ≥ crawl_delay)
  - `test_conn_rate_and_bandwidth_buckets` (fake clock)
  - `test_robots_non_200_is_no_rules`
  - `test_request_headers_sent_in_order`: the server records raw header
    lines.
- [ ] **Step 2:** Run. Expected: FAIL.
- [ ] **Step 3:** Implement.
- [ ] **Step 4:** Run. Expected: PASS.
- [ ] **Step 5: Commit** `feat(httrack): add polite HTTP fetcher with retry and Retry-After gate`

### Task 5: Naming

**Files:** Create `src/dograpper/lib/httrack/naming.py`. Test in
`tests/test_httrack_naming.py`.

**Interfaces:** Produces class `NameRegistry(output_dir: str)` with
`assign(url: str, content_type: str | None) -> str | None`. It returns an
absolute path under `output_dir`, or None when the URL cannot be mapped
safely.

Rules (spec §3, §5.6):
- **Layout:** `<output>/<host>/<path>`; a directory URL becomes `index.html`.
- **HTML extension:** a `text/html` response without `.html`/`.htm` gets
  `.html`, as wget `--adjust-extension` does.
- **Query string:** insert the first 4 lowercase hex digits of
  `md5(query).hexdigest()` before the extension. The case was observed in the
  HTTrack run.
- **Collisions:** a different URL mapping to the same path gets `-2`, `-3`, …
  before the extension. The same URL maps to the same path every time.
- **Safety:** the path is decoded and normalized, then rejected (None) if it
  resolves outside `output_dir`.

- [ ] **Step 1: Tests.**
  - `test_directory_url_maps_to_index_html`
  - `test_html_extension_adjusted`
  - `test_query_hash_suffix`: assert the 4 hex digits equal
    `hashlib.md5(b"x=1").hexdigest()[:4]`.
  - `test_collision_suffix_and_stability`
  - `test_traversal_rejected` (Review Focus 4: `/../x`, `/%2e%2e/x`, `/a\..\b`
    are all None, or all under `output_dir`)
- [ ] **Steps 2–4:** Fail, implement, pass.
- [ ] **Step 5: Commit** `feat(httrack): add HTTrack-style local file naming`

### Task 6: Seeded-list crawl + run report

**Files:** Create `src/dograpper/lib/httrack/crawl.py` and
`src/dograpper/lib/httrack/report.py`. Test in `tests/test_httrack_crawl.py`.

**Interfaces:**
- Consumes `Fetcher` (Task 4), `NameRegistry` (Task 5) and
  `atomic_write_bytes` (Task 1).
- **`report.py`:** a dataclass `RunReport` with fields:
  - `status_counts: dict[str, int]` (keys `"2xx"`, `"3xx"`, `"4xx"`, `"5xx"`,
    `"error"`)
  - `challenged: list[str]`
  - `robots_blocked: list[str]`
  - `retried: int`
  - `out_of_scope: list[str]`
  - `errors: list[tuple[str, str, str | None]]` (url, reason, referrer)
  - `partial: bool`
- **`report.py`:** `format_report(r: RunReport, verbose: bool) -> list[str]`.
  It shows the first 10 errors, or all of them with `verbose`.
- **`crawl.py`:** a dataclass `HttrackResult(success: bool, files_downloaded: list[str], files_skipped: int, report: RunReport, front_failed: bool)`.
  `success` and `files_downloaded` mirror `CrawlResult`.
- **`crawl.py`:** `fetch_url_list(urls: list[str], output_dir: str, policy: HttrackPolicy, include_extensions: str, *, fetcher: Fetcher | None = None) -> HttrackResult`.

Behavior:
- **Per URL:**
  1. robots check (`policy.obey_robots`);
  2. `/cdn-cgi/` skip;
  3. GET `kind="navigate"` for the first URL, `"linked"` after;
  4. a 2xx that is not challenged is named, filtered by `include_extensions`
     on the final file extension, and written atomically;
  5. anything else is reported and **never written**.
- **Redirects:** followed up to 5 hops, only to the same host. Any other
  target goes to `out_of_scope`.
- **Concurrency:** `policy.connections` workers. Stop at `policy.max_links`
  and set `partial`.
- **`front_failed`:** True iff zero files were written and every URL was
  challenged, refused (4xx/5xx/error) or robots-blocked.

- [ ] **Step 1: Tests** (local server fixture).
  - `test_writes_only_2xx_non_challenge`: a 404 page and a `cf-mitigated`
    403 are not on disk, and both are in the report.
  - `test_robots_blocked_not_fetched`: the server asserts that the path was
    never requested.
  - `test_cross_host_redirect_reported_out_of_scope`
  - `test_front_failed_when_all_challenged` (Review Focus 1, library side)
  - `test_max_links_sets_partial`
  - `test_include_extensions_filters_written_files`
  - `test_format_report_truncates_errors_unless_verbose`
- [ ] **Steps 2–4:** Fail, implement, pass.
- [ ] **Step 5: Commit** `feat(httrack): add seeded URL list fetch with run report`
- [ ] **Step 6:** Full suite, `uv run pytest tests/ -q`, green. **Open PR 1a**:
  `feat(httrack): fetch core for the httrack downloader profile`. The body
  links the spec and says "no CLI surface yet".

---

## PR 1b: CLI, layers, docs, release

### Task 7: `--downloader` and profile flags on `download`

**Files:**
- Modify `src/dograpper/commands/download.py`: the options, the
  `_run_download_cascade` branch, and the summary.
- Test in `tests/test_download_httrack_profile.py`.

**Interfaces:**
- Consumes `build_policy`, `fetch_url_list`, `format_report` and
  `warn_if_old_openssl`.
- **New options:**
  - `--downloader [wget|httrack]` (default `wget`);
  - `--user-agent TEXT`;
  - `--no-robots` (flag);
  - `--connections INT` (4);
  - `--max-conn-rate FLOAT` (5);
  - `--max-bandwidth INT` (100000);
  - `--timeout FLOAT` (120);
  - `--retries INT` (2);
  - `--max-links INT` (100000);
  - `--max-retry-after INT` (60);
  - `--disable-security-limits` (flag).
- Every new option goes into `cli_params`, so `.dograpper.json` keys work
  (hyphenated).
- Help text prefix for httrack-only options: `[httrack]`.

Behavior:
- **httrack-only flags with `--downloader wget`.** Any of them set explicitly
  on the CLI or in config raises `click.UsageError` (exit 2). The message
  names the flag.
- **Under `httrack`:**
  1. `warn_if_old_openssl()`.
  2. Layers 1 and 2 run with `fetch=` (Task 8).
  3. If URLs were discovered, `fetch_url_list(...)` runs.
  4. If `front_failed`, raise `click.ClickException`. The message says the
     site refused or challenged every seed (bot protection) and points to the
     README section. It does not mention `--browser-login`.
  5. If `is_spa(output)` holds, raise `click.ClickException`:
     "httrack profile: Playwright fallback is not implemented yet (planned);
     use --downloader wget".
  6. If nothing was discovered, raise `click.ClickException`: "httrack
     profile: recursive crawl is not implemented yet (planned); use
     --downloader wget".
  7. `--headless` raises the Playwright message above.
- The summary prints `format_report(...)` after today's lines.

- [ ] **Step 1: Tests**, mocking `fetch_url_list` and the layer fetchers the
  way `test_download_cascade.py` mocks wget:
  - `test_default_downloader_is_wget_unchanged`: the wget mocks are called
    with today's arguments.
  - `test_httrack_flag_with_wget_is_usage_error` (exit 2)
  - `test_httrack_seeded_fetch_happy_path`
  - `test_httrack_all_seeds_challenged_exits_1` (Review Focus 1). The output
    names bot protection and does not contain `browser-login`.
  - `test_httrack_no_discovery_fails_loud_recursive_crawl`
  - `test_httrack_headless_fails_loud_playwright`
  - `test_httrack_config_keys_respected_and_cli_wins` (precedence rule 6)
- [ ] **Steps 2–4:** Fail, implement, pass. Run
  `uv run pytest tests/test_download_cascade.py -v` too: unchanged, green.
- [ ] **Step 5: Commit** `feat(download): add --downloader httrack profile`

### Task 8: Layers 1 and 2 under the profile

**Files:**
- Modify `src/dograpper/lib/llms_txt_parser.py`: `fetch_llms_txt` gets
  `fetch: Callable[[str], bytes | None] | None = None`.
- Modify `src/dograpper/lib/sitemap_parser.py`: `fetch_sitemap` gets
  `fetch=None` and `extra_candidates: Sequence[str] = ()`. The extra
  candidates are tried *before* `CANDIDATE_PATHS`, and the same-netloc guard
  applies to them.
- Modify `src/dograpper/commands/download.py`: `_discover_urls` passes, under
  httrack, a `fetch` built on `Fetcher.get(kind="linked")`. It returns the body
  only for a 2xx non-challenged response that robots allows, and passes
  `robots.sitemaps` as `extra_candidates`.
- Tests: extend `tests/test_llms_txt_parser.py` and
  `tests/test_sitemap_parser.py`.

- [ ] **Step 1: Tests.**
  - `test_fetch_param_used_when_given`, in both files.
  - `test_robots_sitemap_hint_tried_first`
  - `test_extra_candidate_cross_host_rejected`
  - Existing tests are unchanged, which proves the `fetch=None` behavior is
    identical.
- [ ] **Steps 2–4:** Fail, implement, pass.
- [ ] **Step 5: Commit** `feat(download): route llms.txt and sitemap discovery through the httrack policy`

### Task 9: `sync` pass-through

**Files:** Modify `src/dograpper/commands/sync.py`: the options,
`_DOWNLOAD_PASSTHROUGH` and the `ctx.invoke` kwargs. Extend
`tests/test_sync.py` and `tests/test_sync_precedence.py`.

- [ ] **Step 1: Tests.**
  - `test_sync_forwards_downloader_and_httrack_flags`
  - `test_sync_httrack_precedence_cli_over_json`
- [ ] **Steps 2–4:** Fail, implement, pass.
- [ ] **Step 5: Commit** `feat(sync): forward downloader profile flags`

### Task 10: Extra, release build, docs

**Files:**
- `pyproject.toml`: the `httrack` extra; refresh `uv.lock` with `uv lock`.
- `dograpper.spec`: hiddenimports for `brotli` and `zstandard`, if
  PyInstaller misses them.
- `.github/workflows/release.yml`:
  - build on uv-managed Python: `uv python install 3.10`, with
    `UV_PYTHON_PREFERENCE=only-managed` set for the build steps;
  - `uv sync --extra build --extra headless --extra httrack --extra dev`;
  - before PyInstaller, a step
    `uv run python -c "import ssl,sys; v=ssl.OPENSSL_VERSION_INFO; print(ssl.OPENSSL_VERSION); sys.exit(0 if v >= (3,5) else 1)"`.
- `README.md`:
  - a "Downloader profiles" subsection in `download`: the flags table, the
    deviations list from spec §2, the OpenSSL ≥ 3.5 requirement with
    `uv python install 3.13` as the remedy, the `httrack` extra, and the
    fail-loud gaps (recursive crawl, Playwright), and the cross-refs limitation
    until PR 2;
  - a new exit-code row: "1 | download --downloader httrack | every seed
    refused/challenged".
- `CHANGELOG.md` `[Unreleased]` → Added: the `--downloader httrack` profile
  (one line) and the `httrack` extra (one line).
- `.dograpper.json.example`: `"downloader": "wget"`.
- `CLAUDE.md`: tree rows for `lib/httrack/*`, `utils/atomic_write.py` and the
  new tests; test-table rows for the new test files.

- [ ] **Step 1:** Run `uv lock` and
  `uv sync --extra dev --extra headless --extra httrack`. Expected: the lock
  is updated and both decoders import.
- [ ] **Step 2:** Run `uv run pytest tests/ -q`, including
  `test_claude_md_inventory.py`, `test_changelog.py` and
  `test_cli_regression.py`. Expected: all green, and the help baseline is
  unchanged.
- [ ] **Step 3:** Build check:
  `uv run --extra build --extra headless --extra httrack pyinstaller dograpper.spec --clean`,
  then `./dist/dograpper download --help`. Expected: the binary runs and
  lists `--downloader`.
- [ ] **Step 4: Commits** (one per concern):
  - `build: add optional httrack extra for br/zstd decoding`
  - `ci: build release binary on uv-managed Python with OpenSSL >= 3.5`
  - `docs: document downloader profiles`
- [ ] **Step 5:** Full suite green. **Open PR 1b**. The body links PR 1a and
  the spec and lists the fail-loud gaps.
