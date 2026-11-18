"""HTTrack's link extraction (htsparse.c), dedup key (htshash.c, -%u) and link rewriting (-K0).

Links come from ``href`` and the attribute table of htsparse.c:191-232 (``src``,
``srcset``, ``data-src``, ``poster``, ``background``...) and ``<meta http-equiv=refresh>``.
``<base href>`` applies to the links after it, ``action`` is never a link, and while
robots.txt is obeyed a ``<meta name=robots content=nofollow>`` ends extraction
(htsparse.c:2045-2068).

Scripts are scanned as HTTrack scans them: ``<script>`` and ``<style>`` bodies, ``onXxx=``
and ``style=`` values, ``javascript:`` URLs, and fetched stylesheets and scripts run through
its quote/comment automaton (htsparse.c:97-136, 1229-1254). With -j on (``parse_scripts``),
each byte outside strings and comments is tried against hts_js_scan_link's keywords
(``.src=``, ``location=``, ``.open(``, ``url(``, ``import``, ``from``...; CSS ``url()`` and
``@import`` are the same scan); with -%P on (``extended_parsing``), a quoted string after
``=``, ``(`` or ``,`` in a tag or a script is a link when it looks like one
(hts_dirty_link_is_url, htsparse.c:2160-2276). Both are on by default, as in HTTrack.
Their contexts are the ones this tokenizer reads (a script attribute is its HTML5 value);
inside one, HTTrack's byte rules apply (jsscan.py), reading the page past it where HTTrack
does. Links found by these scans are followed but not rewritten.

Pages are read as UTF-8 with surrogateescape, so every byte survives a rewrite; a URL
holding a byte that is not UTF-8 is not a usable link. The tokenizer is this module's own,
not html.parser: before CPython's 2025 fixes (3.10.18 here) html.parser is quadratic on
unclosed tags, and a crawl must stay linear on any page. It reads start tags and their
attributes as HTML5 does, skips comments, declarations and end tags, and takes <script>
and <style> bodies as raw text; a tag that never closes ends the page. The script scans
jump with regexes and bound every look-ahead, so they stay linear too.
"""

import html
import logging
import os
import re
from collections.abc import Mapping
from typing import NamedTuple
from urllib.parse import urljoin, urlsplit

from ...utils.redact import redact_url
from .jsscan import (
    NEUTRAL, QUOTES, REAL, URL_MAX, Ctx, at, dirty, field, scan_script, unescape_attr)
from .policy import FetchMeta

logger = logging.getLogger(__name__)

# htsparse.c hts_attrs, HTS_ATTR_LINK rows (href is matched apart, as rech_tageq "href")
_LINK_ATTRS = frozenset("""archive background data data-src data-srcset dynsrc lowsrc profile
src srcset swurl url usemap longdesc xlink:href poster""".split())
_SRCSET = frozenset({"srcset", "data-srcset"})
# htsparse.c data_attr_is_not_url
_PLACEHOLDERS = frozenset("lazy placeholder none null undefined false true blank empty".split())

# htsfetch.c hts_fetch_classify: (tag, attribute) -> Sec-Fetch-Dest; "background" on any tag
_DEST = {("a", "href"): "document", ("area", "href"): "document", ("iframe", "src"): "iframe",
         ("frame", "src"): "frame", ("object", "data"): "object", ("embed", "src"): "embed",
         ("img", "src"): "image", ("img", "srcset"): "image", ("img", "data-src"): "image",
         ("img", "data-srcset"): "image", ("source", "srcset"): "image",
         ("input", "src"): "image", ("video", "poster"): "image", ("video", "src"): "video",
         ("audio", "src"): "audio", ("script", "src"): "script"}
_NAVIGATIONS = frozenset({"document", "iframe", "frame", "object", "embed"})
_FRAMES = frozenset({"document", "iframe", "frame"})  # hts_fetch_same_frame
# htsfetch.c, links of a stylesheet: the path decides
_CSS_EXT_DEST = {"css": "style", **dict.fromkeys(("woff2", "woff", "ttf", "otf", "eot"), "font"),
                 **dict.fromkeys(("png", "jpg", "jpeg", "gif", "webp", "avif", "ico", "bmp"),
                                 "image")}
_PRELOAD_AS = frozenset({"style", "script", "image", "font"})

