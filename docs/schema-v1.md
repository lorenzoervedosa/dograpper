# dograpper-context-v1 Schema

## Header Format

With `--context-header`, each file within a chunk begins with a metadata
block in an HTML comment; in the page layout (`--layout page`), each page
file begins with exactly one, at line 1:

```
<!-- dograpper-context-v1
{ ... JSON ... }
-->
```

The JSON is indented by 2, one field per line. Every `>` in a value is
written as the JSON escape `\u003e`, so a value holding `-->` cannot close
the comment; a JSON parser reads the original character back.

## Fields

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| title | string | no | Page title, first field. Written only in the page layout: the `<head>` `<title>` minus the site suffix that ends more than half of the run's titles, else the first `h1` of the raw page, else the file stem. |
| source | string | yes | Relative path of the source file |
| url | string | no | Original URL: the download manifest entry (the URL dograpper requested for the file; after a redirect still the requested one, never the redirect target, which may carry a signed token), else the page's HTTrack or saved-from marker (validated). Omitted when neither yields one. |
| version | string | no | Page metadata (MediaWiki pages, [#88](https://github.com/lorenzoervedosa/dograpper/issues/88)): the build the page says it was written for, from its version banner (`This page was last updated for an older version of the current build (42.10.0).` gives `42.10.0`), else its first hidden `Version X` category. The banner then leaves the page text. Omitted when the page states no version. |
| version_status | string | no | Page metadata, with `version` when it comes from the banner: `current` (revised for the current stable version), `outdated` (an older version of the current build) or `older-build` (a version of an earlier build). Omitted when the version comes from a category or is unknown. |
| chunk_index | int | no | Sub-chunk position (1-based). Omitted if file is not split. |
| total_chunks | int | no | Total sub-chunks for this file. Omitted if file is not split. |
| word_count | int | no | Word count of this chunk's content (excluding header). In `md`, the Markdown markup (heading and list markers, table pipes and delimiter row, link reference definitions) is not counted |
| context_breadcrumb | string[] | no | Heading hierarchy at chunk start. Omitted if no headings. |
| llm_readiness | object | no | Readiness metrics (present when --score is used) |
| schema_version | string | yes | Always "v1" |

### Page layout header

A page is never split, so its header (`--layout page --context-header`)
holds `title`, `source`, `url` (when known), the page metadata (`version`,
`version_status`, when known), `word_count` (the whole page) and
`llm_readiness` (with `--score`). It never holds `chunk_index`,
`total_chunks` or `context_breadcrumb`, and it carries no heading outline:
`grep -n '^#' page.md` gives the headings with their line numbers. Page
metadata fields are flat and optional, and follow `url`
([ADR-0010](adr/0010-per-page-pack-layout.md)); the chunk layout writes them
in every header of the page's sub-chunks.

```
<!-- dograpper-context-v1
{
  "title": "ActionGroup",
  "source": "ActionGroup.html",
  "url": "https://pzwiki.net/wiki/ActionGroup",
  "version": "42.10.0",
  "version_status": "outdated",
  "word_count": 105,
  "schema_version": "v1"
}
-->
```

## llm_readiness Object

| Field | Type | Description |
|-------|------|-------------|
| score | float | Composite score 0.0-1.0 |
| grade | string | "A", "B", or "C" |
| noise_ratio | float | Proportion of boilerplate removed (0.0-1.0) |

## JSONL Record Format (`--format jsonl`)

Each line of a `.jsonl` chunk file is a self-contained JSON object for one
source file (or one sub-chunk of it, when heading-driven splitting divides
a file across sub-chunks). Same `schema_version: "v1"`, but a different
field shape than the header above — JSONL is meant to be parsed
line-by-line by RAG ingestion code, not read by a human alongside the
content.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| id | string | yes | Unique record identifier. With `--api-records`: `NN_path` for a page's main container record, `NN_path#anchor` for its other records (see below). |
| source | string | yes | Relative path of the source file |
| words | int | yes | Word count of `content` |
| content | string | yes | Extracted text |
| schema_version | string | yes | Always "v1" |
| breadcrumb | string[] | no | Heading hierarchy at this position. Present with `--context-header` or `--score`, only when the source file has headings. API records always carry it: `[container]`, or `[container, member]` for a member record. |
| chunk_index | int | no | Sub-chunk position (1-based). Present only when heading-driven splitting produced more than one sub-chunk for this file. |
| total_chunks | int | no | Total sub-chunks for this file. Same condition as `chunk_index`. |
| url | string | no | Original URL. Present only with `--context-header` **and** either a matching manifest entry that has a `url` or a valid HTTrack / saved-from marker in the page head — `--score` alone never populates it, even against a matching manifest. On a member record it ends with the member's anchor, percent-encoded as the generator links it (`#%3Cinit%3E(int)`). |
| readiness_grade | string | no | Bare grade letter ("A"/"B"/"C"). Present with `--score`. Not the same shape as the header's `llm_readiness` object — see below. |
| symbol | string | no | API records only. Qualified name of the record's symbol, e.g. `zombie.characters.IsoGameCharacter#getInventory()` (Javadoc), `packaging.version.Version.is_prerelease` (Sphinx). |
| kind | string | no | API records only. `container` or `member`. |
| symbol_kind | string | no | API records only. Javadoc containers: `class`, `interface`, `enum`, `record`, `annotation`; members: `field`, `enum_constant`, `constructor`, `method`, `element` (annotation element). Sphinx containers: `module`, `class`, `exception`; members: `function`, `method` (classmethods and staticmethods too; the signature says which), `property`, `attribute`, `data` (module-level variable). |
| container | string | no | Member records only. Qualified name of the container that declares the member. |
| generator | string | no | API records only. The adapter that split the page: `javadoc` or `sphinx`. |
| version | string | no | Page metadata of a MediaWiki page, as in the header above. Present with `--context-header` or `--score`, only when the page states its version. |
| version_status | string | no | As in the header above. Same condition as `version`, and only when the version comes from the banner. |

### API records (`--api-records`)

With `pack --format jsonl --api-records`, an API reference page that a
generator adapter recognises is written as one container record followed by
one member record per documented member, in page order, instead of one
record per page ([ADR-0009](adr/0009-api-reference-symbol-records.md)). All
records of a page sit in that page's chunk. Pages that are not recognised
keep the plain record above, without the API fields.

- **Container record**: `id` `NN_path`; `content` starts with the qualified
  name and kind (`zombie.characters.IsoPlayer (class)`), then the
  inheritance chain, the type's notes (implemented interfaces, known
  subclasses, type parameters), its signature and description, one line per
  member kind listing the declared member names, and the "inherited from"
  lists. Summary tables are dropped. A nested type has its own page, so it
  gets its own container record. On a Sphinx page the first record is the
  module's (`packaging.version (module)`): the page text outside the
  objects, then the names of the top-level objects by kind; each class and
  exception record holds its signature, `Bases:` line, docstring and member
  names, and a nested class gets its own record.
- **Member record**: `id` `NN_path#anchor`, the anchor being the member's
  HTML id (`getInventory()`, `<init>(int)`); `content` starts with the
  qualified name (`zombie.characters.IsoGameCharacter#getInventory()`, a
  constructor as `Box#Box(int)`), then the full signature with its type
  parameters, the doc comment and the notes (Overrides, Specified by,
  Parameters, Returns, Throws). On a Sphinx page the anchor is the object's
  HTML id (`packaging.version.parse`); `content` starts with the qualified
  name, then every signature with its annotations (overloads included), the
  docstring and its fields (Parameters, Returns, Raises).

```json
{"id": "01_fixture/api/Box.html#of(U)", "source": "fixture/api/Box.html", "words": 37,
 "content": "fixture.api.Box#of(U)\npublic static <U extends Comparable<U>> Box<U> of(U value)\n...",
 "schema_version": "v1", "breadcrumb": ["fixture.api.Box", "of(U)"],
 "symbol": "fixture.api.Box#of(U)", "kind": "member", "symbol_kind": "method",
 "container": "fixture.api.Box", "generator": "javadoc"}
```

### Field names diverge from the header format

The header and JSONL records describe the same concepts with different
field names in three places. A consumer written against one shape will
not parse the other correctly for these fields:

| Concept | Header field | JSONL field |
|---|---|---|
| word count | `word_count` | `words` |
| breadcrumb | `context_breadcrumb` | `breadcrumb` |
| readiness | `llm_readiness` (object: `score`, `grade`, `noise_ratio`) | `readiness_grade` (bare string, grade only) |

`source`, `url`, `chunk_index`, `total_chunks` and `schema_version` are
identical between the two shapes. `id` and `content` are JSONL-only —
the header format doesn't need an id (it's inline metadata above the
content) or its own content field (it's prepended to the chunk's actual
text).

Source of truth: `src/dograpper/lib/chunker.py` (record construction),
`src/dograpper/utils/api_reference/` (API record content) and
`src/dograpper/lib/pack_reader.py` (the shape read back by `explain`,
`eval` and `serve`).

## Versioning

Future versions (v2+) will be backward-compatible. Parsers should
check `schema_version` and ignore unknown fields.
