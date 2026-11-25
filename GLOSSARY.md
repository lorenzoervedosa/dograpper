# dograpper

dograpper turns downloaded HTML documentation into packed, scored context for
LLM ingestion. These are the terms used when talking about what it downloads,
what it reads and what it writes.

## Download

**Mirror**:
The local copy of a site that a download writes and a pack reads.
_Avoid_: dump, crawl (the run, not its result), cache

**Downloader**:
The engine a download uses to build a mirror: `wget` (the default), `httrack`
or `fire-engine`.
_Avoid_: backend, crawler, profile (code and docs call `httrack` and
`fire-engine` "profiles"; the flag says downloader, and an `--impersonate`
profile is a browser fingerprint, not a downloader)

**fire-engine**:
The downloader that crawls as `httrack` does while presenting a browser's
network fingerprint, optionally through a proxy, for public documentation whose
firewall refuses other clients. It runs no browser.
_Avoid_: stealth mode, browser downloader, Firecrawl (the service it borrows
the name from)

**Manifest**:
The record a download keeps beside its mirror of each saved file and the URL it
came from; the next download and the pack read it.
_Avoid_: index, cache, state file (the pack keeps its own state for `--delta`)

**Update**:
A download by `httrack` or `fire-engine` into a mirror that already has a
manifest: each file the previous run saved is asked about again, or reused,
instead of being fetched blindly.
_Avoid_: update mode (an update is a kind of run, decided by the mirror's
state; the setting that tunes it is `--cache`), refresh, re-crawl

**Kept file**:
A file already in the mirror that an update left byte-identical instead of
replacing it, whether the server reported no change, the request failed or no
request was made.
_Avoid_: cached file (HTTrack's word, echoed by the run summary; dograpper
keeps no cache, the kept copy is the mirror's own), skipped file, unchanged
file (a change-report bucket)

**Link rewriting**:
Turning the links inside the files an `httrack` or `fire-engine` download saves
into ones that work in the mirror: a link to another saved file becomes a
relative path to it, any other link becomes absolute.
_Avoid_: `-K0` on its own (HTTrack's option for this mode: name the behaviour),
relinking, localising links

**Change report**:
What one download did to each file of the mirror, in four buckets: new,
changed, unchanged or gone.
_Avoid_: diff, changelog, delta (the pack's change gate), drift (the comparison
of two readiness snapshots)

**Cookie jar**:
The cookies a download sends and takes in: read from a cookies.txt file before
its first request and written back to it at its end, with every cookie the run
received (`--cookies`), or, from `--browser-login` alone, kept for the run.
_Avoid_: session (the jar is a file, not a login), cookie store, cookie file
(say which: the jar, or a browser's)

## Input

**Page**:
One source HTML file in the directory being packed.
_Avoid_: document, file (when the HTML page is meant)

**API reference page**:
A page produced by a generator from source code, documenting one or more
symbols.
_Avoid_: Javadoc page (unless the generator matters), API doc

**Redirect stub**:
A page whose only job is to send the browser elsewhere: a meta refresh with a URL
and at most 40 visible words. `pack` skips it.
_Avoid_: redirect alias (a MediaWiki page that carries its target's content)

**Generator**:
The tool that produced an API reference page, such as Javadoc, TypeDoc,
rustdoc, Sphinx autodoc or Doxygen.
_Avoid_: doc tool, framework

**Symbol**:
A named element documented on an API reference page: a module, a type, a
function or a member.
_Avoid_: entity, item, element

**Container**:
A symbol that groups other symbols, such as a package or module, namespace,
class, interface, enum or trait; or, when no code symbol declares the members,
the page that documents them, such as a Doxygen file or topic (group) page.
_Avoid_: parent, owner (as a noun for the symbol itself), type (when modules are
included)

**Member**:
A symbol inside a container, such as a method, constructor, field, constant,
module-level function or enum variant.
_Avoid_: entry, API

**Qualified name**:
The full path of a symbol written in its own ecosystem's notation, e.g.
`zombie.characters.IsoGameCharacter#getInventory()`, `click.core.Command.invoke`,
`std::vec::Vec::push`.
_Avoid_: FQN, full name, path

## Output

**Record**:
One unit of packed content with its metadata, the unit that retrieval ranks and
returns; one line of a JSONL chunk.
_Avoid_: chunk (the `serve` tool names `search_chunks` and `get_chunk` predate
this term and act on records), entry, document

**Chunk**:
One output file of a pack, the unit that is uploaded and that the word budget
applies to.
_Avoid_: part, batch, file (when the output file is meant)

**Container record**:
A record for one container, holding its qualified name, description and member
listing.
_Avoid_: type record, class record

**Member record**:
A record for one member, holding its qualified name, signature and
documentation.
_Avoid_: method record, symbol record

## Use

**Target**:
The consumer a pack is shaped for: NotebookLM, a RAG pipeline, a Claude Project
or Claude Code. A Claude Project and Claude Code are different targets: a Claude
Project receives uploaded chunks whole, while Claude Code reads files from disk
on demand and finds them by file name and exact-text search.
_Avoid_: bundle (the `--bundle` presets predate this term; each one serves a
target), destination, platform, consumer