_REFRESH_URL = re.compile(r"url=", re.IGNORECASE)
_NAME_ATTR = re.compile(r"\sname\s*=", re.IGNORECASE)
# HTML5 tokenizer pieces; each match consumes what it scans, so a page is read in linear time
_TAG_NAME = re.compile(r"[a-zA-Z][^\t\n\r\f />]*")
_SKIP = re.compile(r"[\t\n\r\f /]*")
_ATTR = re.compile(r"""([^\t\n\r\f />][^\t\n\r\f /=>]*)"""
                   r"""(?:[\t\n\r\f ]*=[\t\n\r\f ]*("[^"]*"|'[^']*'|[^\t\n\r\f >]*))?""")
_RAW_END = {t: re.compile(rf"</{t}[\t\n\r\f />]", re.IGNORECASE) for t in ("script", "style")}


class Link(NamedTuple):
    url: str  # absolute, without its fragment
    meta: FetchMeta


def url_key(url: str) -> str:
    """HTTrack's dedup key (htshash.c hash_url_key, -%u on): host and port without scheme or
    login, case-insensitive; the path with "//" collapsed; query fields sorted; no fragment.
    Its "www." folding is left out: the crawl never leaves the start host."""
    p = urlsplit(url)
    path = re.sub("/{2,}", "/", p.path) or "/"
    query = "&".join(sorted(p.query.split("&"))) if p.query else ""
    return p.netloc.rpartition("@")[2].lower() + path + ("?" + query if query else "")


def _strip(value: str) -> tuple[int, int]:
    start = len(value) - len(value.lstrip())
    return start, len(value.rstrip())


def _srcset(value: str) -> list[tuple[int, int]]:
    """Spans of the candidate URLs; only a trailing comma splits (htsparse.c srcset_next)."""
    spans, i, n = [], 0, len(value)
    while i < n:
        while i < n and (value[i].isspace() or value[i] == ","):
            i += 1
        j = i
        while j < n and not value[j].isspace():
            j += 1
        end = j
        while end > i and value[end - 1] == ",":
            end -= 1
        if end > i:
            spans.append((i, end))
        i = j
        if end == j:  # no trailing comma: the descriptor runs to the next one
            while i < n and value[i] != ",":
                i += 1
    return spans


def _refresh(value: str) -> list[tuple[int, int]]:
    """Span of the URL= part of a refresh's content, looked for in its first 128 characters."""
    m = _REFRESH_URL.search(value, 0, 128 + 4)
    if not m:
        return []
    i, end = m.end(), len(value)
    if value[i:i + 1] in ("'", '"'):
        i += 1
        close = value.find(value[i - 1], i)
        end = close if close >= 0 else end
    start, stop = _strip(value[i:end])
    return [(i + start, i + stop)] if stop > start else []


def _placeholder(value: str) -> bool:
    v = value.strip()
    head = v.split("?", 1)[0]  # a query may carry JSON
    return any(c in head for c in '{}<>"') or v.lower() in _PLACEHOLDERS


def _css_meta(url: str) -> FetchMeta:
    ext = os.path.splitext(urlsplit(url).path)[1][1:].lower()
    dest = _CSS_EXT_DEST.get(ext, "")
    return FetchMeta(dest, "cors" if dest == "font" else "no-cors", False)


def _usable(url: str) -> str | None:
    """`url` without fragment when it is an http(s) URL a request can carry, else None."""
    try:
        parts = urlsplit(url)
        url.encode("utf-8")  # a lone surrogate (a byte that is not UTF-8) cannot be sent
    except (ValueError, UnicodeEncodeError):
        return None
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None
    return parts._replace(fragment="").geturl()


_NO_META = FetchMeta("", "no-cors", False)  # parse_fetch_meta: a script's link (htsparse.c:819)
# htslib.h:893-897 is_javascript_mime_type: the types whose body is scanned as a script
JS_MIMES = frozenset(("text/javascript", "application/javascript", "application/x-javascript",
                      "application/ecmascript"))
