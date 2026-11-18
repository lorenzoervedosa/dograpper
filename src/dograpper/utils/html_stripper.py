"""HTML Stripping utility.

``strip_html`` writes plain text, one paragraph per block, with ``<pre>`` blocks
fenced (#86). With ``markdown=True`` (md output, #87) it also writes headings,
links, lists and tables as Markdown.
"""

from collections import Counter
from html.parser import HTMLParser
from itertools import chain, groupby
from urllib.parse import quote, unquote
import re
import html

from .code_fence import code_span, fence
from .redact import neutralize_controls

BLOCK_TAGS = frozenset({
    "p", "div", "section", "article", "main",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "tr", "blockquote", "pre", "ul", "ol",
    "table", "dl", "dt", "dd", "figcaption", "figure", "hr",
})

# What <br> leaves in the text until the prose is rendered: \s does not match it, so
# whitespace collapsing keeps it. A page's own U+E000 is replaced by U+FFFD on the way in.
_BR = "\ue000"

# Classes naming a code block's language: MediaWiki (mw-highlight-lang-*),
# Prism / highlight.js (language-*), lang-* and Sphinx (highlight-*). The name
# becomes the fence's info string, so it is limited to characters that cannot
# break the fence.
_LANG_CLASS = re.compile(r"(?:mw-highlight-lang-|language-|lang-|highlight-)([\w#+.-]+)")
# Placeholders that name no language: Sphinx highlight-default, highlight-none
# and Prism language-none.
_NO_LANGUAGE = frozenset({"default", "none"})


def _code_language(attrs) -> str:
    for cls in (dict(attrs).get("class") or "").split():
        match = _LANG_CLASS.fullmatch(cls)
        if match and match.group(1) not in _NO_LANGUAGE:
            return match.group(1)
    return ""


class _Verbatim(str):
    """A block in parser output that is already rendered, kept out of the whitespace collapse."""


class _Code(_Verbatim):
    """A fenced ``<pre>`` block."""


class _Heading(_Verbatim):
    """A Markdown heading line; ``level`` and ``text`` (without markup) name it."""


class _Block(_Verbatim):
    """A rendered Markdown table."""


class _Link(str):
    """A rendered link inside prose; ``text`` is the link text alone."""


class PreCapture:
    """Collects the text of the outermost ``<pre>`` verbatim.

    Its language comes from the ``<pre>``, else a ``<code>`` inside it, else
    the nearest enclosing ``<div>`` that names one (MediaWiki puts it on the
    parent, Sphinx on the grandparent).
    """

    def __init__(self):
        self.depth = 0
        self._parts = []
        self._lang = ""
        self._div_lang = ""
        self._div_langs = []

    def starttag(self, tag, attrs):
        if tag == "div":
            self._div_langs.append(_code_language(attrs))
        elif tag == "pre":
            self.depth += 1
            if self.depth == 1:
                self._parts = []
                self._lang = _code_language(attrs)
                self._div_lang = next((lang for lang in reversed(self._div_langs) if lang), "")
        elif tag == "code" and self.depth and not self._lang:
            self._lang = _code_language(attrs)

    def data(self, d):
        self._parts.append(d)

    def endtag(self, tag):
        """The fenced block when ``tag`` closes the outermost ``<pre>``, else None."""
        if tag == "div" and self._div_langs:
            self._div_langs.pop()
        elif tag == "pre" and self.depth:
            self.depth -= 1
            if not self.depth:
                # HTML drops the newline right after <pre>; trailing blank lines carry nothing.
                code = "".join(self._parts).strip("\n").rstrip()
                if code:
                    return _Code(fence(code, self._lang or self._div_lang))
        return None

    def close(self) -> list:
        """Output parts for a ``<pre>`` still open at the end of the document,
        so its text is kept rather than lost."""
        if not self.depth:
            return []
        self.depth = 1
        code = self.endtag("pre")
        return [code] if code else []


class HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = []
        self.ignore = False
        self.ignore_tags = {'script', 'style'}
        self.pre = PreCapture()

    def handle_starttag(self, tag, attrs):
        if tag in self.ignore_tags:
            self.ignore = True
        elif tag == "br" and not self.ignore and not self.pre.depth:
            self.text.append(_BR)
        self.pre.starttag(tag, attrs)

    def handle_endtag(self, tag):
        if tag in self.ignore_tags:
            self.ignore = False
        elif not self.ignore:
            code = self.pre.endtag(tag)
            if code:
                self.text.append(code)
            if tag in BLOCK_TAGS and not self.pre.depth:
                self.text.append("\n\n")

    def handle_data(self, d):
        if self.ignore:
            return
        if self.pre.depth:
            self.pre.data(d)
        else:
            self.text.append(d.replace(_BR, "\ufffd"))


