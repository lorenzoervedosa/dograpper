# dograpper doctor

Detects, reports, and installs the heavy dependencies (`wget`, chromium)
dograpper needs but doesn't bundle, into `DOGRAPPER_HOME` (default
`~/.dograpper`; see [Storage layout](https://github.com/lorenzoervedosa/dograpper/blob/main/README.md#storage-layout)).

```bash
dograpper doctor [options]
```

Without flags, prints a status table (`WGET`/`CHROMIUM`, path, version) and
exits 0 if both are present, 1 if either is missing.

Exit codes: see [Exit codes](../reference/exit-codes.md#exit-codes).

## Examples

```bash
dograpper doctor
dograpper doctor --install
dograpper doctor --install --force
dograpper doctor --check-system-libs
dograpper doctor --install --check-system-libs   # install, then check
```

## Options

```{dograpper-options} doctor
```

## Options in detail

### `--check-system-libs`

Diagnose missing chromium system libraries via `ldd`; suggests the install command. Combined with `--install`, the install runs first and the check after it
