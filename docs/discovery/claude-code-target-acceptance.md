# Claude Code target acceptance run (epic #83)

> Discovery, 2026-11-18. Question: does the shipped Claude Code preset meet the
> acceptance criteria of epic #83 on the WIKI and Javadoc corpora? Measured at
> `23f2f5d` (dograpper 0.4.0), with the Claude Code 2.1.327 `Read` tool.

## Verdict

**Three of the four criteria pass. The large-file criterion fails.**

- All 32 curated lookups were answered with a `file:line` citation, at 1.56
  tool calls per lookup. 30 of them stayed within one grep plus one `Read`.
- Pages are never split, and pack time is at most 1.23x the baseline.
- Three of the 22 files over 256 KB contain a line that no `Read` call can
  return, at any offset (`Item_tag.md`, `IsoPlayer.md`, `IsoAnimal.md`). The
  cause is the length of link lists in the Markdown output (F1).

## Method

**Packs.** `dograpper init --target claude-code --yes`, run in a scratch
directory, wrote this config:

```json
{"download": {"depth": 3},
 "pack": {"layout": "page", "format": "md", "context-header": true, "dedup": "off"}}
```

Each corpus was packed with `dograpper --config <that file> pack <mirror> -o <out>`.
The baseline is `dograpper pack <mirror> -o <out>` with every default (chunk
layout). Both were run twice, one after the other, on the same machine
(24 cores, WSL2) with `/usr/bin/time`. Other agents were working on the machine
at the same time, so the timings are noisy.

**Corpora** (local mirrors, read-only):

- WIKI: 168 files (167 HTML), HTTrack mirror of the pzwiki.net modding pages,
  with `<!-- Mirrored from <url> -->` markers.
- Javadoc: 1,948 files (1,906 HTML), HTTrack mirror of the game's Javadoc 25
  output.
- The optional Sphinx corpus was not run.

**Lookups.** For each corpus, 16 questions a mod developer would ask were
picked from the source HTML, with text dumped from the mirror and not from the
pack. Each question was written down with its expected answer and source page
before the packs were searched.