def strip_html(text: str, markdown: bool = False, page: str = "") -> str:
    """Read an HTML string and strip all tags, script contents, and style contents.

    ``markdown`` writes headings, links, lists and tables as Markdown; ``page``,
    the page's file name, makes a link to it a link to the same page.
    """
    if markdown:
        return render_markdown(text, page)[0]
    s = HTMLStripper()
    s.feed(text)
    return render_text(s.text + s.pre.close())


def render_markdown(text: str, page: str = "") -> tuple:
    """``strip_html(text, markdown=True, page=page)``, and the (level, text, offset) of each heading."""
    s = MarkdownStripper(page)
    s.feed(text)
    return _render(s.finish())


def render_text(parts: list) -> str:
    """Join a parser's text output into clean text, one block per paragraph.

    ``<pre>`` blocks (from PreCapture) are kept verbatim as fenced blocks.
    """
    return _render(parts)[0]


def _render(parts: list) -> tuple:
    """(text, headings): ``parts`` as text, and the (level, text, offset) of each heading."""
    blocks, headings, offset = [], [], 0
    for verbatim, run in groupby(_flatten(parts),
                                 key=lambda part: isinstance(part, (_Verbatim, _ListTree))):
        for block in (run if verbatim else _prose_blocks(''.join(run))):
            if isinstance(block, _ListTree):
                block = block.render()
            if isinstance(block, _Heading):
                headings.append((block.level, block.text, offset))
            blocks.append(block)
            offset += len(block) + 2
    return '\n\n'.join(blocks), headings


def _flatten(parts: list):
    """The parts of ``parts``, where a part that is a list stands for its own parts.

    Iterative: nesting follows the page's, which is untrusted.
    """
    stack = [iter(parts)]
    while stack:
        for part in stack[-1]:
            if isinstance(part, list):
                stack.append(iter(part))
                break
            yield part
        else:
            stack.pop()


def _prose_blocks(data: str) -> list:
    # Unescape HTML entities that might be lingering
    # (an entity can decode to the marker here, so each piece is neutralized after decoding)
    data = _BR.join(html.unescape(piece).replace(_BR, "\ufffd") for piece in data.split(_BR))
    # Collapse 3+ newlines into exactly 2 (preserve block separators)
    data = re.sub(r'\n{3,}', '\n\n', data)
    # Within each block, collapse whitespace (but not across \n\n boundaries)
    lines = data.split('\n\n')
    lines = [re.sub(r' ?(?:\ue000 ?)+', '\n', re.sub(r'\s+', ' ', block)).strip() for block in lines]
    # Drop empty blocks
    return [block for block in lines if block]


# ---------------------------------------------------------------------------
# Markdown (md output, #87)
# ---------------------------------------------------------------------------

_HEADING_LEVELS = {f"h{n}": n for n in range(1, 7)}
_LISTS = ("ul", "ol")
_CELLS = ("td", "th")
# A list item holding one of these is a container, not an entry (Javadoc puts each
# member's section in one): it is written as its blocks, without a marker.
_ITEM_BLOCKERS = BLOCK_TAGS - {"p", "li", "ul", "ol"}
# Links to anything else (javascript:, data:, file:...) keep only their text.
_LINK_SCHEMES = frozenset({"http", "https", "mailto"})
_SCHEME = re.compile(r"([A-Za-z][A-Za-z0-9+.-]*):")
_DESTINATION_UNSAFE = re.compile(r"[\s<>\\]")
# Deeper lists are indented as this level: indentation grows with depth, so
# unbounded it would make the output grow with the square of the nesting.
MAX_LIST_DEPTH = 16


def escape_link_text(text: str) -> str:
    """``text`` that cannot end the ``[...]`` of a Markdown link early."""
    return text.replace("\\", "\\\\").replace("[", "\\[").replace("]", "\\]")


def _link_destination(href, page: str):
    """Markdown link destination for ``href``, or None when the link keeps only its
    text: no target, a target on the same page (``#x``, or ``page#x`` as mirrors
    rewrite it: anchors are not written), or a scheme other than http, https and
    mailto."""
    href = (href or "").strip()
    # A browser drops whitespace and controls inside the scheme ("java\tscript:").
    scheme = _SCHEME.match(re.sub(r"[\x00-\x20]", "", href))
    if (not href or href.startswith("#") or (page and unquote(href.split("#")[0]) == page)
            or (scheme and scheme.group(1).lower() not in _LINK_SCHEMES)):
        return None
    dest = _DESTINATION_UNSAFE.sub(lambda m: quote(m.group()), neutralize_controls(href, "%%%02X"))
    # The <...> form takes any parentheses; the bare form needs them balanced.
    return f"<{dest}>" if "(" in dest or ")" in dest else dest


