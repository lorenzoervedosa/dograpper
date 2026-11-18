"""HTTrack-style local file naming, layout-compatible with wget --adjust-extension.

``<output>/<host>/<path>``: directory URLs become ``index.html``. HTML responses
without ``.html``/``.htm`` get ``.html``: like HTTrack, it replaces any extension
HTTrack knows (``notes.txt`` -> ``notes.html``, ``foo.cgi?q=45`` -> ``foo<hash>.html``)
and is appended to an unknown one (``article-1.884291`` -> ``article-1.884291.html``).
Characters HTTrack forbids in saved names become ``_``. Pure path computation: never
creates directories or files.

Out of scope: Windows reserved names (CON, NUL...), trailing dots/spaces, over-long names.
"""

import hashlib
import os
import threading
from urllib.parse import unquote, urlsplit

from ...utils.portable_names import FORBIDDEN, claim_unique, resolve_under

_DEFAULT_PORTS = {"http": 80, "https": 443}
# Names that may hold a page whatever their extension says: htsmime.c hts_ext_dynamic,
# htslib.c ishtml_ext and a bare trailing dot.
PAGE_EXTS = frozenset("." + e for e in """
php3 php php4 php2 cgi asp jsp pl cfm nsf shtml phtml htmlx shtm phtm htmx htm html
""".split()) | {"."}
# An HTML page gets .html in place of these, not after them (htsname.c:1200-1215, R14): the
# page extensions and every extension of htsmime.c hts_mime + hts_mime_modern (is_knowntype).
KNOWN_EXTS = PAGE_EXTS | frozenset("." + e for e in """
323 7z aab aac aam aas acx ai aif aifc aiff arj asf asr asx au avi avif axs bas bcpio bin
bmp bz2 c cat cc ccad cco cdf cer cgi class clp cmx cod cpio cpt crd crl crt csh css dcr
der dir dms doc docx dot dotx drw dtd dvi dwf dwg dxf dxr eps etx evy f90 fh fh4 fh5 fh7
fhc fif flac flr g gif gtar gz gzip h hdf heic hh hlp hqx hta htc htm html htt ice ico ief
iges iii ins isg isp jfif jpe jpeg jpg js json jsonld kar ksh latex lha lsf lsx lzh m m13
m14 m3u m4a man md mdb me mesh mht mhtml mid midi mif mjs mny mov movie mp2 mp3 mp4 mpa mpe
mpeg mpg mpga mpp mpv2 ms msh mvb nc nws oda odb odc odf odg odi odm odp ods odt oga ogg
ogv opus otf otg oth otp ots ott p10 p12 p7b p7c p7m p7r p7s part pbm pdb pdf pfx pgm pict
pko pma pmc pml pmr pmw png pnm pot potx ppm pps ppsx ppt prf prt ps pub qt ra ram rar ras
rgb rm rmi roff rpm rtf rtx scd sct set setpay setreg sgm sgml sh shar silo sit skd skm skp
skt sldx smi smil sml snd sol spc spl src sst step stl stm stp sv4cpio sv4crc svg swf t tar
tcl tex texi texinfo tgz tif tiff torrent tr trm ts tsv ttf txt uls unv ustar vcd vcf vda
vrml w6w wasm wav wcm wdb weba webm webmanifest webp wks wmf wmv woff woff2 word wps wri
wrl wrz xaf xbm xla xlc xlm xls xlsx xlt xltx xlw xml xof xpm xwd xyz z zip zst
""".split())


class NameRegistry:
    def __init__(self, output_dir: str):
        self._root = os.path.realpath(output_dir)
        self._lock = threading.Lock()
        self._by_url: dict[str, str | None] = {}
        self._used: set[str] = set()
        self._spare: set[str] = set()  # reserved names not given back yet

    def reserve(self, path: str) -> None:
        """Keep `path` (absolute, real), a file an earlier run saved and this one may keep
        unchanged, from every URL that does not ask for it (assign's `prefer`)."""
        with self._lock:
            self._used.add(path.casefold())
            self._spare.add(path)

    def name_of(self, url: str, content_type: str | None) -> str | None:
        """The name ``url`` would get with no other name taken; claims nothing."""
        return self._compute(urlsplit(url), content_type)

    def assign(self, url: str, content_type: str | None, prefer: str | None = None) -> str | None:
        """Return the absolute local path for ``url``, or None if unsafe. ``prefer``, a
        reserved name not given back yet, is the file ``url`` was saved to last time."""
        parts = urlsplit(url)
        key = parts._replace(fragment="").geturl()
        with self._lock:
            if key in self._by_url:
                return self._by_url[key]
            if prefer in self._spare:
                self._spare.discard(prefer)
                path = prefer
            else:
                path = self._compute(parts, content_type)
                if path is not None:
                    path = claim_unique(path, self._used)
            self._by_url[key] = path
            return path

    def _compute(self, parts, content_type: str | None) -> str | None:
        host = parts.hostname
        if not host or "\x00" in parts.geturl() or host in (".", ".."):
            return None
        if ":" in host:  # IPv6 literal: HTTrack names the dir [addr], its colons then "_"
            host = f"[{host}]"
        host = host.translate(FORBIDDEN)
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
        decoded = decoded.translate(FORBIDDEN)
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
            # shortcut: no htssniff.c magic check, so a real PDF served as text/html still
            # gets doc.html where HTTrack keeps doc.pdf; upgrade if mislabeled binaries matter.
            ext = ".html" if ext.lower() in KNOWN_EXTS else ext + ".html"
        return resolve_under(self._root, host, *segs, stem + ext)
