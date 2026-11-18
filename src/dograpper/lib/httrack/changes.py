"""HTTrack's change report (-%d / --changes, htschanges.c): what a crawl did to each mirrored
file against the previous run, written as hts-changes.json in the mirror folder.

The engines feed one Changes per run: overwriting() before each write samples the copy
about to be replaced, tried() marks each URL requested past robots.txt, and report()
sorts every file into new, changed, unchanged or gone and serializes it as HTTrack does.
The previous run's manifest stands for HTTrack's cache and old.lst: its files are the
previous index, and its records' payload_md5 the bodies the cache kept.
"""

import hashlib
import os
import threading
from collections.abc import Collection, Iterable, Mapping
from datetime import datetime, timezone

from dograpper.lib.manifest import Manifest
from dograpper.utils.portable_names import resolve_under
from dograpper.utils.redact import recordable_url

from .crawl import _fsize, hypertext
from .links import url_key
from .policy import _VERSION

CHANGES_FILE = "hts-changes.json"  # htschanges.h HTS_CHANGES_FILE
SCHEMA = 1                          # htschanges.h HTS_CHANGES_SCHEMA
BUCKETS = ("new", "changed", "unchanged", "gone")
GENERATOR = f"dograpper/{_VERSION}"  # HTTrack writes its own name (spec 5.1: our identity)


def json_string(s: str) -> str:
    """htscharset.c hts_json_string: `"` and `\\` take a backslash, a C0 control or DEL
    is \\u00xx, other characters are written as they are, and what is no well-formed UTF-8
    (a lone surrogate, as an undecodable file name byte reads) is \\ufffd."""
    out = ['"']
    for ch in s:
        c = ord(ch)
        if ch in '"\\':
            out.append("\\" + ch)
        elif c < 0x20 or c == 0x7f:
            out.append(f"\\u{c:04x}")
        elif 0xd800 <= c <= 0xdfff:
            out.append("\\ufffd")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def _md5_file(path: str) -> str | None:
    """htschanges.c digest_file: the MD5 of the file, None when it cannot be read."""
    h = hashlib.md5()
    try:
        with open(path, "rb") as f:
            while chunk := f.read(32768):
                h.update(chunk)
    except OSError:
        return None
    return h.hexdigest()


def _ok(status) -> bool:
    return type(status) is int and 200 <= status < 300