def _inlinable(parts) -> bool:
    """True when ``parts`` fit on one line: text, links and one-line code."""
    return all(type(p) in (str, _Link) or (type(p) is _Code and p.count("\n") == 2)
               for p in parts)


def _inline(parts, plain: bool = False) -> str:
    """Inlinable ``parts`` as one line; ``plain`` writes links as their text."""
    out = []
    for is_code, run in groupby(parts, key=lambda p: isinstance(p, _Code)):
        if is_code:
            out += [code_span(p.split("\n")[1]) for p in run]
        else:
            out += _prose_blocks("".join(p.text if plain and isinstance(p, _Link) else p
                                         for p in run))
    return " ".join(out).replace("\n", "; ")  # a <br> in one line


def _pipe_table(rows) -> str:
    """One line per row; the first row is the header, padded to the widest row."""
    cells = [[_inline(cell.parts).replace("|", "\\|") for cell in row] for row in rows]
    width = max(map(len, cells))
    header = cells[0] + [""] * (width - len(cells[0]))
    return "\n".join("| " + " | ".join(row) + " |"
                     for row in [header, ["---"] * width, *cells[1:]])


class _ListTree:
    """Consecutive list entries, each (marker, text, child trees), written as one block."""

    def __init__(self):
        self.entries = []

    def render(self) -> str:
        lines = []
        stack = [(iter(self.entries), "")]
        while stack:
            entries, indent = stack[-1]
            entry = next(entries, None)
            if entry is None:
                stack.pop()
                continue
            marker, text, children = entry
            lines.append(f"{indent}{marker} {text}".rstrip())
            if children:
                if len(stack) < MAX_LIST_DEPTH:
                    indent += " " * (len(marker) + 1)
                stack.append((chain.from_iterable(t.entries for t in children), indent))
        return "\n".join(lines)


class _Frame:
    """An element whose output is collected apart and placed when it closes."""

    def __init__(self, tag: str, marker: str = ""):
        self.tag = tag
        self.parts = []
        self.marker = marker   # li: "-" or "N."
        self.block = False     # li: holds a block, so it is no list entry
        self.number = 0        # ol: number of its last item
        self.rows = []         # table: one list of cell frames per row