# htsparse.c:212-234: the onXxx= rows of hts_attrs (any other needs an upper-case X)
_EVENTS = frozenset("""onabort onblur onchange onclick ondblclick ondragdrop onerror onfocus
onkeydown onkeypress onkeyup onload onmousedown onmousemove onmouseout onmouseover onmouseup
onmove onreset onresize onselect onsubmit onunload""".split())
_TAG_EVENT = re.compile("[\"']|[ \t\n\v\f\r]+")      # a quote, or blanks (intag_startattr)
_NAME_END = re.compile("[=\"' \n\r\t\f\v]")          # strcspn(.., "=" HTS_SPACES)


class _Hit(NamedTuple):
    vspan: tuple[int, int] | None  # the attribute value as written; None: a script's link
    value: str             # that value, unescaped
    tag: str
    attrs: dict            # first value of each attribute of the tag
    name: str              # attribute holding the link; "css" / "script" / "" for a scan's
    span: tuple[int, int]  # the URL's span in `value`
    raw: str               # the URL as written
    url: str | None        # absolute, no fragment; None when unusable
    follow: bool           # False once a meta robots nofollow was seen


class _Scan:
    def __init__(self, text: str, url: str, robots: bool, parse_scripts: bool,
                 extended: bool):
        self.text, self.base, self.robots = text, url, robots
        self.parse_scripts, self.extended = parse_scripts, extended
        self.hits: list[_Hit] = []
        self.base_hrefs: list[tuple[int, int]] = []  # value spans of each <base href>
        self.base_target = self.nofollow = False
        self._sa: tuple[int, str] = (-1, "")  # intag_startattr and the name read there
        i, n = 0, len(text)
        while (j := text.find("<", i)) >= 0:
            nxt = text[j + 1:j + 2]
            if text.startswith("<!--", j):
                if text.startswith((">", "->"), j + 4):  # <!--> and <!---> are empty comments
                    i = text.index(">", j + 4) + 1
                else:
                    end = text.find("-->", j + 4)
                    i = n if end < 0 else end + 3
            elif nxt in ("!", "?", "/"):  # declaration, processing instruction, end tag
                end = text.find(">", j + 2)
                i = n if end < 0 else end + 1
            elif nxt.isascii() and nxt.isalpha():
                i = self._start_tag(text, j)
            else:
                i = j + 1
            if i >= n:
                break

    def _start_tag(self, text: str, j: int) -> int:
        """Read the start tag at `j`; return where scanning resumes (len(text): the page ends)."""
        m = _TAG_NAME.match(text, j + 1)
        tag, k, n = m.group().lower(), m.end(), len(text)
        attrs: list[tuple] = []  # (name, value, value span, name start, "=" index)
        while True:
            k = _SKIP.match(text, k).end()
            if k >= n:
                return n  # a tag that never closes: nothing after it is read
            if text[k] == ">":
                break
            a = _ATTR.match(text, k)
            raw = a.group(2)
            value = None if raw is None else unescape_attr(
                raw[1:-1] if raw[:1] in "'\"" and len(raw) > 1 and raw[-1] == raw[0] else raw)
            attrs.append((a.group(1).lower(), value, a.span(2) if raw is not None else None,
                          a.start(1), text.find("=", a.end(1)) if raw is not None else -1))
            k = a.end()
        skip = self._tag(tag, attrs, j, k)
        if tag in _RAW_END:
            end = _RAW_END[tag].search(text, k + 1)
            stop = end.start() if end else n
            if self.parse_scripts or self.extended:
                self.hits += [h for _, h in self._script(
                    k + 1, stop, Ctx(css=tag == "style"),
                    self._lastc(k, j, skip[-1] if skip else (0, 0)), tag)]
            return stop
        return k + 1

    def _resolve(self, raw: str) -> str | None:
        if not raw or raw.startswith("#") or len(raw) > URL_MAX:
            return None
        try:
            return _usable(urljoin(self.base, raw))
        except ValueError:
            return None

    def _lastc(self, q: int, j: int, skipped: tuple[int, int]) -> str:
        """parseall_lastc at t[q] in the tag opened at t[j]: the last byte before it that
        is no blank, neutral when an attribute value read as a link holds it."""
        t, r = self.text, q - 1
        while r > j and t[r] in REAL:
            r -= 1
        return NEUTRAL if r <= j or skipped[0] <= r < skipped[1] else t[r]

    def _script(self, i: int, end: int, ctx: Ctx, lastc: str, tag: str,
                attrs: dict | None = None) -> list[tuple[int, _Hit]]:
        """The links of the script t[i:end], each with its position."""
        name = "css" if ctx.css else "script"
        return [(pos, _Hit(None, "", tag, attrs or {}, name, (0, 0), raw,
                           self._resolve(unescape_attr(raw)), not self.nofollow))
                for pos, raw, _ in scan_script(self.text, i, end, ctx, lastc,
                                                self.parse_scripts, self.extended)]

    def _attr_script(self, tag: str, amap: dict, j: int, start: int, vend: int,
                     lastq: str, ctx: Ctx) -> list[tuple[int, _Hit]]:
        """An onXxx=/style= value or a javascript: URL, from `start`: HTTrack leaves it at the
        next `lastq` byte or ">" (htsparse.c:1658-1672, 1749-1760), here within the value."""
        t = self.text
        stop = vend
        for ch in {lastq, ">"} - {""}:
            if (k := t.find(ch, start, stop)) >= 0:
                stop = k
        return self._script(start, stop, ctx._replace(in_tag=True, tag_lastc=lastq,
                                                      tag_start=j),
                            lastq if lastq and lastq not in REAL else NEUTRAL, tag, amap)

    def _tag(self, tag: str, attrs: list, j: int, k: int) -> list[tuple[int, int]]:
        """Record the links of the tag t[j:k+1]; return the spans HTTrack reads as links or
        scripts (from the attribute name's second byte on), which -%P leaves alone."""
        t = self.text
        raw_tag = t[j:k + 1]
        amap: dict = {}
        for name, value, *_ in attrs:
            amap.setdefault(name, value)
        if tag == "meta" and self.robots and not self.nofollow:
            m = _NAME_ATTR.search(raw_tag)
            tail = raw_tag[m.start() + 1:].split(">", 1)[0].lower() if m else ""
            if m and len(tail) < 999 and all(w in tail for w in ("content", "robots", "nofollow")):
                self.nofollow = True
                logger.info("links after the robots meta tag of %s not followed",
                            redact_url(self.base))  # the page's own <base href> may set it
        refresh = (tag == "meta"
                   and (amap.get("http-equiv") or "").strip().lower().startswith("refresh"))
        scan = self.parse_scripts or self.extended
        skip: list[tuple[int, int]] = []
        found: list[tuple[int, _Hit]] = []  # with its position: links leave in page order
        for name, value, vspan, nstart, eq in attrs:
            if value is None:
                continue
            if tag == "base" and name == "target":
                self.base_target = True
            if tag == "base" and name == "href":
                self.base_hrefs.append(vspan)
                skip.append((nstart + 1, vspan[1]))
                start, stop = _strip(value)
                try:
                    self.base = urljoin(self.base, value[start:stop])
                except ValueError:
                    pass  # an unusable base leaves the current one, as a browser does
                continue
            raw_name = t[nstart:eq].rstrip(" \t\n\r\f\v\"'")
            if name == "style" or name in _EVENTS or (  # htsparse.c:1945-1980
                    raw_name[:2] == "on" and raw_name[2:3].isascii() and raw_name[2:3].isupper()
                    and raw_name.isascii() and raw_name.isalpha() and len(raw_name) < 64):
                skip.append((nstart + 1, vspan[1]))
                if scan:
                    found += self._attr_script(tag, amap, j, eq + 2, vspan[1], at(t, eq + 1),
                                               Ctx(css=name == "style"))
                continue
            if name == "href" or name in _LINK_ATTRS or name == "action" or (
                    name == "content" and refresh):
                skip.append((nstart + 1, vspan[1]))
                q = t[vspan[0]] if t[vspan[0]:vspan[0] + 1] in ("'", '"') else ""
                if scan and name != "content" and field(t, vspan[0] + len(q), "javascript:"):
                    found += self._attr_script(tag, amap, j, vspan[0] + len(q) + 1, vspan[1],
                                               q, Ctx())
            if name == "href" or name in _LINK_ATTRS:
                if name.startswith("data-") and _placeholder(value):
                    continue
                spans = _srcset(value) if name in _SRCSET else [_strip(value)]
            elif name == "content" and refresh:
                spans = _refresh(value)
            else:
                continue
            for a, b in spans:
                raw = value[a:b]
                found.append((vspan[0] + a, _Hit(vspan, value, tag, amap, name, (a, b), raw,
                                                 self._resolve(raw), not self.nofollow)))
        if self.extended:
            found += self._tag_dirty(tag, amap, j, k, skip)
        found.sort(key=lambda f: f[0])
        self.hits += [h for _, h in found]
        return skip

    def _tag_dirty(self, tag: str, amap: dict, j: int, k: int,
                   skip: list[tuple[int, int]]) -> list[tuple[int, _Hit]]:
        """-%P in the tag t[j:k+1] (htsparse.c:2160-2276): each quote outside `skip` opening
        a string after "=", "(" or "," that names a file is a link, unless its attribute
        never holds one."""
        t, xi, last = self.text, 0, (0, 0)
        pos, found = j + 1, []
        while (m := _TAG_EVENT.search(t, pos, k)) is not None:
            p = m.start()
            while xi < len(skip) and skip[xi][1] <= p:
                last, xi = skip[xi], xi + 1
            if xi < len(skip) and skip[xi][0] <= p:
                last, pos, xi = skip[xi], skip[xi][1], xi + 1
                continue
            if t[p] not in QUOTES:
                self._sa = (m.end(), "")  # intag_startattr, the attribute after the blanks
                pos = m.end()
                continue
            sa, name = self._sa
            if sa >= 0 and not name:
                stop = _NAME_END.search(t, sa)
                name = t[sa:stop.start() if stop else len(t)]
                self._sa = (sa, name)
            got = dirty(t, p, self._lastc(p, j, last), False, j, name if sa >= 0 else None)
            if got is None:
                pos = p + 1
                continue
            raw, term = got
            if raw:
                found.append((p + 1, _Hit(None, "", tag, amap, "", (0, 0), raw,
                                          self._resolve(unescape_attr(raw)),
                                          not self.nofollow)))
            last, pos = (p + 1, term + 1), term + 1
        return found


