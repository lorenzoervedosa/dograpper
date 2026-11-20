# dograpper docs site — design

Date: 2026-11-20 · Status: approved 2026-11-20; revised during implementation (below)

> **Revision (2026-11-20, Task 3).** sphinx-click is replaced by a
> `dograpper-options` directive that `site/conf.py` defines. It renders a
> table from the click tree with the same cells as `dograpper docs`
> (`option_cells()` in `src/dograpper/commands/docs.py`). Why: sphinx-click
> 6.2.0 has no `:hide-header:`, its rST renders as literal text under MyST, and
> the `{eval-rst}` fallback fails `-W` (a duplicate section id, and help text
> parsed as rST). See `docs/DECISIONS.md`. The sections below describe it as
> revised.

## Intent

All user documentation lives in `README.md`: 2048 lines, 39 sections. The
`download` and `pack` sections run about 580 and 620 lines, five times their
`--help`. The maintainer finds it too verbose and wants a docs-as-code site
modeled on <https://rclone.org/docs/>: guide pages that teach how to use the
tool, and reference pages for every command and flag.

How rclone does it, for reference:
- Hugo builds the site from Markdown in `docs/content/`.
- Topic pages are hand-written.
- The command and global-flag pages are generated from the code
  (`rclone gendocs`, marked "DO NOT EDIT"), so the reference cannot drift from
  `--help`.
- Its usage page also carries hand-written `### --flag` sections (109 of them)
  for options that need more than the help line.

The work has two stages, and this design covers the first.

1. **Now: a site the maintainer builds locally.** It gets its own pages and is
   iterated on until it is good enough. The README stays as it is and remains
   the source of truth for the observable contract.
2. **Later: the cutover**, a separate project when the maintainer decides the
   site is ready. The README shrinks to a landing page, the harness points at
   the site, and hosting is decided. It is listed at the end so stage 1 doesn't
   block it.

## Goals (stage 1)

- One local command builds the whole site into static HTML the maintainer opens
  in a browser.
- One page per command:
  - prose in Markdown;
  - an options reference generated from the click tree at build time;
  - an "Options in detail" section for the options the help line does not
    fully describe.
- A generated global-options page.
- Guides, reference pages and troubleshooting, all carrying the README's
  content.
- A pytest guard that fails when a site page names a flag the CLI does not
  have, or when a command has no page.

## Non-goals (stage 1)

- Public hosting, GitHub Pages, a deploy workflow. The maintainer only needs a
  local build for now.
- Changing the README. It keeps all its content until the cutover.
- Rewriting or tightening the prose. Pages carry the README's wording, and
  tightening comes later.
- Removing or changing `dograpper docs`. It stays as the offline reference for
  the installed version.
- Publishing internal docs: `docs/adr/`, `DEBT.md`, `DECISIONS.md`,
  `superpowers/`, `audits/`, `discovery/`, `glossario.md`,
  `migration-v0.1-v0.2.md`.
- Versioned docs. Nothing is released (`docs/DECISIONS.md`, 2026-11-20).

## Anti-goals (would make this a failure even if it builds)

- A hand-written option table on the site. Tables come from click; extra detail
  goes in "Options in detail".
- A Node.js toolchain in the repo.
- Internal docs in the site's source tree.
- Every session forced to edit two copies of the docs during stage 1. The README
  stays the only maintained copy, and the site catches up at cutover (see
  "Transition").

## Constraints

- Python/uv stack. Docs tooling goes into a new optional extra `docs`, following
  the existing `dev` extra, and never becomes a runtime dependency. New
  dependencies and why:
  - `sphinx`: the site generator.
  - `myst-parser`: pages are written in Markdown.
  - `furo`: the theme.
  - ~~`sphinx-click`~~: dropped (see Revision); the options table comes from
    a directive in `site/conf.py` that reuses `dograpper docs`' cells.
- `requires-python` is `>=3.10` and `uv.lock` is universal. Recent Sphinx
  releases may require a newer Python, so the extra has to resolve under the
  lock.
- The project rules apply: all site text is in English, and every commit keeps
  `uv run pytest tests/ -q` passing (contract 5). The existing CI runs the
  drift guard, which needs neither Sphinx nor the `docs` extra.
- This work comes after the `chore/unreleased-calver` PR: the Install page
  documents installing from source only, since no release binary exists.

## Approaches

The maintainer chose all three of these in the brainstorm.

