# dograpper sync

Convenience wrapper: `download` + `pack --delta` chained, with defaults
tuned for continuous maintenance. Forwards most `download` and `pack`
flags; calibration-only pack flags (`--report`, `--dry-run`) are
deliberately not exposed here.

```bash
dograpper sync <url> -o <dir> [options]
```

`pack` is always executed with an implicit `--delta`: when the mirror
came back unchanged the pack step is skipped entirely, and when
anything changed the chunks are rebuilt in full. See
[ADR-0008](https://github.com/lorenzoervedosa/dograpper/blob/main/docs/adr/0008-delta-as-a-change-gate.md).

## Examples

```bash
# Full sync with NotebookLM presets
dograpper sync https://docs.python.org/3/ -o ./py-docs --bundle notebooklm --context-header --score

# Daily cron sync (true incremental)
dograpper sync https://docs.rust-lang.org -o ./rust-docs --chunks-dir ./out/rust

# SPA sync
dograpper sync https://react.dev -o ./react-docs --headless --delay 500
```

## Options

```{dograpper-options} sync
```

## Options in detail

### `--filter`

URL rule, repeatable (passed to `download`; see [URL filters](download.md#url-filters---filter))

### `--downloader`

`wget` | `httrack` | `fire-engine` (passed to `download`; see [Downloader profiles](download.md#downloader-profiles))