def _target(target, frame: str) -> str:
    """htsfetch.c link_target_dest: the frame a click with this target loads."""
    if target is None or target == "_self":
        return frame
    if target in ("_top", "_blank") or (target == "_parent" and frame == "document"):
        return "document"
    return ""


def _link_rel(attrs: dict) -> tuple[str, bool]:
    """htsfetch.c link_dest: a <link href>'s destination (and CORS) from rel and as."""
    rel = (attrs.get("rel") or "").lower().split()
    if "stylesheet" in rel:
        return "style", False
    if "icon" in rel:
        return "image", False
    if "modulepreload" in rel:
        return "script", True
    as_ = (attrs.get("as") or "").lower()
    return (as_ if "preload" in rel and as_ in _PRELOAD_AS else ""), False


def _classify(hit: _Hit, page_frame: str, link_frame: str) -> FetchMeta:
    """htsfetch.c hts_fetch_classify (and parse_fetch_meta for a refresh)."""
    if hit.vspan is None:  # a stylesheet's link goes by its path, a script's sends nothing
        return _css_meta(hit.url or "") if hit.name == "css" else _NO_META
    attrs, user, cors = hit.attrs, False, False
    if hit.tag == "meta":  # a refresh navigates whatever frame holds the page
        dest = page_frame
    elif hit.tag == "link" and hit.name == "href":
        dest, cors = _link_rel(attrs)
    else:
        dest = _DEST.get((hit.tag, hit.name)) or ("image" if hit.name == "background" else "")
    if dest == "document" and hit.tag != "meta":
        dest = "" if "download" in attrs else _target(attrs.get("target"), link_frame)
        user = "download" not in attrs
    module = dest == "script" and (attrs.get("type") or "").lower() == "module"
    cors = cors or "crossorigin" in attrs or module
    mode = ("navigate" if dest in _NAVIGATIONS
            else "cors" if cors or dest == "font" else "no-cors")
    return FetchMeta(dest, mode, user)


