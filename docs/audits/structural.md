# Structural audit log

Append-only log of the `/structural-audit` command
(`.claude/commands/structural-audit.md`). Each run appends one dated entry at
the end and diffs against the previous one. Never edit or delete an entry.

## 2026-11-18 — baseline (src at `23f2f5d`)

Baseline metrics only, recorded with the command; no findings triaged yet.

- **Largest modules (lines):** `commands/pack.py` 830, `lib/chunker.py` 659,
  `utils/html_stripper.py` 500, `commands/download.py` 413,
  `lib/wget_mirror.py` 409, `utils/content_extractor.py` 380,
  `lib/httrack/fetcher.py` 354, `commands/doctor.py` 284,
  `lib/manifest.py` 281, `utils/link_extractor.py` 269.
- **Churn, last 4 weeks (commits):** `lib/httrack/fetcher.py` 16,
  `commands/pack.py` 16, `lib/httrack/policy.py` 11,
  `commands/download.py` 10, `lib/httrack/crawl.py` 9. Size × churn:
  `commands/pack.py`, `commands/download.py`, `lib/httrack/fetcher.py`.
- **Layering:** no `utils/` → `lib/`/`commands/` and no `lib/` → `commands/`
  import.
- **Second-copy markers:** `lib/httrack/policy.py:17` (version lookup),
  `tests/conftest.py:9` (local HTTP server), `tests/test_httrack_fetcher.py:118`
  (decoder fixture).
- **Test files over 1000 lines:** `tests/test_download.py` 1197.

## 2026-11-18 — src at `1aff627`

Diff against the baseline is not like for like: 41 files changed between
`23f2f5d` and `1aff627` (+3787/-392).

- **Largest modules (lines):** `commands/pack.py` 851 (+21), `lib/chunker.py`
  664, `lib/httrack/links.py` 611, `utils/html_stripper.py` 608 (+108),
  `lib/httrack/crawl.py` 558, `lib/httrack/jsscan.py` 471,
  `commands/download.py` 469 (+56), `lib/wget_mirror.py` 462 (+53),
  `utils/content_extractor.py` 380, `lib/httrack/fetcher.py` 375.
- **Churn, last 4 weeks (commits):** `lib/httrack/crawl.py` 23,
  `lib/httrack/fetcher.py` 20, `commands/pack.py` 20, `commands/download.py`
  20, `lib/httrack/policy.py` 19. Size × churn: `commands/pack.py`,
  `commands/download.py`, `lib/httrack/crawl.py`.
- **Layering:** no `utils/` → `lib/`/`commands/` and no `lib/` → `commands/`
  import; no write bypasses `utils/atomic_write.py`.
- **Test files over 1000 lines:** `tests/test_download.py` 1361 (was 1197).
- **Findings:**
  1. fix-now — the local HTTP server is at its 3rd copy: `tests/conftest.py:33`,
     `tests/test_httrack_fetcher.py:68`, `tests/test_fire_engine.py:565`
     (`trickle`); `tests/conftest.py:9` says to factor it out on the third.
  2. debt — `pack()` is one ~653-line function (`commands/pack.py:198-851`),
     20 commits in 4 weeks.
  3. debt — `lib/httrack/mirror.py:229` is the 2nd copy of the `write()` of
     `lib/httrack/crawl.py:476`; extract on the 3rd.
  4. debt — `tests/test_download.py` 1361 lines (+164); split by layer.
  5. ignore — growth of `utils/html_stripper.py` (+108), `commands/download.py`
     (+56) and `lib/wget_mirror.py` (+53) is feature-driven, all under 700
     lines; revisit past 700.
- No open issue or `docs/DEBT.md` entry covers these findings; none was filed
  or written in this run.
