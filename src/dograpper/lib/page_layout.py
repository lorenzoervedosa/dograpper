"""Per-page pack layout (ADR-0010): one file per page under ``pages/``, plus ``INDEX.md``.

Page files mirror the source tree with the format's extension
(``Modding/vi.html`` -> ``pages/Modding/vi.md``), named by the rules shared with
the httrack profile (``utils/portable_names.py``) plus Windows reserved names.
Each run builds the whole tree in a sibling temporary directory and swaps it
in, so a failed run keeps the previous pages and a removed page never
survives a repack. ``pack`` owns ``INDEX.md`` and ``pages/`` only: any other
file in the output directory (a ``SKILL.md``) is never touched.
"""

import os
import shutil
from collections import Counter
from html.parser import HTMLParser

from .chunker import Chunk, ChunkFile, _plain_text, is_html, read_source_text
from ..utils.atomic_write import atomic_write_bytes
from ..utils.heading_extractor import format_context_header
from ..utils.html_stripper import escape_link_text
from ..utils.portable_names import FORBIDDEN, claim_unique, resolve_under
from ..utils.redact import neutralize_controls
from ..utils.word_counter import count_words, count_words_file

PAGES_DIR = "pages"
INDEX_FILENAME = "INDEX.md"

_RESERVED = frozenset(["CON", "PRN", "AUX", "NUL",
                       *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))])
_SUFFIX_SEPARATORS = (" - ", " – ", " — ", " | ")


def _portable_segment(seg: str) -> str:
    seg = seg.translate(FORBIDDEN)
    if seg.endswith((".", " ")):
        seg = seg[:-1] + "_"
    if seg.upper() in _RESERVED:
        seg += "_"
    return seg


def assign_page_paths(rel_paths, fmt: str) -> dict:
    """Output path of each source path, relative to the pack root (``pages/...``).

    Assigned in sorted source order, so the same tree always gives the same names.
    """
    used: set = set()
    paths = {}
    for rel in sorted(rel_paths):
        *dirs, name = rel.split("/")
        segs = [_portable_segment(s) for s in (*dirs, os.path.splitext(name)[0])]
        paths[rel] = claim_unique("/".join([PAGES_DIR, *segs]) + "." + fmt, used)
    return paths


def page_chunks(paths, input_dir: str, fmt: str, no_extract: bool) -> list:
    """One chunk per page, in output-path order; ``page_path`` is the chunk's id."""
    rels = {os.path.relpath(p, input_dir).replace(os.sep, '/'): p for p in paths}
    out = assign_page_paths(rels, fmt)
    chunks = []
    for rel in sorted(rels, key=out.__getitem__):
        words = count_words_file(rels[rel], no_extract=no_extract)
        chunks.append(Chunk(index=len(chunks) + 1, files=[ChunkFile(rel, words)],
                            total_words=words, page_path=out[rel]))
    return chunks


class _Found(Exception):
    pass


class _FirstText(HTMLParser):
    """Whitespace-collapsed text of the first ``<tag>``; ``head_only`` stops at ``<body>``."""

    def __init__(self, tag: str, head_only: bool):
        super().__init__(convert_charrefs=True)
        self._tag, self._head_only = tag, head_only
        self._parts = None
        self.text = ""

    def handle_starttag(self, tag, attrs):
        if self._head_only and tag == "body":
            raise _Found
        if tag == self._tag and self._parts is None:
            self._parts = []

    def handle_endtag(self, tag):
        if tag == self._tag and self._parts is not None:
            self.text = " ".join("".join(self._parts).split())
            raise _Found

    def handle_data(self, data):
        if self._parts is not None:
            self._parts.append(data)


def _first_text(path: str, tag: str, head_only: bool) -> str:
    with open(path, 'r', encoding='utf-8', errors='replace') as fh:
        html = fh.read()
    parser = _FirstText(tag, head_only)
    try:
        parser.feed(html)
        parser.close()
    except _Found:
        pass
    return parser.text


def _last_suffix(title: str):
    """The text from the last site-suffix separator on, or None."""
    cut = max(title.rfind(sep) for sep in _SUFFIX_SEPARATORS)
    return title[cut:] if cut >= 0 else None


