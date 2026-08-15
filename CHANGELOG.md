# Changelog

All notable changes to this project are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Entries start at `0.4.0`. For anything earlier, read `git log`.

## How to update this file

**What earns an entry.** A change belongs here exactly when a user can observe
it without reading the source: the CLI surface (a command, a flag, printed
output, an exit code), the files a run writes or the format of those files, the
GitHub Action's inputs/outputs/behaviour, or an install or runtime requirement.
Everything else — internal refactors, tests, tooling, docs — earns nothing.

**Which section.** Derive it from the Conventional Commit type:

| Commit | Section |
|---|---|
| `feat:` introducing new surface | `Added` |
| `feat:` or `fix:` that alters documented behaviour on purpose | `Changed` |
| `fix:` restoring intended behaviour | `Fixed` |
| removal of existing surface | `Removed` |
| surface kept but slated for removal | `Deprecated` |
| anything with a security impact | `Security` |
| `refactor:` `test:` `chore:` `ci:` `build:` `docs:` | *(none)* |

A `refactor:` or `chore:` that would need an entry was mistyped — it changed
behaviour, so it is a `feat:` or a `fix:`.

**When.** In the same pull request that makes the change, appended to
`## [Unreleased]`. Never reconstructed in a batch at release time.

**Granularity.** One line per user-visible change, not per commit: five commits
that build one flag are one entry. A contract change links its ADR and issue.

**Releasing.** Rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD`, open a
fresh empty `## [Unreleased]` above it, and bump `version` in `pyproject.toml`
in the same commit — `dograpper --version` reads the installed package
metadata, so a tag without the bump ships a binary that misreports itself.
While the project is pre-1.0, new surface or a contract change is a MINOR bump
and fixes alone are a PATCH bump.

`tests/test_changelog.py` enforces the mechanical half of these rules.

## [Unreleased]

## [0.4.0] - 2026-08-15

### Added

- `dograpper eval` — offline validation of a packed context: deterministic
  golden Q&A generated from heading breadcrumbs, BM25 retrieval, and
  hit-rate@k / MRR reported per readiness grade. No network calls.
- `dograpper explain` — read-only preview of exactly what the LLM receives per
  chunk (v1 headers, cross-references, grade). Writes nothing.
- `dograpper serve` — local MCP server over the packed JSONL, speaking
  newline-delimited JSON-RPC 2.0 on stdio: search, get, cross-refs, readiness.
- `dograpper init` — onboarding wizard that generates a `.dograpper.json` tuned
  per target (`notebooklm`, `rag`, `claude-project`). `--target` with `--yes`
  for scripted use.
- `dograpper drift` — diff between two `llm-readiness.json` snapshots, rendered
  as markdown or text, with `--fail-on-drift` for CI.
- Composite GitHub Action for context freshness: re-packs, computes the drift
  and posts a single upserted report comment on the pull request.
- `pack --for-queries` — reorders source files by BM25 affinity to a list of
  expected queries so content answering the same question is co-located.
  Requires `--strategy size`.
- `pack --report` — writes `readiness-report.html` with per-page before/after
  extraction data and the cause of each score penalty. Implies `--score`.

### Changed

- `pack --delta` is now a change gate: the corpus state recorded by the last
  pack decides *whether* the run happens, not *which* files it packs. Nothing
  changed, nothing is written; anything changed, the pack runs in full. Partial
  runs used to renumber chunks from `01` and overwrite the artifacts of the
  files they did not touch. ([#39], [ADR-0008](docs/adr/0008-delta-as-a-change-gate.md))
- `pack --delta` records `pack_state.json` in the output directory and diffs
  against it on the next run, so delta now works in pack-only flows. ([#39])
- `pack --manifest` no longer drives the delta comparison; its remaining role is
  resolving source URLs for `--context-header`. `pack` never writes it. ([#39])
- `--report` is a paired flag (`--report/--no-report`) so a config file that
  enables it can still be overridden from the command line.

### Fixed

- The content extractor no longer discards the rest of a page after a
  blacklisted element whose end tag never arrives — a void element such as
  `<img class="copy-button">`, or stray markup inside a code sample. Extraction
  used to stop mid-sentence at an arbitrary point. ([#42])
- `sync` preserves explicit CLI flag precedence across `ctx.invoke`, so a
  `.dograpper.json` value no longer overrides a flag typed on the command line.
- `pack` skips binary files instead of counting their bytes as words. ([#2])
- `download` uses a binary reject-list so wget follows pretty URLs. ([#1])
- `pack` no longer aborts when a single page fails extraction during `--report`.
- `serve` survives malformed request params and tool handlers that raise.
- `drift` rejects malformed snapshots and delta manifests loudly instead of
  degrading silently, and omits the source-file section when no delta manifest
  was given.
- Boundary issues are attributed to the source page that caused them rather
  than to the joined chunk text.
- Query-oriented ordering ignores terms common to the corpus, excludes the
  queries file itself from the packed corpus, ranks on post-dedup text, warns
  on unreadable files instead of skipping them silently, and reports its
  summary in `--dry-run`.
- The release install script matches the filename referenced by its `.sha256`
  companion.

[#1]: https://github.com/lorenzoervedosa/dograpper/issues/1
[#2]: https://github.com/lorenzoervedosa/dograpper/issues/2
[#39]: https://github.com/lorenzoervedosa/dograpper/issues/39
[#42]: https://github.com/lorenzoervedosa/dograpper/issues/42
