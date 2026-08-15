"""Cross-reference extraction and indexing for documentation HTML.

Parses internal links from HTML files, builds a cross-reference index
mapping chunks to their outgoing/incoming references, and optionally
annotates plain text with chunk pointers.
"""

import json
import logging
import posixpath
import re
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import List, Dict

logger = logging.getLogger(__name__)

# Schemes that indicate an external (non-local) link.
_EXTERNAL_SCHEMES = ("http://", "https://", "mailto:", "javascript:")


@dataclass
class LinkRef:
    """A single internal hyperlink extracted from an HTML file."""
    source_path: str    # file containing the link (relative to input_dir)
    target_path: str    # canonicalized resolved target path (relative to input_dir)
    anchor: str         # #fragment if present, else empty
    link_text: str      # visible link text from HTML


def extract_links(html: str, source_path: str) -> List[LinkRef]:
    """Extract internal links from *html* originating from *source_path*.

    External links (http, https, mailto, javascript) are discarded.
    Relative paths are resolved against *source_path*'s directory.
    ``index.html`` suffixes are stripped during normalisation.

    Returns a list of :class:`LinkRef` instances.
    """
    parser = _LinkParser()
    parser.feed(html)

    source_dir = posixpath.dirname(source_path)

    results: List[LinkRef] = []
    for href, text in parser.links:
        # Skip external links
        if any(href.startswith(scheme) for scheme in _EXTERNAL_SCHEMES):
            continue

        # Skip empty hrefs and pure-fragment links
        if not href or href.startswith("#"):
            continue

        # Separate fragment
        anchor = ""
        if "#" in href:
            href, anchor = href.split("#", 1)
            anchor = "#" + anchor

        # Resolve relative path
        if href:
            resolved = posixpath.normpath(posixpath.join(source_dir, href))
        else:
            # href was only a fragment (already skipped above)
            continue

        # Remove leading ./
        if resolved.startswith("./"):
            resolved = resolved[2:]

        # Normalise trailing index.html
        if resolved.endswith("/index.html"):
            resolved = resolved[:-len("/index.html")]
        elif resolved == "index.html":
            resolved = ""

        # Skip if resolved to empty (root index)
        if not resolved:
            continue

        results.append(LinkRef(
            source_path=source_path,
            target_path=resolved,
            anchor=anchor,
            link_text=text.strip(),
        ))

    return results


def build_cross_ref_index(
    links: List[LinkRef],
    file_to_chunk: Dict[str, str],
) -> dict:
    """Build a JSON-serialisable cross-reference index.

    Args:
        links: All extracted links across all files.
        file_to_chunk: Mapping ``{relative_path: chunk_id}``.

    Returns:
        A dict with per-chunk ``references_to``, ``referenced_by``,
        ``links`` lists, plus an ``unresolved`` list for links whose
        target is not part of the pack.
    """
    index: Dict[str, dict] = {}
    unresolved: list = []

    def _ensure_chunk(chunk_id: str) -> dict:
        if chunk_id not in index:
            index[chunk_id] = {
                "references_to": [],
                "referenced_by": [],
                "links": [],
            }
        return index[chunk_id]

    for link in links:
        source_chunk = file_to_chunk.get(link.source_path)
        target_chunk = file_to_chunk.get(link.target_path)

        if source_chunk is None:
            # Source file not in any chunk — shouldn't happen but be safe
            continue

        if target_chunk is None:
            unresolved.append({
                "source_file": link.source_path,
                "target_file": link.target_path,
                "anchor": link.anchor,
                "link_text": link.link_text,
            })
            continue

        src_entry = _ensure_chunk(source_chunk)
        tgt_entry = _ensure_chunk(target_chunk)

        # Record outgoing reference
        if target_chunk not in src_entry["references_to"]:
            src_entry["references_to"].append(target_chunk)

        # Record incoming reference
        if source_chunk not in tgt_entry["referenced_by"]:
            tgt_entry["referenced_by"].append(source_chunk)

        # Record link detail
        src_entry["links"].append({
            "source_file": link.source_path,
            "target_file": link.target_path,
            "target_chunk": target_chunk,
            "anchor": link.anchor,
            "link_text": link.link_text,
        })

    result = dict(index)
    result["unresolved"] = unresolved
    return result


def annotate_cross_refs(
    text: str,
    links: List[LinkRef],
    file_to_chunk: Dict[str, str],
) -> str:
    """Annotate *text* with cross-reference markers.

    For each link whose target resolves to a chunk, the **first**
    occurrence of ``link_text`` in *text* is suffixed with
    ``[-> chunk_id]``.  Only the first occurrence is touched to
    avoid false positives.  Unresolved links are skipped.

    The match is word-boundary-aware: ``link_text`` is only annotated
    when it is not adjacent to a word character, so short link text
    (e.g. "Install") does not corrupt an unrelated word that merely
    contains it as a substring (e.g. "Installation").
    """
    annotated = set()  # link_text values already processed

    for link in links:
        lt = link.link_text.strip()
        if not lt or lt in annotated:
            continue

        target_chunk = file_to_chunk.get(link.target_path)
        if target_chunk is None:
            continue

        marker = f"{lt} [-> {target_chunk}]"
        # Replace only the first occurrence, and only when not adjacent to
        # a word character on either side (a plain \b fails here because
        # link text often starts/ends in punctuation, e.g. "C++").
        pattern = re.compile(r"(?<!\w)" + re.escape(lt) + r"(?!\w)")
        new_text = pattern.sub(lambda m: marker, text, count=1)
        if new_text != text:
            text = new_text
            annotated.add(lt)

    return text


# ---------------------------------------------------------------------------
# Internal parser
# ---------------------------------------------------------------------------

class _LinkParser(HTMLParser):
    """Single-pass parser that collects ``<a href="...">text</a>`` pairs."""

    def __init__(self):
        super().__init__()
        self.convert_charrefs = True
        self.links: List[tuple] = []    # (href, visible_text)
        self._current_href = None
        self._text_parts: list = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            attrs_dict = dict(attrs)
            href = attrs_dict.get("href", "")
            self._current_href = href
            self._text_parts = []

    def handle_endtag(self, tag):
        if tag == "a" and self._current_href is not None:
            text = "".join(self._text_parts)
            self.links.append((self._current_href, text))
            self._current_href = None
            self._text_parts = []

    def handle_data(self, data):
        if self._current_href is not None:
            self._text_parts.append(data)
