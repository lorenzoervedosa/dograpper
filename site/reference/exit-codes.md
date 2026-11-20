# Exit codes

| Code | Origin | Meaning | Remediation |
|------|--------|---------|-------------|
| 0 | any | success | — |
| 1 | any | `--verbose` together with `--quiet`, or a `--config` file that is not valid JSON | drop one flag; fix the file |
| 2 | any | usage error: unknown option, missing argument, invalid value | see `--help` |
| 1 | doctor (default) | one or more deps missing | run `dograpper doctor --install` |
| 1 | doctor --install | download, SHA256 verification, or the chromium install step failed | retry, check network/proxy |
| 1 | doctor --check-system-libs | `ldd` not found on this system | install `ldd` (usually part of `libc-bin`) |
| 1 | download / crawl | chromium not installed, or any other crawl failure | run `dograpper doctor --install` |
| 1 | download --downloader httrack / fire-engine | every seed, or the start URL of the crawl (or of `httrack --headless`'s Playwright crawl), refused/challenged; `fire-engine`: `--headless`, a result that looks client-rendered, or no `fire-engine` extra | retry later, switch to `--downloader wget`, change network (`fire-engine`: `--proxy`), or install the extra |
| 2 | download / sync | a `[httrack, fire-engine]` flag under `--downloader wget`, `--proxy` or a non-default `--impersonate` without `--downloader fire-engine`, `--cache`/`--updatehack`/`--do-not-recatch`/`--changes` with `--downloader httrack --headless`, or an invalid `--filter` rule | fix the flags |
| 1 | pack --context-header --manifest | the manifest named with `--manifest` is missing or cannot be loaded | fix the path, or re-run `dograpper download` to rewrite the manifest |
| 1 | pack --layout page | `pages/` exists in the output directory without `INDEX.md`, or a page file cannot be written | move that `pages/` away or pick another `--output`; free space or fix permissions |
| 2 | pack --layout page | a chunk-only setting, `--bundle`, `--for-queries`, `--format jsonl`, `--api-records` or `--dedup` other than `off` | drop the setting, or use `--layout chunk` |
| 2 | pack --api-records | `--format` other than `jsonl`, or `--bundle notebooklm` | use `--format jsonl`; drop the bundle |
| 1 | pack | no input file, or every file excluded by the ignore rules or skipped as a bot-challenge or saved error page; `--for-queries` with `--strategy semantic` or with an unreadable or empty file; `--report` with `--dry-run` | fix the input or the flags |
| 1 | download | the manifest cannot be written | fix permissions or free space in `--output`; the mirror itself is complete |
| 1 | pack --delta | `pack_state.json` cannot be written | fix permissions or free space in `--output`; the chunks are complete, the next `--delta` run packs in full |
| 2 | pack | `--dedup-threshold` outside 0 to 10, or an unknown `--token-encoding` (command line or config) | use a value in range; `cl100k`, `o200k`, `p50k` or a full tiktoken name |
| 2 | pack | `--output` is the same directory as `INPUT_DIR` | use a subdirectory or another path |
| 1 | explain / eval / serve | no chunk file matches `--prefix` (JSONL for `eval` and `serve`); `explain`: unknown chunk id; `eval`: no record carries a heading breadcrumb | re-run `pack` with the format and flags the command needs |
| 1 | drift | a snapshot or the delta manifest is unreadable or malformed; with `--fail-on-drift`, drift was found | fix the file; with `--fail-on-drift` the exit is the signal asked for |
| 1 | init | the config file exists (`--yes` without `--force`, or the overwrite prompt declined) | pass `--force`, or another `--output` |
| 2 | init | `--yes` without `--target`, or `--skill-dir` with a target other than `claude-code` | add `--target`; drop `--skill-dir` |
| 1 | docs | the port is in use | pick another `--port` |
| 2 | doctor --check-system-libs | system libs missing | run suggested `apt install ...` |
| 3 | doctor --check-system-libs | chromium not installed (with `--install`, the install ran first and did not leave one) | run `dograpper doctor --install` |
| 4 | doctor --install | concurrent install lock held | wait for other install, retry |
| 10 | install.sh | SHA256 mismatch | retry install, report issue |
| 20 | install.sh | unsupported architecture | — |
| 21 | install.sh | unsupported OS | — |
| 30 | install.sh | binary or checksum download failed | check network/proxy, retry |
