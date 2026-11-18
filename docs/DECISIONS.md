# Session decisions

An operational log of the decisions an agent session took on its own: a choice
between two readings of a request, a deviation from the brief, a convention
picked where the repo had none, or a question left for the maintainer. It is
more granular than an ADR and cheaper to write.

- A decision that changes architecture or an inviolable contract (CLAUDE.md)
  goes to `docs/adr/` instead; an entry here can link the ADR it led to.
- A review finding accepted without a fix goes to `docs/DEBT.md`.
- Newest entry first. Never rewrite an old entry: add a new one that
  supersedes it and say so.

Entry format:

```markdown
## YYYY-MM-DD — <topic> (#issue or PR)

- **Decision:** <what was chosen>
- **Why:** <the evidence or constraint that decided it>
- **Rejected:** <the alternatives, one line each>
- **Pending:** <what the maintainer still has to answer, or "none">
```

## 2026-11-18 — Table cells in plain text, Javadoc grids in md only (#125, #120)

- **Decision:** (#125) the plain-text renderer starts each `td`/`th` with a
  tab (private marker, turned into `\t` when the prose is rendered; a `<tr>`
  also starts a block, since `</td>` and `</tr>` may be omitted); the md
  renderer does not emit it. (#120) a Javadoc `div.summary-table` with a
  `two|three-column-summary` class is a table in md: its child divs are the
  cells, N to a row, the first row the header. The plain path keeps one cell
  per paragraph for these grids.
- **Why:** `text.split()` counts ` | ` as a word, a tab is whitespace, so
  word counts (ADR-0003) change only where gluing had merged two words. The
  grid reuses the md table frame and `_pipe_table`; the plain path has no
  frames, so one line per grid row there needs a second row tracker in the
  base class, and the issue asks for md.
- **Rejected:** ` | ` in plain text (inflates counts); a space (cells with
  several words become ambiguous); a plain-text grid renderer (follow-up if
  grep over txt/jsonl needs it).
- **Pending:** whether txt/jsonl should also get one line per Javadoc grid row.

## 2026-11-18 — Harness patterns mirrored from open-notes (#35)

- **Decision:** Phases 2–5 of the epic ship as one commit each in a single
  batch PR. Phase 1 (the `setup-matt-pocock-skills` skill) is left to the
  maintainer because it is interactive.
- **Why:** this repo's practice is one combined PR per batch of parallel
  sessions; the epic was written for one PR per phase.
- **Rejected:** one PR per phase (the batch flow already reviews them
  together).
- **Pending:** Phase 1.

- **Decision:** `block-dangerous-git.py` fails open on its own errors (bad
  JSON, an exception), unlike the open-notes original, which fails closed.
  An `--amend` whose repository it cannot tell is still blocked, as in the
  source, and so is a git command that does not tokenize (review finding):
  those are policy decisions, not errors.
- **Why:** a broken guard must never stop normal Bash work, and a hook that
  hangs is already let through by the harness timeout, so failing closed
  would only cover crashes.
- **Rejected:** fail closed (one crash would block every Bash call that
  mentions git).
- **Pending:** none.

- **Decision:** the push rule blocks any direct push to `main` or `develop`
  without user consent. There is no `GATES=green` attestation.
- **Why:** every change lands through a reviewed PR here; open-notes pushes to
  `main` after a local merge, which this repo never does.
- **Rejected:** porting the gates attestation as is.
- **Pending:** none.

- **Decision:** the living glossary is `docs/glossario.md` (pt-BR, didactic),
  separate from `GLOSSARY.md` (domain language, normative). A domain term is
  never redefined in `docs/glossario.md`; its entry points to `GLOSSARY.md`.
- **Why:** the `/explique` and `/revisao` commands read and write
  `docs/glossario.md` in a fixed format; `GLOSSARY.md` follows the
  domain-modeling format and names things in code.
- **Rejected:** merging both into `GLOSSARY.md` (two formats and two readers
  in one file).
- **Pending:** none.

- **Decision:** saved HTTP error pages (#121) are detected by `utils/error_page.py` (new module), not folded into `utils/challenge.py`; rule = `<title>` fully matches `[45]xx <reason>` AND file <= 16 KiB AND <= 40 visible words (scripts/styles dropped); wired as step 6a-1 of `pack`, a second copy of the 6a block.
- **Why:** `challenge.py` is Cloudflare-specific and shared with the httrack fetcher; the error-page rule has no fetcher use. Both layouts and `--dry-run` run after 6a, so they inherit the skip. Second copy tolerated per the project rule; a third skip class should extract the shared block.
- **Rejected:** matching "404" anywhere in the text; requiring an `<h1>` (not all servers emit one).
- **Pending:** none.
