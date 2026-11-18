# 10. A per-page pack layout for readers that navigate by file name and grep

- Status: accepted
- Date: 2026-11-17
- Issues: #83 (epic), #84 (layout and index), #85 (header), #93 (`init` preset)

## Context

Claude Code reads a pack from disk. It finds files by name (`Glob`) and by exact
text (`Grep`), then reads bounded slices. A `Read` returns about 25k tokens,
refuses a whole file above 256 KB and truncates lines over 2,000 characters
(tool limits at the time of writing). `pack` writes only numbered chunks. The
only way to get one page per file today is `--max-words-per-chunk 1
--max-chunks 100000`. That run prints one WARNING per page, uses
`docs_chunk_NNN` names, writes no index, and emits one header per paragraph
(#84, #85). The tree, file names, index line and header fields settled here
become a public interface that skills, scripts and committed packs (ADR-0007)
will depend on.

Measured on three local mirrors, one page per file with today's extraction:

| | WIKI (MediaWiki, HTTrack) | Sphinx (furo) | Javadoc 25 |
|---|---|---|---|
| HTML pages | 167 | 136 | 1,906 |
| File names with `: ? * " < > \|` | 0 | 0 | 0 |
| File names with `(` `)` / `'` / `!` | 15 / 3 / 1 | 0 | 0 |
| Case-only collisions, before or after `.html` → `.md` | 0 | 0 | 0 |
| Windows reserved names; trailing dot or space | 0 | 0 | 0 |
| Longest relative path after mapping | 45 chars | 88 | 96 |
| A page named `index` at the input root | no | no (under the host dir) | yes |
| Pages over 256 KB after extraction | 0 (max 147 KB) | 2 (max 1.46 MB) | 7 (max 727 KB) |
| Output lines over 2,000 chars | 15, in 3 pages | 0 | 237, in 214 pages |
| `<title>` ending in a shared site suffix | 167 (` - PZwiki`) | 135 of 136 | 0 (bare class name) |
| Pack time, one page per file today | 7 s | 13 s | 57 s |

The WIKI names are clean only because HTTrack rewrote them. Two of the 167
source URLs contain `:` (`Help:Style_guide`, `Help:Translations`), saved as
`Help_Style_guide.html`. `dograpper download` runs wget without
`--restrict-file-names`, and wget's Linux default (`unix`) keeps both `:` and
`?`. Every Sphinx page has 8 `<title>` elements: the first, in `<head>`, is the
page title, and the other seven are SVG icons.

## Decision

### 1. Surface

**Decision.** Add `pack --layout [chunk|page]`, default `chunk`,
config key `layout`. `sync` forwards it through `_PACK_PASSTHROUGH`.
`--format` keeps choosing only the serialization: with `page`, `md` or `txt`
sets the extension of every page file. `--layout page --format jsonl` is a
usage error (exit 2): `serve`, `eval` and `pack_reader` read
`<prefix>*.jsonl` at the root, one record per file gives the reader nothing
that `grep` lacks, and the epic leaves the JSONL schema alone. That also rules
out `--api-records` (#76), which is JSONL-only under ADR-0009.

**Alternatives.** `--format md-pages`/`txt-pages` puts two axes in one option,
doubles the format list, and spreads new values into every `fmt` branch and
into `count_chunk_tokens`. `--bundle claude-code` cannot work: a bundle is a
preset over existing settings and cannot add a layout that no flag provides. A
new subcommand would duplicate the extraction, header and sidecar wiring.

### 2. File names and tree

**Decision.** Pages go under `<out>/pages/`, mirroring their path
relative to INPUT_DIR, with the source extension replaced by the format's:
`Modding/vi.html` → `pages/Modding/vi.md`. Stems keep their original spelling,
with no slugging, because the name is the reader's main handle:
`Glob **/IsoPlayer.md` must hit `zombie/characters/IsoPlayer.html`.

Packs are committed and checked out on Windows and macOS, so these rules apply
on every system:

1. The characters HTTrack forbids (`\ : * ? " < > | ~`, C0 controls and DEL)
   become `_`. This is the set `lib/httrack/naming.py` applies, so wget and
   HTTrack mirrors get the same names (`Help:Style_guide.html` →
   `Help_Style_guide.md`).
2. A stem that is a Windows reserved name (`CON`, `PRN`, `AUX`, `NUL`,
   `COM1`–`COM9`, `LPT1`–`LPT9`, any case) gets a trailing `_`. A trailing dot
   or space also becomes `_`.
3. Collisions are resolved as in the httrack profile. The key is the
   `casefold()` of the path, and each later name gets `-2`, `-3`… before the
   extension. Names are assigned in sorted source-path order, so the same tree
   always gives the same names. A new page can still rename a colliding
   sibling, and `INDEX.md` always shows the current names.
4. There is no length rule. Only the `-N` suffix and step 2 lengthen a name,
   and the source names already fit their file system's 255-byte limit. A
   failed write is an error (exit 1), never a skip.
5. Each resolved path must stay under `<out>/pages/`, so a symlink in the
   output cannot redirect a write. `NameRegistry` already makes this
   containment check.

Steps 1, 3 and 5 are not copied: the forbidden set, the casefold `-N` rule and
the containment check move from `lib/httrack/naming.py` into one `utils/`
helper that both callers import. Step 2 is page-layout only, so the httrack
profile stays faithful to HTTrack.

**Alternatives.** Percent-encoding (`Help%3AStyle_guide.md`, wget's `windows`
mode) can be reversed, but nobody greps for it. A hash suffix is stable when
pages are added, but opaque, and 0 collisions were measured in 2,209 pages.
Keeping the source extension (`Foo.html.md`) never collides, but
`Glob **/Foo.md` misses it. NFC normalization in the collision key matters on
APFS, but no non-ASCII names were measured.

### 3. Index file

**Decision.** Write one `<out>/INDEX.md` next to `pages/`. Since no
page sits at the root, no page can collide with the index or with a sidecar
(`llm-readiness.json`, `cross_refs.json`, `pack_state.json`…). At the root,
Javadoc's `index.html` would become `index.md`, the same file as `INDEX.md` on
NTFS and APFS. Two header lines come first, then one line per page sorted by
output path:

```
# Index
167 pages. One line per page: - [title](<path>), N words, URL

- [ActionGroup](<pages/ActionGroup.md>), 599 words, https://pzwiki.net/wiki/ActionGroup
- [Help:Style guide](<pages/Help_Style_guide.md>), 4273 words, https://pzwiki.net/wiki/Help:Style_guide
- [Bản Mod](<pages/Modding/vi.md>), 3130 words, https://pzwiki.net/wiki/Modding/vi
```

- **Path.** Relative to `INDEX.md`, in a CommonMark angle-bracket
  destination. Parentheses need no escaping (15 WIKI names have them), the
  text is exactly the path `Read` takes, and step 1 rules out `<` and `>`.
- **Title.** The header title from point 4. It is untrusted page content, so
  whitespace is collapsed, controls are neutralized (`utils/redact.py`), and
  `\`, `[` and `]` are backslash-escaped.
- **URL.** Written only when known (`lib/source_urls.py`). It is validated and
  never contains a space, so a regex can split the line.
- New fields (such as the page version from #88) are only ever appended. The
  index is written on every page-layout run, with or without
  `--context-header`.

**Alternatives.** A Markdown table needs `|` escaped in titles and gives `grep`
nothing extra. `INDEX.tsv` or `index.jsonl` parse more easily, but they are
harder to read and `SKILL.md` cannot link them as Markdown. One index per
directory means more files to find, when one `grep -i term INDEX.md` already
answers "which page".

### 4. Per-page header (#85)

**Decision.** Use the same `<!-- dograpper-context-v1 ... -->`
comment, `schema_version` `"v1"`, with JSON indented by 2 so that each field is
one greppable line. It is written only with `--context-header`, exactly once
per file, starting at line 1.

| Field | In the page layout |
|---|---|
| `title` | New, optional. The `<head>` `<title>` minus the site suffix. Fallback: the first `h1` of the raw page, read before extraction, so MediaWiki's `h1#firstHeading` counts even though it sits outside the extracted container (G4, #85). Last resort: the file stem. |
| `source`, `url`, `word_count`, `llm_readiness` | Unchanged (`url` from `lib/source_urls.py`) |
| page metadata | Flat optional fields defined by #88 (e.g. `version`) |
| `chunk_index`, `total_chunks` | Never written: pages are not split |
| `context_breadcrumb` | Never written: it is the heading path at a chunk offset, which means nothing at the top of a whole page |

**Site suffix.** The text after the last ` - `, ` – `, ` — ` or ` | ` of
`<title>` is dropped when that exact suffix ends more than half of the run's
titles (WIKI 167 of 167, Sphinx 135 of 136, Javadoc 0). A per-page rule would
cut real titles that contain ` - `. A config option would add a setting with
no measured need.

**No heading outline.** Size of the headers over the size of the page bodies,
estimated with `title`, `source`, `url` and `word_count`:

| Header | WIKI | Sphinx | Javadoc |
|---|---|---|---|
| without an outline | 2.4% | 1.3% | 3.2% |
| with an `h1`–`h2` outline | 3.7% | 4.9% | 5.5% |
| with the full outline | 4.6% | 5.1% | 17.4% |

The full outline breaks #85's 5% budget on Javadoc (median 18 headings per
page, max 3,850). It also repeats the body: once #87 renders headings as `#`
lines, `grep -n '^#' page.md` returns the outline with the line numbers that a
`Read` with an offset needs. The bodies were measured before #88 removes the
navboxes (36% of WIKI words). After that, the header without an outline is
about 3.8% on WIKI.

**Escaping.** `json.dumps` leaves `>` alone, so a title or heading that
contains `-->` would close the comment. The writer emits `>` as `\u003e`, a valid JSON escape, so no value can close the comment.
Today's breadcrumbs have the same problem, so this applies to every v1 header.

**Schema.** The schema stays at v1. `title` is new and optional, every field
left out was already optional, and readers ignore unknown fields (the
"Versioning" section of `docs/schema-v1.md`). The JSONL-only fields of #76
(`symbol`, `kind`, `symbol_kind`, `container`, `generator`) do not overlap
with these, and a future JSONL title would use the same name. Without
`--context-header`, a page file holds only its content, with no
`<!-- SOURCE -->` line and no file list.

**Alternatives.** YAML front matter would be a second header syntax for the
same fields, need a new parser in `chunk_inspector`, and mean nothing in
`txt`. `dograpper-context-v2` would only break readers, since no field changes
meaning. For the outline as #85 asks, see the table above and question 6.

### 5. Interactions

"Set" means set on the CLI or in `.dograpper.json`; a default never triggers an
error. Internally the layout makes one `Chunk` per page, so scoring,
cross-refs, delta and token counting keep their code paths; only the naming and
the writer change.

| Flag | With `--layout page` | Why |
|---|---|---|
| `--max-words-per-chunk`, `--max-chunks`, `--strategy`, `--prefix`, `--with-index/--no-index` | exit 2 when set | No effect in this layout; ignoring them would be silent |
| `--bundle` (either preset) | exit 2 | Presets serve chunk targets; `IMPORT_GUIDE.md` lists chunks |
| `--for-queries` | exit 2 | No co-location with one file per page; the index is sorted by path |
| `--dedup exact\|fuzzy\|both` | exit 2 | A page read alone loses blocks that dedup kept only on another page (#89) |
| `--format jsonl`, `--api-records` | exit 2 | Point 1 |
| `--delta` | allowed | The ADR-0008 gate is unchanged; a run that passes it rebuilds `pages/` in full |
| `--context-header` | allowed | One header per file (point 4) |
| `--cross-refs` | allowed | Marker `[-> pages/Target.md]`, relative to the root as in `INDEX.md`; `cross_refs.json` keyed by page path |
| `--score`, `--report` | allowed | One score per page; `chunk_id` holds the page path, which is stable across runs, so `drift` compares pages |
| `--show-tokens`, `--dry-run`, `--manifest`, `--ignore*`, `--include-extensions`, `--no-extract` | unchanged | |
| `serve`, `eval`, `explain` | not supported | They already exit 1 when there are no `<prefix>*` chunk files |

**Who owns `pages/`.** Each run that writes builds the whole tree in a sibling
temporary directory, then swaps it in. A failed run leaves the old pages in
place, as ADR-0008 requires for its state. Removed and renamed pages do not
survive, so `grep` never hits a stale page. If `pages/` exists without
`INDEX.md`, it is not a previous output, and the run exits 1 before writing.

### 6. Very large pages

**Decision.** Never split pages and never wrap lines. The reader
runs `grep -n`, then a `Read` with an offset and limit. Pages over 256 KB
number 0, 2 and 7 across the three corpora. The largest, a 1.46 MB Sphinx page,
has 231,943 lines, none over 547 characters, so all of it can be reached by
line number.

The real precondition is line length, not size. Javadoc has 237 lines over
2,000 characters (the longest, 22,680, is in `IsoDummyCameraCharacter.html`);
WIKI has 15 (the longest, 17,982, is in `Item_tag.html`). `Read` truncates
these lines, although `grep` still matches them. They are inherited-member
lists and one table cell, so shortening them belongs to the extraction (#87:
one table row per line) and to the ADR-0009 adapters, not to the layout. #84's
acceptance run reports the count.

**Alternatives.** Splitting at 256 KB (`Foo.part2.md`) breaks name = page, a
hit in part 2 comes without the header, and offset reads already reach every
line. Hard-wrapping breaks phrase matches across the wrap and changes the text.

### 7. Skill skeleton (#93)

**Decision.** The skill skeleton is not part of this layout. The
layout guarantees what a skill needs: `INDEX.md` and `pages/` at fixed relative
paths. `pack` never writes, rewrites or deletes a root file it does not own,
and it owns only `INDEX.md`, `pages/` and its sidecars, so a `SKILL.md` in the
output directory survives every repack.

#93 decides who creates the file (`init --target claude-code`, or `pack` only
when it is missing). Its description needs human wording, so it must never be
regenerated over edits. The two decisions meet only at the directory name.
#93 proposes `references/`, while `pages/` is the GLOSSARY term. This ADR
recommends `pages/`, which means amending #93's "under `references/`".

## Consequences

- New public surface: `--layout`, the `layout` key, the `pages/` tree, the
  `INDEX.md` line and the `title` field. Changing any of them later breaks
  committed packs.
- G4 stays open for the chunk layout; in the page layout, body headings answer
  it once #87 lands.
- `serve`, `eval`, `explain` and the Action remain chunk-layout only. Mixing
  layouts in one output directory is unsupported, because `pack` never deletes
  root chunk files.

## Review

The maintainer accepted every decision above as proposed on 2026-11-17:
`pages/` rather than `references/`, `--dedup` other than `off` is a usage
error in the page layout, and the header carries no heading outline.
