# dograpper drift

Compare two `llm-readiness.json` snapshots (produced by `pack --score`)
and render a human-readable **context drift report**: chunks added,
modified (grade/score transitions) and removed, plus the exact
source-file lists from `delta_manifest.json` when available. Built for
CI — it powers the [GitHub Action](../reference/github-action.md#github-action).

```bash
# Keep the previous snapshot, fully re-pack, then diff
cp ./chunks/llm-readiness.json /tmp/old-readiness.json
dograpper pack ./docs -o ./chunks --score
dograpper drift --new ./chunks/llm-readiness.json --old /tmp/old-readiness.json
```

The markdown report always starts with the `<!-- dograpper-drift -->`
marker line, which the GitHub Action uses to update its PR comment in
place instead of posting a new one.

**Caveats**: chunk ids (`docs_chunk_NN`) are positional and can be
renumbered by upstream content changes, so chunk-level drift is
best-effort; the source-file lists from `delta_manifest.json` are exact.
Snapshots from a `--delta` run are directly comparable since
[ADR-0008](https://github.com/lorenzoervedosa/dograpper/blob/main/docs/adr/0008-delta-as-a-change-gate.md) — a delta run that
fires writes a complete `llm-readiness.json`. `--delta-manifest` is
meant for local use right after a `pack --delta` run — the file on disk
reflects the *last* delta run and can be stale (or absent) if nothing
changed; the GitHub Action does not use it and derives source drift
from git instead.

## Options

```{dograpper-options} drift
```

## Options in detail

### `--delta-manifest`

`delta_manifest.json` from `pack --delta`. A missing file is tolerated (`pack --delta` does not write it when nothing changed)
