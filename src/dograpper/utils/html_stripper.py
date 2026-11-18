"""HTML Stripping utility."""

from html.parser import HTMLParser
import re
import html

BLOCK_TAGS = frozenset({
    "p", "div", "section", "article", "main",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "li", "tr", "blockquote", "pre", "ul", "ol",
    "table", "dl", "dt", "dd", "figcaption", "figure", "hr",
})


class HTMLStripper(HTMLParser):
    def __init__(self):
        super().__init__()
        self.reset()
        self.strict = False
        self.convert_charrefs = True
        self.text = []
        self.ignore = False
        self.ignore_tags = {'script', 'style'}

    def handle_starttag(self, tag, attrs):
        if tag in self.ignore_tags:
            self.ignore = True

    def handle_endtag(self, tag):
        if tag in self.ignore_tags:
            self.ignore = False
        elif not self.ignore and tag in BLOCK_TAGS:
            self.text.append("\n\n")

    def handle_data(self, d):
        if not self.ignore:
            self.text.append(d)


def strip_html(text: str) -> str:
    """Read an HTML string and strip all tags, script contents, and style contents."""
    s = HTMLStripper()
    s.feed(text)
    return render_text(s.text)


def render_text(parts: list) -> str:
    """Join a parser's text output into clean text, one block per paragraph."""
    data = ''.join(parts)
    # Unescape HTML entities that might be lingering
    data = html.unescape(data)
    # Collapse 3+ newlines into exactly 2 (preserve block separators)
    data = re.sub(r'\n{3,}', '\n\n', data)
    # Within each block, collapse whitespace (but not across \n\n boundaries)
    lines = data.split('\n\n')
    lines = [re.sub(r'\s+', ' ', block).strip() for block in lines]
    # Rejoin and drop empty blocks
    data = '\n\n'.join(block for block in lines if block)
    return data.strip()