class MarkdownStripper(HTMLStripper):
    """HTMLStripper that also writes headings, links, lists and tables as Markdown.

    A heading, list, list item, table and table cell collects its output in a
    frame and is written when it closes: a heading as one line; a list item as
    one line under its list's marker unless it holds a block (then as its
    blocks, without a marker); a table as one line per row unless a cell holds
    something that cannot share a line (multi-line code, a heading, a table),
    then as its cells, one block each. Lists inside a cell are written inline.
    Each part is placed once and by reference, so the work stays linear on
    untrusted pages. Missing end tags close what they imply, and whatever is
    still open at the end of the page is closed, so no text is lost.
    """

    def __init__(self, page: str = ""):
        super().__init__()
        self.page = page
        self.frames = [_Frame("")]
        self.open = Counter()
        self.text = self.frames[0].parts
        self.link = None  # (frame, index of its "[" placeholder, destination)

    def handle_starttag(self, tag, attrs):
        if not self.ignore and not self.pre.depth:
            self._open(tag, attrs)
        super().handle_starttag(tag, attrs)

    def handle_endtag(self, tag):
        super().handle_endtag(tag)
        if not self.ignore and not self.pre.depth:
            self._close(tag)

    def finish(self) -> list:
        """Close everything still open and return the output parts."""
        self.text.extend(self.pre.close())
        while len(self.frames) > 1:
            self._end()
        return self.frames[0].parts

    def _push(self, frame):
        self.frames.append(frame)
        self.open[frame.tag] += 1
        self.text = frame.parts

    def _open(self, tag, attrs):
        frame = self.frames[-1]
        if frame.tag == "li" and tag in _ITEM_BLOCKERS:
            frame.block = True
        if tag == "a":
            self.link = None  # an <a> inside an open one leaves the outer as text
            dest = _link_destination(dict(attrs).get("href"), self.page)
            if dest is not None:
                self.link = (frame, len(frame.parts), dest)
                frame.parts.append("")
        elif frame.tag in _HEADING_LEVELS:
            return  # a heading is one line of text
        elif tag in _HEADING_LEVELS or tag == "table":
            self._push(_Frame(tag))
        elif tag in _LISTS and frame.tag not in _CELLS:
            lst = _Frame(tag)
            start = dict(attrs).get("start") or ""
            lst.number = int(start) - 1 if tag == "ol" and start.isdigit() else 0
            self._push(lst)
        elif tag == "li":
            if frame.tag == "li":
                self._end()  # an omitted </li>
                frame = self.frames[-1]
            if frame.tag in _LISTS:
                frame.number += 1
                self._push(_Frame("li", "-" if frame.tag == "ul" else f"{frame.number}."))
        elif tag == "tr" or tag in _CELLS:
            if frame.tag in _CELLS:
                self._end()  # an omitted </td>
                frame = self.frames[-1]
            if frame.tag == "table":
                if tag == "tr" or not frame.rows:
                    frame.rows.append([])
                if tag in _CELLS:
                    cell = _Frame(tag)
                    frame.rows[-1].append(cell)
                    self._push(cell)

    def _close(self, tag):
        if tag == "a":
            self._close_link()
        elif tag in _HEADING_LEVELS:
            self._close_to(_HEADING_LEVELS, ())
        elif tag == "li":
            self._close_to(("li",), _LISTS + _CELLS + ("table",))
        elif tag in _LISTS:
            self._close_to(_LISTS, _CELLS + ("table",))
        elif tag in _CELLS or tag == "tr":
            self._close_to(_CELLS, ("table",))
        elif tag == "table":
            self._close_to(("table",), ())

    def _close_to(self, tags, boundary):
        """Close the innermost open frame with a tag in ``tags`` and every frame above
        it, unless a frame in ``boundary`` comes first."""
        if not any(self.open[t] for t in tags):
            return  # a stray end tag: no scan, so stray tags stay O(1)
        for i in range(len(self.frames) - 1, 0, -1):
            if self.frames[i].tag in tags:
                while len(self.frames) > i:
                    self._end()
                return
            if self.frames[i].tag in boundary:
                return

    def _end(self):
        """Close the innermost frame and place its output in the enclosing one."""
        frame = self.frames.pop()
        self.open[frame.tag] -= 1
        parent = self.frames[-1]
        self.text = parent.parts
        if frame.tag in _HEADING_LEVELS:
            text = _inline(frame.parts, plain=True) if _inlinable(frame.parts) else ""
            if text:
                heading = _Heading("#" * _HEADING_LEVELS[frame.tag] + " " + _inline(frame.parts))
                heading.level, heading.text = _HEADING_LEVELS[frame.tag], text
                parent.parts.append(heading)
            else:
                parent.parts.append(frame.parts)
        elif frame.tag == "li":
            trees = [p for p in frame.parts if isinstance(p, _ListTree)]
            rest = [p for p in frame.parts if not isinstance(p, _ListTree)]
            if frame.block or not _inlinable(rest):
                parent.parts += ("\n\n", frame.parts, "\n\n")
                return
            text = _inline(rest)
            if text or trees:
                parts = parent.parts
                while parts and type(parts[-1]) is str and parts[-1].isspace():
                    parts.pop()  # whitespace between items
                if not (parts and isinstance(parts[-1], _ListTree)):
                    parts.append(_ListTree())
                parts[-1].entries.append((frame.marker, text, trees))
        elif frame.tag in _LISTS:
            items = [p for p in frame.parts if not (type(p) is str and p.isspace())]
            if parent.tag == "li" and all(isinstance(p, _ListTree) for p in items):
                parent.parts += items
            else:
                parent.block = True
                parent.parts += ("\n\n", frame.parts, "\n\n")
        elif frame.tag == "table":
            rows = [row for row in frame.rows if row]
            parent.parts.append(frame.parts)  # the caption and any text outside the cells
            if all(_inlinable(cell.parts) for row in rows for cell in row):
                if rows:
                    parent.parts.append(_Block(_pipe_table(rows)))
            else:
                for cell in (cell for row in rows for cell in row):
                    parent.parts += ("\n\n", cell.parts)
                parent.parts.append("\n\n")

    def _close_link(self):
        if self.link is None:
            return
        frame, at, dest = self.link
        self.link = None
        parts = frame.parts
        if frame is not self.frames[-1] or not all(type(p) is str for p in parts[at + 1:]):
            return  # a block or a frame inside the link: its text stays as is
        text = "".join(parts[at + 1:])
        words = text.split()
        if not words:
            return
        # Prose is unescaped once more when rendered (_prose_blocks): what goes in
        # here is escaped so that pass gives back the label and the destination.
        label = html.escape(escape_link_text(html.unescape(" ".join(words))), quote=False)
        lead = " " if text[0].isspace() else ""
        trail = " " if text[-1].isspace() else ""
        link = _Link(f"{lead}[{label}]({html.escape(dest, quote=False)}){trail}")
        link.text = lead + " ".join(words) + trail
        del parts[at + 1:]
        parts[at] = link
