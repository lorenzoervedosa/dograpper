"""HTML Stripping utility."""

from html.parser import HTMLParser
from itertools import groupby
import re
import html

from .code_fence import fence

BLOCK_TAGS = frozenset({
    "p", "div", "section", "article", "main",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "tr", "blockquote", "pre", "ul", "ol",
    "table", "dl", "dt", "dd", "figcaption", "figure", "hr",
})

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


class _Code(str):
    """A fenced ``<pre>`` block in parser output, kept out of the whitespace collapse."""


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
            self.text.append(d)


def strip_html(text: str) -> str:
    """Read an HTML string and strip all tags, script contents, and style contents."""
    s = HTMLStripper()
    s.feed(text)
    return render_text(s.text + s.pre.close())


def render_text(parts: list) -> str:
    """Join a parser's text output into clean text, one block per paragraph.

    ``<pre>`` blocks (from PreCapture) are kept verbatim as fenced blocks.
    """
    blocks = []
    for is_code, run in groupby(parts, key=lambda part: isinstance(part, _Code)):
        blocks += list(run) if is_code else _prose_blocks(''.join(run))
    return '\n\n'.join(blocks)


def _prose_blocks(data: str) -> list:
    # Unescape HTML entities that might be lingering
    data = html.unescape(data)
    # Collapse 3+ newlines into exactly 2 (preserve block separators)
    data = re.sub(r'\n{3,}', '\n\n', data)
    # Within each block, collapse whitespace (but not across \n\n boundaries)
    lines = data.split('\n\n')
    lines = [re.sub(r'\s+', ' ', block).strip() for block in lines]
    # Drop empty blocks
    return [block for block in lines if block]