**Answering.** The lookups used only these tools: ripgrep over the pack (the
engine behind Claude Code's `Grep`, including its `glob` filter), a name lookup
(`Glob`), and the `Read` tool with `offset` and `limit`. Each lookup started
from `INDEX.md` or from a grep. Search terms came from the question, not from
the expected answer, with one slip recorded under W7. Every tool call was
counted. The budget is one grep or glob plus one `Read`. A lookup is a hit
when the expected answer is at the cited `file:line`. For display, grep output
lines were cut to 200 to 300 characters.

## Corpus stats

| | WIKI | Javadoc |
|---|---|---|
| Source files (HTML) | 168 (167) | 1,948 (1,906) |
| Skipped by `pack` | 1 `.json` (non-doc filter), 5 redirect aliases | 42 assets (non-doc filter), 1 bot-challenge page (`IsoHeatSource.html`, title "Just a moment...") |
| Page files / `INDEX.md` lines | 162 / 162 | 1,905 / 1,905 |
| `INDEX.md` lines with a URL | 162 (all from page markers) | 1,904 (1 without: `script-files/module-summary.html`, a saved 404 page) |
| Total words | 122,713 | 1,355,925 |
| Total size of `pages/` | 1.49 MB | 37.4 MB |
| Largest file | 501,362 B, `pages/Item_tag.md` | 1,839,224 B, `pages/index-files/index-7.md` |
| Files over 256 KB | 1 | 21: 16 `index-files/index-N.md`, `ModelKey`, `SoundKey`, `IsoGameCharacter`, `IsoPlayer`, `IsoAnimal` |
| Context headers | 162: one per file, at line 1 | 1,905: one per file, at line 1 |
| Lines over 2,000 chars (files) | 42 (2) | 586 (319) |
| ...of them in files over 256 KB | 41 | 21 |
| Longest line | 60,413 chars, `Item_tag.md:189` | 115,338 chars, `RandomizedBuildingBase.HumanCorpse.md:119` |
| Lines no `Read` call can return (46,523 chars or more) | 2 | 7, plus 12 between 43,036 and 43,844 chars (not measured) |

**Pack time** (seconds, run 1 / run 2; maximum RSS in parentheses):

| | Preset (`--layout page`) | Baseline (chunk defaults) | Ratio |
|---|---|---|---|
| WIKI | 7.68 / 8.58 (49 MB) | 6.51 / 6.98 (49 MB) | 1.18 / 1.23 |
| Javadoc | 56.69 / 61.44 (104 MB) | 60.33 / 79.59 (58 MB) | 0.94 / 0.77 |

The baseline wrote one 1.46 MB chunk for WIKI and three chunks of 10 to 13.5 MB
for Javadoc.

**What `Read` did with long lines (measured).** Single-line `Read` calls
(`limit: 1`) were refused with "exceeds maximum allowed tokens (25000)" on
`Item_tag.md:204` (46,523 chars, 27,103 tokens), `Item_tag.md:189` (60,413
chars, 35,129 tokens) and `IsoPlayer.md:3119` (89,497 chars, 47,388 tokens). A
2,106-char line (`ServerChatMessage.md:47`) came back whole. ADR-0010 assumed
that `Read` truncates lines over 2,000 characters, but this version did not
truncate. The limit that applied was the 25k-token cap on each call, and a
`Read` cannot start in the middle of a line. These links are 1.7 to 1.9
characters per token, so a line longer than about 43k to 46k characters can
never be read.

## Lookups

### WIKI (16)

| # | Question | Expected answer (source page) | Calls | Result | `file:line` |
|---|---|---|---|---|---|
| W1 | Which parameters does `map.info` take? | title, description, lots, fixed2x, zoomX, zoomY, zoomS, demoVideo (`Map.info.html`) | 2: grep `INDEX.md`, Read | hit | `pages/Map.info.md:32-41` |
| W2 | Which `mod.info` parameters are needed at minimum, and how is `require=` written? | "at least be the ID and name"; `require=otherModID,anotherModID` (`Mod.info.html`) | 2: grep `INDEX.md`, Read | hit | `pages/Mod.info.md:17`, `:36` |
| W3 | Which event fires right after `OnInitWorld` when a game loads? | `OnLoadedTileDefinitions`, after "Sandbox Options loaded here" (`Lua_event.html`) | 2: grep, Read | hit | `pages/Lua_event.md:61-63` |
| W4 | How do I unhook a function from an event? | `Events.OnCreatePlayer.Remove(yourFunction)` (`Lua_event.html`) | 2: grep, Read | hit | `pages/Lua_event.md:33` |
| W5 | Which items count for tag `base:canopener`? | Can Opener, Can Opener - Old-Fashioned, Handiknife, Multitool, P38 Can Opener, Sheet Metal Snips (`Item_tag.html`) | 2: grep, Read with offset (501 KB file) | hit | `pages/Item_tag.md:73` |
| W6 | Which parameters does a sandbox option of type `enum` take? | `type = enum`, `default = <value>`, `numValues = <number>` (`Sandbox_options.html`) | 2: grep, Read | hit | `pages/Sandbox_options.md:99-101` |
| W7 | Which startup parameter sets the mod folders and their load order? | `-modfolders workshop,steam,mods` (`Startup_parameters.html`) | 2: grep `load order`, Read; +1 slip (a first grep used the answer term) | hit; two examples glued together (F2) | `pages/Startup_parameters.md:115` |
| W8 | How do I sync an item's mod data in multiplayer? | `syncItemModData(player, item)`, server only (`Mod_data.html`) | 2: grep `INDEX.md`, Read | hit | `pages/Mod_data.md:39` |
| W9 | What arguments does an `OnClientCommand` handler get? | `(module, command, playerObj, args)` (`Networking.html`) | 2: grep, Read | hit | `pages/Networking.md:100` |
| W10 | Which `craftRecipe` key makes a recipe require learning? | `needTobeLearn = true` (`CraftRecipe.html`) | 3: grep, Read at the wrong offset, Read | hit, over budget (reader error: the grep line already held the answer) | `pages/CraftRecipe.md:345` |
| W11 | What is the key ID of `Keyboard.KEY_F11`? | 87 (`Keyboard.html`) | 1: grep | hit | `pages/Keyboard.md:118` |
| W12 | How much real time is one in-game hour by default? | 00:02:30 (`Game_time.html`) | 2: grep `INDEX.md`, Read | hit | `pages/Game_time.md:40` |
| W13 | Which distribution argument ignores zombie density for spawns? | `ignoreZombieDensity` (`Procedural_distributions.html`) | 1: grep | hit | `pages/Procedural_distributions.md:104` |
| W14 | Which file format do translation files use since 42.15.0? | `.json`, with no language code in the name (`Translation.html`) | 2: grep `INDEX.md`, Read | hit | `pages/Translation.md:21` |
| W15 | Which values does vehicle `mechanicType` take? | 0 Burnt, 1 Standard, 2 Heavy Duty, 3 Sport (`Vehicle_(scripts).html`) | 1: grep | hit | `pages/Vehicle_(scripts).md:71` |
| W16 | Which containers does room `gasstore` have? | counter, freezer, fridge, other, shelves, shelvesmag (`Room_definitions_and_item_spawns.html`) | 2: grep, Read | hit | `pages/Room_definitions_and_item_spawns.md:173` |

WIKI: 16 of 16 hits, 30 calls (1.88 per lookup; 1.94 counting the slip), 15 of
16 within budget.

### Javadoc (16)

Grep was scoped to a class with ripgrep's glob filter (`-g '**/IsoCell.md'`),
which matches Claude Code's `Grep` `glob` parameter, so no package path had to
be known. Signature lines start at column 0, so `^public .* name\(` finds a
member's signature. A grep for the phrase `ReturnType name(` does not (F3).

| # | Question | Expected answer (source page) | Calls | Result | `file:line` |
|---|---|---|---|---|---|
| J1 | Signature of `IsoPlayer.getInventory`? | `public ItemContainer getInventory()`, declared in `IsoGameCharacter` (`zombie/characters/IsoGameCharacter.html`) | 3: grep `IsoPlayer.md` (the only hit is the 89,497-char inherited-member list at `:3119`, F1), grep `IsoGameCharacter.md`, Read | hit, over budget (inherited member) | `pages/zombie/characters/IsoGameCharacter.md:9999` |
| J2 | Overloads of `ItemContainer.AddItem`? | `(InventoryItem item)` and `(String type)` return `InventoryItem`; `(String type, float useDelta)` and `(..., boolean synchSpawn)` return `boolean` | 1: grep | hit | `pages/zombie/inventory/ItemContainer.md:2099`, `:2115`, `:2123`, `:2127` |
| J3 | How do I get `GameTime` and the current hour? | `public static GameTime getInstance()`, `public int getHour()` | 1: grep | hit | `pages/zombie/GameTime.md:1205`, `:1541` |
| J4 | Return type of `IsoGridSquare.getObjects`? | `PZArrayList<IsoObject>` | 1: grep | hit | `pages/zombie/iso/IsoGridSquare.md:5671` |
| J5 | Overloads of `IsoCell.getGridSquare`? | `(double, double, double)`, `(Double, Double, Double)`, `(int x, int y, int z)`, all returning `IsoGridSquare` | 1: grep | hit | `pages/zombie/iso/IsoCell.md:3031`, `:3063`, `:3067` |
| J6 | How many arguments can `LuaEventManager.triggerEvent` pass? | 9 overloads: the event plus up to 8 `Object` params, `public static void` | 1: grep | hit | `pages/zombie/Lua/LuaEventManager.md:463-515` |
| J7 | Signature of `InventoryItem.getFullType`? | `public String getFullType()` | 1: grep | hit | `pages/zombie/inventory/InventoryItem.md:4353` |
| J8 | How do I get a vehicle part by id? | `public VehiclePart getPartById(String id)` (`VehicleParts`; `BaseVehicle` gets it from `VehiclePartOwner`, which is not mirrored) | 1: grep over `pages/zombie/vehicles/` | hit | `pages/zombie/vehicles/VehicleParts.md:327`; `BaseVehicle.md:4057` |
| J9 | Signature of `SandboxOptions.getOptionByName`? | `public SandboxOptions.SandboxOption getOptionByName(String name)` | 1: grep | hit | `pages/zombie/SandboxOptions.md:2177` |
| J10 | Superclass chain of `IsoZombie`? | Object > GameEntity > IsoObject > IsoMovingObject > IsoGameCharacter > IsoZombie | 2: grep, Read | hit | `pages/zombie/characters/IsoZombie.md:13`, `:19` |
| J11 | Which package holds `ItemContainer`? | `zombie.inventory` | 1: glob | hit | `pages/zombie/inventory/ItemContainer.md` |
| J12 | Value of `GameServer.MAX_PLAYERS`? | 512 (`constant-values.html`) | 2: grep, Read | hit | `pages/constant-values.md:8671` (name), `:8673` (value) |
| J13 | Constants of `MoodleType`? | 26, `ENDURANCE` to `FOOD_EATEN` | 1: grep `^#+ ` | hit (it is a class with static fields, not a Java enum as the question said) | `pages/zombie/scripting/objects/MoodleType.md:189-289` |
| J14 | Static accessor for the local `IsoPlayer`? | `public static IsoPlayer getInstance()` | 1: grep | hit | `pages/zombie/characters/IsoPlayer.md:4343` |
| J15 | Overloads of `ZombRand`? | `public static double ZombRand(double max)` and `ZombRand(double min, double max)`, in `LuaManager.GlobalObject` | 1: grep over all pages | hit | `pages/zombie/Lua/LuaManager.GlobalObject.md:4647`, `:4655` |
| J16 | Return type of `IsoGameCharacter.getStats`? | `Stats` | 1: grep | hit | `pages/zombie/characters/IsoGameCharacter.md:10455` |

Javadoc: 16 of 16 hits, 20 calls (1.25 per lookup), 15 of 16 within budget.

**Both corpora:** 32 of 32 hits, 50 calls (1.56 per lookup; 1.59 counting the
W7 slip), 30 of 32 within budget. For comparison, the hand-built reference in
the epic answered 10 of 10 lookups at 1.7 calls per lookup.

## Criteria

| Criterion (epic #83, "Acceptance") | Result | Evidence |
|---|---|---|
| WIKI and Javadoc corpora, about 10 to 20 curated lookups each | **pass** | 16 + 16, chosen from the source pages before the packs were searched |
| Each lookup answered by one grep plus one `Read` of at most 25k tokens | **pass, with 2 overruns** | 32 of 32 answered; 30 of 32 within budget. W10 was a reader error. J1 needed a second grep because the member is inherited. Neither overrun comes from a pack defect |
| Pages are not split | **pass** | Page files = `INDEX.md` lines = source HTML minus the documented skips (162; 1,905). Every file has exactly one header, at line 1 |
| A file above 256 KB stays readable with `grep -n` plus a `Read` with offset and limit | **fail** | 3 of 22 such files contain a line that no `Read` returns: `Item_tag.md:189` and `:204`; `IsoPlayer.md:3119`; `IsoAnimal.md:1573` (F1). In the other 19 files (16 `index-files` pages, `ModelKey`, `SoundKey`, `IsoGameCharacter`), the longest line is 30,909 chars (`IsoGameCharacter`), below the shortest refused line; that line was not read |
| Pack time at most 2x the baseline | **pass** | Highest ratio 1.23 (WIKI); Javadoc 0.77 to 0.94 |

## Findings

Defects are filed here only, and nothing was fixed. The maintainer decides on
follow-ups.

- **F1. Link markup makes lines too long to read, which fails the large-file
  criterion.** Every link keeps its full destination, so lists of links become
  very long lines: Item_tag rows such as `[Can Opener](https://pzwiki.net/wiki/Can_Opener)`,
  and Javadoc "Methods inherited from class X" lists such as `[name](<X.html#name(args)>)`.
  Link destinations are 68% of `Item_tag.md` (501,362 B, or 161,494 B without
  them) and 73% of `IsoPlayer.md:3119` (89,497 chars, or 23,832 without them).
  ADR-0010 measured the same corpora before the Markdown output existed: WIKI
  had a longest line of 17,982 chars, 15 lines over 2,000 chars and a largest
  page of 147 KB. Javadoc had a longest line of 22,680 chars, 237 lines over
  2,000 chars and 7 pages over 256 KB. Now the figures are 60,413, 42 and
  501 KB for WIKI, and 115,338, 586 and 21 for Javadoc. Grep still matches
  these lines, but 2 WIKI lines and at least 7 Javadoc lines cannot be read at
  all. J1 is an example: its grep landed on such a line. Possible directions
  are dropping or shortening link destinations inside long link lists, or one
  list item per line. Choosing between them is a design decision.
- **F2. `<br>` produces no separator, so the text on either side runs
  together.** `pages/Startup_parameters.md:115` reads
  `-modfolders workshop,steam,mods-modfolders workshop,steam`, and `:126`
  reads `-debuglog=All-debuglog=Network,Sound`. In the source, these are two
  `<code>` examples separated by `<br/>` in one table cell. In the WIKI source,
  45 table cells in 4 pages (`Fliers`, `Startup_parameters`, `Steam`,
  `Vehicle_zones`) have a `<br>` between content. `br` is not in `BLOCK_TAGS`
  in `utils/html_stripper.py`, and the Markdown writer emits nothing for it.
  Grep for the first value still matches, but the glued text is wrong.
- **F3. Links inside Javadoc signatures break phrase grep.** A signature is
  written as `public [ItemContainer](../inventory/ItemContainer.html) getInventory()`,
  so `rg 'ItemContainer getInventory'` finds nothing. 21,272 of the 52,441
  signature lines (41%) contain a link. The lookups worked around it with
  `^public .* name\(`.
- **F4 (minor). In-page links point to source `.html` names.** For example,
  `[translation](Translations.html)` at `pages/Map.info.md:43` names a redirect
  alias that `pack` skipped. That affects 642 lines in WIKI and 117,658 in
  Javadoc. The preset does not turn on `--cross-refs`. No lookup depended on
  following a link.
- **F5 (minor, MediaWiki cleanup).** 143 of 162 WIKI pages end with an empty
  `## Navigation` heading: the navbox is removed but its heading stays. Also,
  294 red links (`index.php?title=...&action=edit&redlink=1`) remain in 34
  pages, for example `pages/Vehicle_(scripts).md:71`.
- **F6 (minor).** Javadoc 25 summary grids (`div`-based, not `<table>`) come
  out one cell per paragraph. A grep hit on a constant or member name in a
  summary therefore never carries its type or value on the same line: J12
  needed a `Read` to get from `:8671` to `:8673`.
- **F7 (download side, not blocking).** `script-files/module-summary.html` in
  the Javadoc mirror is a saved 404 page. It is packed as "404 Not Found"
  (14 words) and has no URL.

Not checked: the Sphinx corpus, how Claude Code's `Grep` tool displays lines
over 2,000 characters, and whether the 12 Javadoc lines between 43,036 and
43,844 chars fit in one `Read`.
