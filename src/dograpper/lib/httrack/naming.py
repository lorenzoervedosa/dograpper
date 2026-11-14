"""HTTrack-style local file naming, layout-compatible with wget --adjust-extension.

``<output>/<host>/<path>``: directory URLs become ``index.html``. HTML responses
without ``.html``/``.htm`` get ``.html``: like HTTrack, it replaces a dynamic or
HTML-family extension (``foo.cgi?q=45`` -> ``foo<hash>.html``) and is appended to
anything else. Characters HTTrack forbids in saved names become ``_``. Pure path
computation: never creates directories or files.

Out of scope: Windows reserved names (CON, NUL...), trailing dots/spaces, over-long names.
"""

import hashlib
import os
import threading
from urllib.parse import unquote, urlsplit

_DEFAULT_PORTS = {"http": 80, "https": 443}
# htsname.c: replaced by "_" in every saved name, on every platform
_FORBIDDEN = {c: "_" for c in [*range(32), 127, *map(ord, '~\\:*?"<>|')]}
# htsmime.c hts_ext_dynamic + htslib.c ishtml_ext (and a bare trailing dot): an HTML page
# gets .html in place of these, not after them (htsname.c, R14)
_REPLACED_EXTS = frozenset({".php3", ".php", ".php4", ".php2", ".cgi", ".asp", ".jsp", ".pl",
                            ".cfm", ".nsf", ".shtml", ".phtml", ".htmlx", ".shtm", ".phtm",
                            ".htmx", "."})


class NameRegistry:
    def __init__(self, output_dir: str):
        self._root = os.path.realpath(output_dir)
        self._lock = threading.Lock()
        self._by_url: dict[str, str | None] = {}
        self._used: set[str] = set()

    def assign(self, url: str, content_type: str | None) -> str | None:
        """Return the absolute local path for ``url``, or None if unsafe."""
        parts = urlsplit(url)
        key = parts._replace(fragment="").geturl()
        with self._lock:
            if key in self._by_url:
                return self._by_url[key]
            path = self._compute(parts, content_type)
            if path is not None:
                path = self._dedupe(path)
                self._used.add(path)
            self._by_url[key] = path
            return path

    def _dedupe(self, path: str) -> str:
        base, ext = os.path.splitext(path)
        n, cand = 1, path
        while cand in self._used:
            n += 1
            cand = f"{base}-{n}{ext}"
        return cand

    def _compute(self, parts, content_type: str | None) -> str | None:
        host = parts.hostname
        if not host or "\x00" in parts.geturl() or host in (".", ".."):
            return None
        host = host.translate(_FORBIDDEN)
        try:
            port = parts.port
        except ValueError:
            return None
        # wget names the host dir host:port only for a non-default explicit port.
        if port is not None and port != _DEFAULT_PORTS.get(parts.scheme):
            host = f"{host}:{port}"

        decoded = unquote(parts.path)
        if "\x00" in decoded:
            return None
        decoded = decoded.translate(_FORBIDDEN)
        is_dir = decoded.rsplit("/", 1)[-1] in ("", ".", "..")
        segs: list[str] = []
        for seg in decoded.split("/"):
            if seg == "..":
                if not segs:
                    return None  # would escape the host directory
                segs.pop()
            elif seg not in ("", "."):
                segs.append(seg)
        name = "index.html" if is_dir or not segs else segs.pop()

        stem, ext = os.path.splitext(name)
        if parts.query:
            stem += hashlib.md5(parts.query.encode()).hexdigest()[:4]
        is_html = (content_type or "").split(";")[0].strip().lower() == "text/html"
        if is_html and ext.lower() not in (".html", ".htm"):
            ext = ".html" if ext.lower() in _REPLACED_EXTS else ext + ".html"
        full = os.path.realpath(os.path.join(self._root, host, *segs, stem + ext))
        if os.path.commonpath([self._root, full]) != self._root:
            return None
        return full