**How each command is documented.**
- (a) rclone's way for command pages: the long text lives in the click help, so
  the whole page is generated. One source, but `dograpper pack --help` would grow
  past 600 lines.
- **(b) chosen:** prose in Markdown on the site, with the generated options
  reference placed in the same page. `--help` stays short.

**Where the README's option-table detail goes.** The README's 119 option-table
rows often say more than the click help:
- `pack --manifest` climbs up to 8 levels but never above the mirror root;
- `--format md` describes the structure of the Markdown it writes;
- `--cache` defaults to 2 with a manifest, 1 without.

The options were:
- (a) Drop the rows. That loses contract detail.
- (b) Move the detail into click `help=`. That touches dozens of options in
  `src/`, makes `--help` longer, and every change needs a CHANGELOG entry.
- **(c) chosen:** an "Options in detail" section on each command page, with one
  `### --flag` subsection per option whose README text says more than its help.
  - The text is the README's, moved from a table cell into a paragraph.
  - Rows that add nothing over the help are dropped.
  - This matches rclone's hand-written `### --flag` sections.

**Site generator.**
- **A. Sphinx + MyST + Furo + sphinx-click (chosen).** Stays in uv.
  The options rendering was revised to our own `dograpper-options` directive
  (see the Revision note at the top); sphinx-click is no longer used. Search is built in and works from local files. The cost is Sphinx's
  learning curve and directive syntax inside Markdown.
- B. Docusaurus. Brings Node 20+ into a pure-Python repo, needs our own Python
  generator for the option tables, and a v4 migration is ahead.
- C. Hugo, which rclone uses. A single binary, with option tables done as a JSON
  data file plus a shortcode. The cost is Go templates and a small JSON
  generator of ours.
- Dropped:
  - MkDocs Material: its maintenance window ended on 2026-11-05.
  - Zensical: still alpha (0.0.31), with plugin support undefined.

## Decided with the maintainer

1. **Content tree**, in navigation order:
   - Home
   - Install
   - Quickstart
   - Guides: NotebookLM, RAG, incremental maintenance (CI/CD), air-gapped
   - Commands: one page each for download, pack, sync, serve, drift, eval,
     explain, init, doctor, docs
   - Reference:
     - global options (generated)
     - exit codes
     - configuration (`.dograpper.json`, `.docsignore`)
     - output and generated artifacts
     - schema v1
     - GitHub Action
   - Troubleshooting
   - Changelog
2. Prose model (b), option detail (c), generator A.
3. A local build only, with no hosting for now.
4. The README stays unchanged and is slimmed later, once the site is good
   enough.
5. Wording is kept and tightened later.
6. `dograpper docs` stays, and internal docs stay off the site.

## Design

### Layout

```
site/                          Sphinx source dir — public pages only
├── conf.py
├── index.md                   Home: the README pitch
├── install.md
├── quickstart.md
├── guides/                    notebooklm.md, rag.md, incremental.md, air-gapped.md
├── commands/<name>.md         one per click command
├── reference/                 global-options.md, exit-codes.md, configuration.md,
│                              output.md, schema-v1.md, github-action.md
├── troubleshooting.md
└── changelog.md               includes ../CHANGELOG.md
```

Our calls:

- **A new `site/` directory instead of reusing `docs/`.** Internal docs then
  cannot leak, because they sit outside the Sphinx source dir.
- **Most pages copy their text from the README** (see "Transition").
- **`CHANGELOG.md` and `docs/schema-v1.md` are included with MyST `{include}`,
  not copied.** Both are maintained as they are today, so they stay single
  source and the harness paths that name them keep working. A relative link
  inside them that breaks on the site (e.g. `schema-v1.md` links `adr/...`) is
  rewritten to its GitHub URL in the source file.
- **Guides are built from the README's "Use cases" section.**
  `docs/workflows/*.md` is in Portuguese, so it can't be included as is.
  Whatever it adds over the README goes into the English guides. The folder
  itself is left untouched, and its fate is decided at cutover.
- **The section titled "Downloader profiles" is kept on the site.** CLI
  messages and three tests name it.

### Command pages

Each page has three parts:

1. **Prose:** the README section for the command, minus its option table.
2. **`## Options`:** generated by the `dograpper-options` directive, whose
   argument is the command name:

   ````markdown
   ```{dograpper-options} pack
   ```
   ````

3. **`## Options in detail`:** the `### --flag` subsections from decision (c).