class Changes:
    """The --changes accumulator of one run (htschanges.c hts_changes). `cache` is the
    policy's cache mode: under -C0 HTTrack keeps no file list, so nothing is read from
    `previous`, nothing is gone and first_crawl is null (htscore.c:2147)."""

    def __init__(self, output_dir: str, previous: Manifest | None, cache: int | None):
        self.root = os.path.realpath(output_dir)
        self.indexed = cache != 0
        self.listed = {}  # old.lst: file -> the previous run's entry for it
        for key, e in (previous.files.items() if previous and self.indexed else ()):
            if path := resolve_under(self.root, e.local_path or key):
                self.listed.setdefault(path, e)
        self._before: dict[str, tuple[int, str | None]] = {}
        self._tried: set[str] = set()
        self._lock = threading.Lock()

    def overwriting(self, path: str) -> None:
        """A file is about to be written: its size and MD5 before, sampled once, "the last
        moment it exists" (hts_changes_notify, htschanges.c:268-296)."""
        size = _fsize(path)
        digest = _md5_file(path) if size >= 0 else None
        with self._lock:
            self._before.setdefault(path, (size, digest))

    def tried(self, url: str) -> None:
        """`url` was requested past robots.txt this run: its file is in HTTrack's save-name
        table, so a copy it then leaves is no deletion (htscore.c:2196-2204)."""
        try:
            k = url_key(url)
        except ValueError:
            return
        with self._lock:
            self._tried.add(k)

    def _rel(self, path: str) -> str:
        return os.path.relpath(path, self.root).replace(os.sep, "/")

    def report(self, order: Iterable[str], written: Collection[str], urls: Mapping[str, str],
               fields: Mapping[str, dict]) -> tuple[str, str]:
        """(hts-changes.json, the run's summary line) for the files of this run, `order`
        being the order they were reached in, `written` the ones it wrote, `urls` the URL
        requested for each and `fields` the record of its response or of its kept copy
        (htschanges.c changes_resolve, changes_serialize, hts_changes_close_opt)."""
        old_index = self.indexed and bool(self.listed)
        entries, seen = [], set()  # (bucket, url, file, size, previous size)
        for path in order:
            if path in seen:
                continue
            seen.add(path)
            size = _fsize(path)
            bucket, prev_size = "unchanged", size  # a file left alone (189-206)
            if path in written:
                prev_size, prev_digest = self._before.get(path, (-1, None))
                if not (path in self.listed if old_index else prev_size >= 0):
                    bucket = "new"
                elif hypertext(fields[path].get("content_type")) and size > 0:
                    # a parsed file: its payload against the cache's previous body (299-345)
                    e = self.listed.get(path)
                    old = e.payload_md5 if e is not None and _ok(e.status) else None
                    new = fields[path].get("payload_md5")
                    bucket = "unchanged" if old and new == old else "changed"
                elif size >= 0 and prev_size >= 0 and size != prev_size:
                    bucket = "changed"  # different lengths: no need to hash (431-435)
                else:
                    now = _md5_file(path) if prev_digest is not None else None
                    # no digest: a 200 is the "updated" signal, so changed (201-205)
                    bucket = "unchanged" if now is not None and now == prev_digest else "changed"
            url = recordable_url(urls[path]) or ""  # the manifest's rule for the URL requested
            entries.append((bucket, url, self._rel(path), size, prev_size))
        if self.indexed:  # old.lst minus new.lst, still on disk (htscore.c:2186-2210)
            for path in sorted(self.listed):
                e = self.listed[path]
                if path in seen or not os.path.isfile(path):
                    continue
                try:
                    tried = bool(e.url) and url_key(e.url) in self._tried
                except ValueError:
                    tried = False
                entries.append(("unchanged" if tried else "gone", "", self._rel(path),
                                _fsize(path) if tried else -1, -1))
        counts = {b: sum(1 for e in entries if e[0] == b) for b in BUCKETS}
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        out = ['{\n  "schema": ', str(SCHEMA), ',\n  "generator": ', json_string(GENERATOR),
               ',\n  "date": ', json_string(now), ',\n  "first_crawl": ',
               "null" if not self.indexed else "false" if old_index else "true",
               ',\n  "partial": false',
               ',\n  "purged": false',  # the profile never purges (spec 5.6)
               ',\n  "counts": { ', ", ".join(f"{json_string(b)}: {counts[b]}" for b in BUCKETS),
               " }"]
        for b in BUCKETS:
            out.append(f",\n  {json_string(b)}: [")
            items = [e for e in entries if e[0] == b]
            for i, (_, url, file, size, prev_size) in enumerate(items):
                out.append(("\n" if i == 0 else ",\n") + '    { "url": ' + json_string(url)
                           + ', "file": ' + json_string(file))
                if size >= 0:
                    out.append(f', "size": {size}')
                if b == "changed" and prev_size >= 0:
                    out.append(f', "previous_size": {prev_size}')
                out.append(" }")
            out.append("\n  ]" if items else "]")
        out.append("\n}\n")
        if not self.indexed:
            line = (f"Change report: no mirror index (the cache is off), {len(entries)} files "
                    f"mirrored, deletions not detected ({CHANGES_FILE})")
        elif not old_index:
            line = (f"Change report: first crawl, {len(entries)} files mirrored, nothing to "
                    f"compare against ({CHANGES_FILE})")
        else:
            line = (f"Change report: {counts['new']} new, {counts['changed']} changed, "
                    f"{counts['unchanged']} unchanged, {counts['gone']} gone ({CHANGES_FILE})")
        return "".join(out), line