def _decode(body: bytes) -> str:
    return body.decode("utf-8", errors="surrogateescape")


def page_links(body: bytes, url: str, *, frame: str = "document", robots: bool = True,
               parse_scripts: bool = True, extended_parsing: bool = True) -> list[Link]:
    """Links of the HTML page `body` fetched from `url` as Sec-Fetch-Dest `frame`, in
    document order. `robots` (robots.txt obeyed) makes meta robots nofollow count;
    `parse_scripts` is HTTrack's script scan (-j), `extended_parsing` its -%P."""
    scan = _Scan(_decode(body), url, robots, parse_scripts, extended_parsing)
    page_frame = frame if frame in _FRAMES else ""
    link_frame = "" if scan.base_target else page_frame
    return [Link(h.url, _classify(h, page_frame, link_frame))
            for h in scan.hits if h.url and h.follow]


def _file_links(body: bytes, url: str, base: str, css: bool, parse_scripts: bool,
                extended: bool) -> list[Link]:
    """The links of a whole stylesheet or script: HTTrack parses it as one script body
    (htsparse.c:1264-1287), its links resolved against `base`, a module specifier's
    against the file itself."""
    out, text = [], _decode(body)
    for _, raw, module in scan_script(text, 0, len(text), Ctx(css, css), "\0",
                                       parse_scripts, extended):
        raw = unescape_attr(raw)
        if len(raw) <= URL_MAX:
            try:
                u = _usable(urljoin(url if module else base, raw))
            except ValueError:
                u = None
            if u:
                out.append(Link(u, _css_meta(u) if css else _NO_META))
    return out


