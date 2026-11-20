# Configuration

Create a `.dograpper.json` file at the project root to avoid repeating flags:

```json
{
  "download": {
    "depth": 3,
    "include-extensions": "html,md",
    "manifest": ".dograpper-manifest.json"
  },
  "pack": {
    "max-words-per-chunk": 400000,
    "max-chunks": 50,
    "strategy": "semantic",
    "format": "md",
    "with-index": true,
    "context-header": true,
    "score": true,
    "dedup": "both"
  }
}
```

**Precedence**: code defaults → `.dograpper.json` → CLI flags.
CLI flags always win. Internally this uses Click's
`ctx.get_parameter_source()` to distinguish implicit defaults from
explicit values.

Use `--config` to point to a different file:

```bash
dograpper --config ./projects/rust/.dograpper.json pack ./rust-docs -o ./chunks
```

## `.docsignore` file

Create a `.docsignore` at the project root to exclude files from the
pack (gitignore syntax):

```text
# Images
*.png
*.jpg
*.gif
*.svg

# Binaries
*.pdf
*.zip
*.tar.gz

# Unwanted pages
**/404.html
**/changelog/**
```

The file can be customized via `--ignore-file` or complemented with
inline `--ignore` (repeatable).

Binary and image extensions (`.png`, `.jpg`, `.gif`, `.svg`, `.pdf`,
`.zip`, `.tar.gz` and similar) are skipped automatically, unconditionally
— they don't need `.docsignore` entries. Use it for pages and paths that
are still text but you don't want packed.