def page_titles(rel_paths, input_dir: str) -> dict:
    """Title of each page (ADR-0010 point 4).

    The ``<head>`` ``<title>`` minus the site suffix, when that exact suffix ends
    more than half of the run's titles; else the first ``h1`` of the raw page
    (MediaWiki's sits outside the extracted container); else the file stem.
    """
    is_html = {rel: rel.lower().endswith(('.html', '.htm')) for rel in rel_paths}
    head = {rel: _first_text(os.path.join(input_dir, rel), "title", head_only=True)
            for rel in rel_paths if is_html[rel]}
    found = [t for t in head.values() if t]
    counts = Counter(s for s in map(_last_suffix, found) if s)
    suffix, n = counts.most_common(1)[0] if counts else (None, 0)
    if n * 2 <= len(found):
        suffix = None

    titles = {}
    for rel in rel_paths:
        title = head.get(rel, "")
        if suffix and _last_suffix(title) == suffix:
            title = title[:-len(suffix)]
        if not title and is_html[rel]:
            title = _first_text(os.path.join(input_dir, rel), "h1", head_only=False)
        titles[rel] = title or os.path.splitext(rel.rsplit("/", 1)[-1])[0]
    return titles


def _index_line(title: str, path: str, words: int, url: str) -> str:
    # Title is page content: one line, no control characters, no link-text breakout.
    title = escape_link_text(" ".join(title.split()))
    line = f"- [{neutralize_controls(title)}](<{path}>), {words} words"
    return f"{line}, {url}" if url else line


def owns_pages(output_dir: str) -> bool:
    """False when ``<output_dir>/pages`` exists but is not a previous page-layout output."""
    pages = os.path.join(output_dir, PAGES_DIR)
    if not os.path.lexists(pages):
        return True
    return (os.path.isdir(pages) and not os.path.islink(pages)
            and os.path.isfile(os.path.join(output_dir, INDEX_FILENAME)))


def _write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write(text)


def _swap_in(new: str, dest: str) -> None:
    old = None
    if os.path.lexists(dest):
        old = new + ".old"
        os.rename(dest, old)
    try:
        os.rename(new, dest)
    except BaseException:
        if old:
            os.rename(old, dest)
        raise
    if old:
        shutil.rmtree(old)


def write_pages(chunks, input_dir: str, output_dir: str, no_extract: bool = False,
                text_overrides=None, url_map=None, readiness_map=None, annotate=None,
                with_header: bool = False, markdown: bool = False) -> str:
    """Write ``pages/`` and ``INDEX.md`` for ``page_chunks`` output. Returns the index path.

    ``markdown`` writes HTML pages as Markdown (md) and counts their words
    without its markup; otherwise (txt) code blocks lose their fence, as in
    txt chunks. The caller checks ``owns_pages`` first. Raises OSError
    on any failed write, leaving the previous ``pages/`` in place.
    """
    chunks = sorted(chunks, key=lambda c: c.page_path)
    titles = page_titles([c.files[0].relative_path for c in chunks], input_dir)
    os.makedirs(output_dir, exist_ok=True)
    root = os.path.realpath(output_dir)
    # Created like atomic_write's temp file: a fresh name, mode from the umask.
    tmp = os.path.join(root, f".pages-{os.urandom(8).hex()}.tmp")
    os.mkdir(tmp)
    try:
        lines = []
        for chunk in chunks:
            rel = chunk.files[0].relative_path
            content = (text_overrides or {}).get(rel)
            if content is None:
                content = read_source_text(os.path.join(input_dir, rel), no_extract=no_extract,
                                           markdown=markdown)
            if not markdown:
                content = _plain_text(chunk.files[0], content)
            words = count_words(content, markdown and is_html(rel))
            url = (url_map or {}).get(rel, "")
            text = annotate(rel, content) if annotate else content
            if with_header:
                text = format_context_header(
                    [], title=titles[rel], source_path=rel, word_count=words, url=url,
                    readiness=(readiness_map or {}).get(chunk.page_path)) + text
            dest = resolve_under(tmp, *chunk.page_path.split("/")[1:])
            if dest is None:
                raise OSError(f"page path leaves {PAGES_DIR}/: {chunk.page_path}")
            _write_text(dest, text + "\n")
            lines.append(_index_line(titles[rel], chunk.page_path, words, url))

        count = f"{len(lines)} page{'' if len(lines) == 1 else 's'}"
        index = "\n".join(["# Index",
                           f"{count}. One line per page: - [title](<path>), N words, URL",
                           "", *lines]) + "\n"
        # The index goes first: it marks pages/ as ours, so a crash before the
        # swap never leaves a pages/ that the next run refuses to replace.
        atomic_write_bytes(os.path.join(root, INDEX_FILENAME), index.encode('utf-8'))
        _swap_in(tmp, os.path.join(root, PAGES_DIR))
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    return os.path.join(output_dir, INDEX_FILENAME)
