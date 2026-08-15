"""Intelligent content extraction for documentation HTML.

Locates the main content block in documentation pages and strips
boilerplate (nav, sidebar, footer, breadcrumbs, etc.) so that only
informative text reaches the chunker.
"""

import logging
from html.parser import HTMLParser
from typing import Optional

logger = logging.getLogger(__name__)

SEMANTIC_SELECTORS = [
    # (tag, attr_name, attr_value) — None means "any value" / "no attr needed"
    ("main", None, None),
    ("div", "role", "main"),
    ("article", None, None),
    ("div", "id", "content"),
    ("div", "id", "main-content"),
    ("div", "class", "content"),
    ("div", "class", "main-content"),
    ("div", "class", "markdown-body"),
    ("div", "class", "documentation-content"),
    ("div", "class", "doc-content"),
]

BLACKLISTED_TAGS = frozenset({
    "nav", "header", "footer", "aside",
    "script", "style", "noscript", "iframe", "svg",
})

BLACKLISTED_CLASSES = frozenset({
    "breadcrumb", "breadcrumbs", "sidebar", "side-bar", "side-nav",
    "toc", "table-of-contents", "navbar", "nav-bar", "navigation",
    "footer", "page-footer", "site-footer", "cookie", "cookie-banner",
    "copy-button", "copy-to-clipboard", "version-selector",
    "version-banner", "version-warning", "feedback",
    "was-this-helpful", "edit-this-page", "edit-on-github",
    "announcement", "announcement-banner",
})

# HTML void elements: they have no end tag, so a skip region opened on one
# would never be closed.
VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})

BLACKLISTED_IDS = frozenset({
    "navbar", "sidebar", "footer", "toc", "table-of-contents",
    "breadcrumb", "cookie-consent", "announcement-bar",
})


def extract_content(html: str) -> str:
    """Extract the main content from a documentation HTML page.

    Strategy:
    1. Try to find a semantic container (<main>, <article>, etc.).
    2. Fall back to density scoring on <div>/<section> blocks.
    3. Remove blacklisted elements from the result.
    4. If nothing is found, return the original HTML (never lose content).

    Returns HTML (still with tags) — the caller is responsible for
    running strip_html() afterwards.
    """
    if not html or not html.strip():
        return ""

    container_html = _find_semantic_container(html)
    if container_html is None:
        container_html = _find_by_density(html)
    if container_html is None:
        container_html = html

    return _remove_blacklisted(container_html)


def _find_semantic_container(html: str) -> Optional[str]:
    """Return innerHTML of the highest-priority semantic container, or None."""
    parser = _SemanticFinderParser()
    parser.feed(html)
    return parser.get_result()


def _find_by_density(html: str) -> Optional[str]:
    """Score <div>/<section> blocks by text density; return best or None."""
    parser = _DensityScorerParser()
    parser.feed(html)
    return parser.get_result()


def _remove_blacklisted(html: str) -> str:
    """Strip blacklisted elements (nav, footer, sidebar, etc.) from HTML."""
    parser = _BlacklistRemoverParser()
    parser.feed(html)
    return parser.get_output()


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _matches_class(element_classes: str, blacklist: frozenset) -> bool:
    """Check if any individual class substring-matches a blacklist entry.

    Example:
        _matches_class("docs-sidebar left-nav", {"sidebar"})  -> True
        _matches_class("main-content", {"sidebar"})           -> False
    """
    for cls in element_classes.split():
        for blocked in blacklist:
            if blocked in cls:
                return True
    return False


def _matches_selector(attrs, sel_attr, sel_val):
    """Check whether element *attrs* match a semantic selector."""
    if sel_attr is None:
        return True
    attrs_dict = dict(attrs)
    val = attrs_dict.get(sel_attr, "")
    if sel_attr == "class":
        # Exact match on individual class tokens (not substring).
        return sel_val in val.split()
    return val == sel_val