`reference/global-options.md` renders the root group with
```` ```{dograpper-options} dograpper ````, plus an "Options in detail" section
for the global flags if the README says more than their help.

### Drift guard

A new `tests/test_docs_site.py` reads the Markdown only:

- every command in `dograpper.cli.cli.commands` has `site/commands/<name>.md`,
  and every page there maps to a command;
- every command page contains exactly one `{dograpper-options}` directive
  naming its own command;
- every `### --flag` heading on a command page is an option of that command, and
  on the global-options page an option of the root group;
- every `--flag` token anywhere on the site (prose and code blocks alike) is an
  option of some command or of the root group. A page about `sync`
  legitimately cites `pack` flags, so this check is global, not per page.

### Local build

The command, run in a checkout:

```bash
uv run --extra docs sphinx-build -W --keep-going -b html site site/_build/html
```

Then open `site/_build/html/index.html`.
- `-W` turns warnings into failures: a broken cross-reference, an orphan page,
  a bad include.
- `site/_build/` goes into `.gitignore`.
- The root `CLAUDE.md` documents the command under "Como rodar localmente".
- No CI job builds the site in stage 1. *(Our call: nobody consumes the site yet,
  and the drift guard in the existing suite catches the commonest breakage.)*

### Transition: README and site side by side

In stage 1 the README stays the source of truth, and harness rules don't
change. A session that changes behaviour updates the README as today, and is
not required to update the site. Exception: if the drift guard fails on a
renamed or removed flag, that session fixes the site page.

The builder records the README commit the pages were copied from in a
`docs/DECISIONS.md` entry. At cutover, `git diff <that-commit>..HEAD -- README.md`
lists what to carry over.

The root `CLAUDE.md` gets two things now: a `site/` line in "Estrutura do
repositório" stating this rule, and the local build command.
`docs/glossario.md` gets entries for docs-as-code, Sphinx and MyST, as the
learning-glossary rule requires.

### Suggested split

1. **Scaffold PR.**
   - the `docs` extra;
   - `site/conf.py`;
   - Home;
   - one complete command page (`pack`, the largest), with prose, generated
     options and "Options in detail";
   - the drift guard, limited to the pages that exist;
   - the `CLAUDE.md` lines and `.gitignore`.

   This proves the toolchain, including the MyST directive question, and gives
   the maintainer a page to judge.
2. **Content PR.** All remaining pages.

## Left to the builder

- Furo and Sphinx configuration: title, logo, sidebar depth.
- Page titles and the section-to-page mapping for anything the tree above
  leaves ambiguous.
- Which option rows say more than their help (the call behind each `### --flag`
  subsection).
- How the Portuguese workflow notes merge into the English guides.
- The exact drift-guard regexes, including flags inside inline code.
- Whether the PR split above holds.

## Stage 2: the cutover (future, not part of this design)

Recorded so it isn't lost. Its own brainstorm decides it when the maintainer
says the site is ready.

- **Catch up and slim:** carry over the README changes made since the copy
  commit, tighten the prose, then shrink the README to pitch, install,
  quickstart, a short GitHub Action block (`action.yml` has `branding:`, so a
  future Marketplace listing shows the README), link, development and license.
- **Flip the harness:**
  - root `CLAUDE.md` rows and the maintenance table;
  - `.claude/hooks/harness-reminder.sh` and the `commit-doc-check.sh` regex;
  - `tests/test_claude_hooks.py`;
  - ADR-0012, "the site is the source of truth for the observable contract".
- **Repoint the CLI messages** that name README sections to the site:
  - `lib/httrack/policy.py:307`;
  - `commands/_httrack_profile.py:270`;
  - the `--api-records` help in `commands/pack.py:210`.

  This is a CHANGELOG entry. Three tests pin "Downloader profiles".
- **Decide hosting.** The repo is public, so GitHub Pages would serve it at
  `lorenzoervedosa.github.io/dograpper`. That needs a docs workflow and the
  Pages setting. Also decide a CI build check.
- **Decide what happens to `docs/workflows/`.**

## Risks

- **Sphinx's Python floor** may conflict with `requires-python >=3.10` in the
  universal lock.
- **Relative links in included files** (`CHANGELOG.md`, `schema-v1.md`) may
  break or trigger `-W` failures on the site.
- **Copied pages lag the README during stage 1.** The catch-up diff at cutover
  covers it, and the longer stage 1 lasts, the bigger that diff gets.
