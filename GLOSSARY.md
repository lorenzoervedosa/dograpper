# dograpper

dograpper turns downloaded HTML documentation into packed, scored context for
LLM ingestion. These are the terms used when talking about what it reads and
what it writes.

## Input

**Page**:
One source HTML file in the directory being packed.
_Avoid_: document, file (when the HTML page is meant)

**API reference page**:
A page produced by a generator from source code, documenting one or more
symbols.
_Avoid_: Javadoc page (unless the generator matters), API doc

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
class, interface, enum or trait.
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
