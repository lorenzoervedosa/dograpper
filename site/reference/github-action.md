# GitHub Action

dograpper ships a composite GitHub Action (`action.yml` at the repo
root) that keeps your packed context fresh from CI: it downloads the
docs (`dograpper download`, when a `url` is given), always runs a
**full** `pack --score`, computes the drift against the previous
`llm-readiness.json` with [`dograpper drift`](../commands/drift.md#dograpper-drift), and
posts/updates a single drift report comment on the pull request. The
comment's source-file section comes from `git status` over `input-dir`
— exact lists, since the docs are versioned.

The action always runs a full `pack --score`, never `pack --delta`.
The original reason — a delta pack corrupting the snapshot — is gone
since [ADR-0008](https://github.com/lorenzoervedosa/dograpper/blob/main/docs/adr/0008-delta-as-a-change-gate.md); what remains
is that incrementality already lives at the download layer (wget
timestamping + manifest) and a full pack over unchanged sources is
deterministic, so no upstream change means an empty drift
(see [ADR-0007](https://github.com/lorenzoervedosa/dograpper/blob/main/docs/adr/0007-freshness-action-and-drift-command.md)).

It assumes **ubuntu runners** (python3, wget, `jq` and the `gh` CLI are
preinstalled) and that the docs mirror (`input-dir`, which holds the
`.dograpper-manifest.json` that `download` writes there) and the chunks
directory (with `llm-readiness.json`) are **versioned in your repo**: that is
what carries state across stateless CI runners (see
[Incremental maintenance](../guides/incremental.md)).

```yaml
name: Context freshness

on:
  schedule:
    - cron: "0 6 * * 1" # weekly refresh
  pull_request:

permissions:
  contents: write
  pull-requests: write

jobs:
  freshness:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v7

      - name: Refresh context and report drift
        id: freshness
        uses: lorenzoervedosa/dograpper@<commit-sha> # pin a commit SHA (no release tag exists yet), not a branch
        with:
          url: https://docs.example.com
          input-dir: ./docs
          chunks-dir: ./chunks
          pack-args: "--context-header"
          mode: warn # or `fail` to break the build on drift

      - name: Commit refreshed pack
        if: github.event_name == 'schedule' && steps.freshness.outputs.drift == 'true'
        run: |
          git config user.name "github-actions[bot]"
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git add ./docs ./chunks
          git diff --cached --quiet || git commit -m "chore: refresh packed context"
          git push
```

Inputs:

| Input | Default | Description |
|---|---|---|
| `url` | *(empty)* | Docs site URL. Set → `dograpper download` before packing; empty → only re-packs `input-dir` |
| `input-dir` | `./docs` | Downloaded docs directory (download output / pack input) |
| `chunks-dir` | `./chunks` | Packed chunks directory (versioned in the repo) |
| `pack-args` | *(empty)* | Extra flags appended verbatim to the pack command |
| `mode` | `warn` | `warn`: `::warning::` annotation on drift; `fail`: fail the job on drift (after posting the comment) |
| `comment` | `true` | Post/update the PR drift comment (`pull_request` events only) |
| `github-token` | `${{ github.token }}` | Token used by the `gh` CLI to post the comment |

Outputs: `drift` (`true`/`false`) and `report-path` (the markdown
report). The PR comment is upserted by matching the
`<!-- dograpper-drift -->` marker, so re-runs edit the same comment.

The manifest is left out of the comment's source-file list (it changes on
every download). Up to 0.4.0 it was written at the repo root; that file is no
longer read and can be deleted once `input-dir` holds the new one.