def css_links(body: bytes, url: str, *, parse_scripts: bool = True,
              extended_parsing: bool = True) -> list[Link]:
    """url() and @import links of the stylesheet `body` fetched from `url`: HTTrack's script
    scan of a stylesheet (-j), with -%P (`extended_parsing`) on its strings."""
    return _file_links(body, url, url, True, parse_scripts, extended_parsing)


def script_links(body: bytes, url: str, parent: str, *, parse_scripts: bool = True,
                 extended_parsing: bool = True) -> list[Link]:
    """Links of the script `body` fetched from `url`, linked from the page `parent`: a
    script's links take that page's base, bar a module specifier (htsparse.c:1280-1285,
    htscore.h:276); they carry no fetch metadata (htsparse.c:819-820)."""
    return _file_links(body, url, parent, False, parse_scripts, extended_parsing)


def _local_ref(path: str, page_path: str) -> str:
    rel = os.path.relpath(path, os.path.dirname(page_path)).replace(os.sep, "/")
    return rel.replace("%", "%25").replace("#", "%23")  # a name holding them is no URL syntax


def _new_value(value: str, hits: list[_Hit], page_path: str, local: Mapping[str, str]) -> str:
    for h in sorted(hits, key=lambda h: h.span, reverse=True):
        fragment = h.raw[h.raw.index("#"):] if "#" in h.raw else ""
        saved = local.get(url_key(h.url))
        if saved is not None:
            ref = _local_ref(saved, page_path) + fragment
        elif urlsplit(h.raw).scheme:
            continue  # already absolute
        else:
            ref = h.url + fragment
        value = value[:h.span[0]] + ref + value[h.span[1]:]
    return value


def rewrite_links(body: bytes, url: str, path: str, local: Mapping[str, str]) -> bytes:
    """`body` (an HTML page fetched from `url`, saved at `path`) with HTTrack -K0 links: a
    link to a saved file becomes a relative path to it, any other relative link becomes
    absolute, and <base href> is blanked so the relative links resolve on disk. `local`
    maps url_key() to saved paths. Bytes outside the rewritten attribute values are kept;
    a page with nothing to rewrite is returned as is."""
    text = _decode(body)
    scan = _Scan(text, url, robots=False, parse_scripts=False, extended=False)
    values: dict[tuple[int, int], list[_Hit]] = {}
    for h in scan.hits:
        if h.vspan is not None and h.url:
            values.setdefault(h.vspan, []).append(h)
    edits = {vspan: "" for vspan in scan.base_hrefs if text[vspan[0]:vspan[1]] not in ('""', "''")}
    for vspan, hits in values.items():
        new = _new_value(hits[0].value, hits, path, local)
        if new != hits[0].value:
            edits[vspan] = new
    if not edits:
        return body
    out, last = [], 0
    for (start, stop), new in sorted(edits.items()):
        out += [text[last:start], '"', html.escape(new, quote=True), '"']
        last = stop
    out.append(text[last:])
    return "".join(out).encode("utf-8", errors="surrogateescape")