def _is_blacklisted(tag, attrs):
    """Decide whether an element should be removed entirely."""
    if tag in BLACKLISTED_TAGS:
        return True
    attrs_dict = dict(attrs)
    cls = attrs_dict.get("class", "")
    if cls and _matches_class(cls, BLACKLISTED_CLASSES):
        return True
    el_id = attrs_dict.get("id", "")
    if el_id:
        for blocked in BLACKLISTED_IDS:
            if blocked in el_id:
                return True
    return False


def _last_index(stack, tag):
    """Index of the innermost open *tag* in *stack*."""
    return len(stack) - 1 - stack[::-1].index(tag)


def _rebuild_tag(tag, attrs):
    """Reconstruct an opening HTML tag string from parsed components."""
    parts = [f"<{tag}"]
    for name, value in attrs:
        if value is None:
            parts.append(f" {name}")
        else:
            parts.append(f' {name}="{value}"')
    parts.append(">")
    return "".join(parts)


# ---------------------------------------------------------------------------
# Parsers
# ---------------------------------------------------------------------------

class _SemanticFinderParser(HTMLParser):
    """Single-pass parser that finds the highest-priority semantic container.

    Iterates SEMANTIC_SELECTORS in priority order.  When a matching tag is
    opened, its innerHTML is captured until the corresponding close tag.
    If a higher-priority match is found later in the document, it replaces
    the previous best.
    """

    def __init__(self):
        super().__init__()
        self.convert_charrefs = True
        self.best_match = None        # (priority_index, content_str)
        self._capturing = False
        self._cap_priority = None
        self._cap_tag = None
        self._cap_nesting = 0         # same-tag nesting counter
        self._cap_parts = []

    def handle_starttag(self, tag, attrs):
        if self._capturing:
            if tag == self._cap_tag:
                self._cap_nesting += 1
            self._cap_parts.append(_rebuild_tag(tag, attrs))
            return

        # Try to start a capture that can improve on best_match.
        for i, (sel_tag, sel_attr, sel_val) in enumerate(SEMANTIC_SELECTORS):
            if self.best_match is not None and i >= self.best_match[0]:
                break  # cannot improve
            if tag == sel_tag and _matches_selector(attrs, sel_attr, sel_val):
                self._capturing = True
                self._cap_priority = i
                self._cap_tag = tag
                self._cap_nesting = 0
                self._cap_parts = []
                break

    def handle_endtag(self, tag):
        if not self._capturing:
            return
        if tag == self._cap_tag:
            if self._cap_nesting > 0:
                self._cap_nesting -= 1
                self._cap_parts.append(f"</{tag}>")
            else:
                content = "".join(self._cap_parts)
                if self.best_match is None or self._cap_priority < self.best_match[0]:
                    self.best_match = (self._cap_priority, content)
                self._capturing = False
        else:
            self._cap_parts.append(f"</{tag}>")

    def handle_data(self, data):
        if self._capturing:
            self._cap_parts.append(data)

    def get_result(self) -> Optional[str]:
        return self.best_match[1] if self.best_match else None


