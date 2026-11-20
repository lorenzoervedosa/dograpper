# Incremental maintenance (CI/CD)
```bash
dograpper sync <url> -o ./docs
# Incremental download + automatic delta pack
```

For a ready-made CI setup — scheduled refresh, PR drift report and
auto-commit — see the [GitHub Action](../reference/github-action.md).

## More on delta packing

Re-processing the whole documentation on every update is slow and produces
needless diffs in CI/CD pipelines. `--delta` is a change gate: it decides
whether the pack runs, not which files it packs. If nothing changed since the
last pack, it exits without writing anything. If something changed, it runs a
full pack with every artifact intact.

```bash
# First run: there is no previous state, so everything is packed
dograpper pack ./docs -o ./chunks --delta

# Later runs: a cheap no-op while the documentation is unchanged
dograpper pack ./docs -o ./chunks --delta
```

Always pack into the same output directory. The corpus state lives in
`<output-dir>/pack_state.json`, and the next run compares against it. A new
directory on every run has no baseline and always re-packs.

Files excluded by `.docsignore` or `--ignore` do not trigger the gate;
removals do.

`dograpper sync` chains the download and the delta pack in one command.

In CI, for example on GitHub Actions:

```yaml
- run: dograpper sync ${{ env.DOCS_URL }} -o ./docs --chunks-dir ./chunks --score
# Upload ./chunks to the vector DB
```

For the gate to work on stateless runners, version the chunks directory
(including `pack_state.json`) in the repository, the same premise as
[ADR-0007](https://github.com/lorenzoervedosa/dograpper/blob/main/docs/adr/0007-freshness-action-and-drift-command.md).

When a delta run fires, it writes `delta_manifest.json`, which maps the files
that were added, modified and removed and lists the chunks that were
generated. Because that run is a full pack, `chunks_generated` lists every
chunk, not only those that contain changed files.

[ADR-0008](https://github.com/lorenzoervedosa/dograpper/blob/main/docs/adr/0008-delta-as-a-change-gate.md)
records the decision and what it replaces.
