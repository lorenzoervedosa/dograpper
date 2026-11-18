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