class _DensityScorerParser(HTMLParser):
    """Score <div> and <section> blocks by text density.

    Each block's score = word_count - (link_count * 3)
                         - (50 if contains nav/header/footer/aside child)

    The block with the highest score above 50 wins.
    """

    BLOCK_TAGS = frozenset({"div", "section"})
    NAV_TAGS = frozenset({"nav", "header", "footer", "aside"})

    def __init__(self):
        super().__init__()
        self.convert_charrefs = True
        self.block_stack = []       # list of block-info dicts
        self.best = None            # (score, html_content)

    def handle_starttag(self, tag, attrs):
        rebuilt = _rebuild_tag(tag, attrs)

        # Append to every open block's innerHTML buffer.
        for b in self.block_stack:
            b["html_parts"].append(rebuilt)

        if tag in self.BLOCK_TAGS:
            # Increment same-tag nesting counter for ancestor blocks.
            for b in self.block_stack:
                if b["tag"] == tag:
                    b["nesting"] += 1
            self.block_stack.append({
                "tag": tag,
                "nesting": 0,
                "text_parts": [],
                "link_count": 0,
                "has_blacklisted_child": False,
                "html_parts": [],
            })

        if tag == "a":
            for b in self.block_stack:
                b["link_count"] += 1

        if tag in self.NAV_TAGS and self.block_stack:
            self.block_stack[-1]["has_blacklisted_child"] = True

    def handle_endtag(self, tag):
        if tag in self.BLOCK_TAGS and self.block_stack:
            # Find the topmost block of this tag type.
            for i in range(len(self.block_stack) - 1, -1, -1):
                if self.block_stack[i]["tag"] == tag:
                    block = self.block_stack[i]
                    if block["nesting"] > 0:
                        block["nesting"] -= 1
                        for b in self.block_stack[i:]:
                            b["html_parts"].append(f"</{tag}>")
                    else:
                        closed = self.block_stack.pop(i)
                        word_count = len(" ".join(closed["text_parts"]).split())
                        penalty = closed["link_count"] * 3
                        if closed["has_blacklisted_child"]:
                            penalty += 50
                        score = word_count - penalty
                        if score > 50 and (self.best is None or score > self.best[0]):
                            self.best = (score, "".join(closed["html_parts"]))
                        # Propagate close to remaining ancestor blocks.
                        for b in self.block_stack:
                            b["html_parts"].append(f"</{tag}>")
                            if b["tag"] == tag:
                                b["nesting"] -= 1
                    break
        else:
            for b in self.block_stack:
                b["html_parts"].append(f"</{tag}>")

    def handle_data(self, data):
        for b in self.block_stack:
            b["text_parts"].append(data)
            b["html_parts"].append(data)

    def get_result(self) -> Optional[str]:
        return self.best[1] if self.best else None


class _BlacklistRemoverParser(HTMLParser):
    """Rebuild HTML while omitting blacklisted elements and their children.

    A skip region must always terminate: a blacklisted element whose end tag
    never arrives (a void element, or stray markup inside a code sample) used
    to swallow the whole remainder of the document. Two guarantees keep that
    from happening:

    * a blacklisted void element is dropped on its own, without opening a
      skip region at all;
    * an end tag belonging to an element that was already open when the skip
      started closes the runaway skip, because the blacklisted element must
      have been implicitly closed before it.
    """

    def __init__(self):
        super().__init__()
        self.convert_charrefs = True
        self.output = []
        self._open_tags = []    # elements open around the current position
        self._skip_stack = []   # elements open inside the skipped subtree

    def handle_starttag(self, tag, attrs):
        if self._skip_stack:
            if tag not in VOID_ELEMENTS:
                self._skip_stack.append(tag)
            return

        if _is_blacklisted(tag, attrs):
            if tag not in VOID_ELEMENTS:
                self._skip_stack.append(tag)
            return

        if tag not in VOID_ELEMENTS:
            self._open_tags.append(tag)
        self.output.append(_rebuild_tag(tag, attrs))

    def handle_endtag(self, tag):
        if self._skip_stack:
            if tag in self._skip_stack:
                # Closes an element inside the skipped subtree — when it is
                # the blacklisted element itself, the skip region ends here.
                del self._skip_stack[_last_index(self._skip_stack, tag):]
                return
            if tag not in self._open_tags:
                return
            # An enclosing element is closing while the blacklisted element is
            # still open: it was never closed. Recover and handle normally.
            self._skip_stack.clear()

        if tag in self._open_tags:
            del self._open_tags[_last_index(self._open_tags, tag):]
        self.output.append(f"</{tag}>")

    def handle_data(self, data):
        if not self._skip_stack:
            self.output.append(data)

    def get_output(self) -> str:
        return "".join(self.output)
