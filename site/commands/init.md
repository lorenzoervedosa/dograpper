# dograpper init

Onboarding wizard: generates a ready-to-use `.dograpper.json` tuned for
your ingestion target. Interactive by default; `--target` + `--yes` for
scripts.

```bash
dograpper init                          # interactive wizard
dograpper init --target rag --yes       # non-interactive
```

Targets:

- **`notebooklm`** — the `--bundle notebooklm` preset (≤50 balanced `md`
  chunks), semantic strategy, context headers, readiness score, dedup.
- **`rag`** — `jsonl` records with context headers, cross-references,
  readiness score and dedup.
- **`claude-project`** — for a Claude Project (claude.ai Projects knowledge):
  compact `md` chunks (≤100k words) to upload, semantic strategy, context
  headers, readiness score and dedup.
- **`claude-code`** — for Claude Code: the
  [page layout](pack.md#page-layout---layout-page) (`layout: page`, `format: md`),
  one context header per page and `dedup: off` (dedup keeps a repeated block
  on one page only, #89). It sets no chunk-only key, so `pack` accepts it
  without a warning. It also writes a `SKILL.md` stub into `--skill-dir`:
  frontmatter `name` (from the directory name) and a `description` to fill
  in, a link to `INDEX.md`, and the grep-then-Read lookup steps.

A Claude Project and Claude Code are different targets. A Claude Project
receives uploaded files whole, so it gets a few large chunks. Claude Code
reads a local directory on demand: it finds a file by name or with `grep`
and reads a bounded slice of it, so it gets one file per page, named after
the page, plus an index.

`init` writes `SKILL.md` once and never rewrites it, even with `--force`;
`pack` never touches it either, so the description you write survives every
repack. Pack into the skill directory, then register it:

```bash
dograpper init --target claude-code --yes --skill-dir ./pz-wiki
dograpper download https://docs.example.com/ -o ./docs
dograpper pack ./docs -o ./pz-wiki                 # INDEX.md + pages/, SKILL.md kept
# edit the description in ./pz-wiki/SKILL.md, then, for every project:
mkdir -p ~/.claude/skills && ln -s "$PWD/pz-wiki" ~/.claude/skills/pz-wiki
# or for one project: ln -s "$PWD/pz-wiki" <project>/.claude/skills/pz-wiki
```

Keep the link name equal to the `name` in `SKILL.md`. `claude --add-dir
<dir>` loads skills from `<dir>/.claude/skills/`; adding the pack directory
itself only gives the session read access to its files.

Writing to a non-default path prints the `--config <path>` invocation
needed to consume it.

The generated file plugs into the standard config precedence
(defaults < `.dograpper.json` < explicit CLI flags) — any flag you pass
later still wins.

## Options

```{dograpper-options} init
```

## Options in detail

### `--yes`

Non-interactive mode (requires `--target`; exit 2 without it)
