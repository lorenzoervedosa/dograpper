"""HTTrack's link extraction (htsparse.c), dedup key (htshash.c, -%u) and link rewriting (-K0).

Links come from ``href`` and the attribute table of htsparse.c:191-232 (``src``,
``srcset``, ``data-src``, ``poster``, ``background``...), ``<meta http-equiv=refresh>``
and CSS ``url()``/``@import`` (``<style>``, ``style=``, stylesheets). ``<base href>``
applies to the links after it, ``action`` is never a link, and while robots.txt is
obeyed a ``<meta name=robots content=nofollow>`` ends extraction (htsparse.c:2045-2068).

Temporary gap, not a deviation: HTTrack's JavaScript scan (-j) and "dirty" parsing of
unknown attributes and script strings (-%P, htsparse.c:2160-2276) are not ported yet, so
links only a script names are not followed. A follow-up PR under #78 (#122) ports both onto
this tokenizer.

Pages are read as UTF-8 with surrogateescape, so every byte survives a rewrite; a URL
holding a byte that is not UTF-8 is not a usable link. The tokenizer is this module's own,
not html.parser: before CPython's 2025 fixes (3.10.18 here) html.parser is quadratic on
unclosed tags, and a crawl must stay linear on any page. It reads start tags and their
attributes as HTML5 does, skips comments, declarations and end tags, and takes <script>
and <style> bodies as raw text; a tag that never closes ends the page.
"""

import html
import logging
import os
import re
from collections.abc import Mapping
from html.entities import html5 as _ENTITIES
from typing import NamedTuple
from urllib.parse import urljoin, urlsplit

from ...utils.redact import redact_url
from .policy import FetchMeta

logger = logging.getLogger(__name__)

URL_MAX = 1024  # htsglobal.h HTS_URLMAXSIZE: a longer link is not processed

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

# Bounded runs keep every scan linear on hostile input.
_CSS_URL = re.compile(r"""(?<![\w-])url\(\s*(?:"([^"\n]{0,1024})"|'([^'\n]{0,1024})'"""
                      r"""|([^"'()\s]{1,1024}))\s*\)"""
                      r"""|@import\s+(?:"([^"\n]{0,1024})"|'([^'\n]{0,1024})')""", re.IGNORECASE)
_REFRESH_URL = re.compile(r"url=", re.IGNORECASE)
_NAME_ATTR = re.compile(r"\sname\s*=", re.IGNORECASE)
# HTML5 tokenizer pieces; each match consumes what it scans, so a page is read in linear time
_TAG_NAME = re.compile(r"[a-zA-Z][^\t\n\r\f />]*")
_SKIP = re.compile(r"[\t\n\r\f /]*")
_ATTR = re.compile(r"""([^\t\n\r\f />][^\t\n\r\f /=>]*)"""
                   r"""(?:[\t\n\r\f ]*=[\t\n\r\f ]*("[^"]*"|'[^']*'|[^\t\n\r\f >]*))?""")
_RAW_END = {t: re.compile(rf"</{t}[\t\n\r\f />]", re.IGNORECASE) for t in ("script", "style")}
_CHARREF = re.compile(r"&(#[0-9]{1,8};?|#[xX][0-9a-fA-F]{1,8};?|[A-Za-z][A-Za-z0-9]{0,31};?)")


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


def _css(text: str) -> list[str]:
    return [next(g for g in m.groups() if g is not None) for m in _CSS_URL.finditer(text)]


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


def _unescape_attr(value: str) -> str:
    """HTML5 character references in an attribute value: a named one without ";" stays
    literal unless it is a whole legacy name not followed by "=" (?a=1&copy=2 keeps &copy)."""
    def ref(m):
        token = m.group(1)
        if token[0] == "#" or token.endswith(";"):
            return html.unescape(m.group())
        after = value[m.end():m.end() + 1]
        return html.unescape(m.group()) if token in _ENTITIES and after != "=" else m.group()
    return _CHARREF.sub(ref, value) if "&" in value else value


class _Hit(NamedTuple):
    vspan: tuple[int, int] | None  # the attribute value as written in the page; None for CSS
    value: str             # that value, unescaped
    tag: str
    attrs: dict            # first value of each attribute of the tag
    name: str              # attribute holding the link
    span: tuple[int, int]  # the URL's span in `value`
    raw: str               # the URL as written
    url: str | None        # absolute, no fragment; None when unusable
    follow: bool           # False once a meta robots nofollow was seen


class _Scan:
    def __init__(self, text: str, url: str, robots: bool):
        self.base, self.robots = url, robots
        self.hits: list[_Hit] = []
        self.base_hrefs: list[tuple[int, int]] = []  # value spans of each <base href>
        self.base_target = self.nofollow = False
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
        attrs: list[tuple[str, str | None, tuple[int, int] | None]] = []
        while True:
            k = _SKIP.match(text, k).end()
            if k >= n:
                return n  # a tag that never closes: nothing after it is read
            if text[k] == ">":
                break
            a = _ATTR.match(text, k)
            raw = a.group(2)
            value = None if raw is None else _unescape_attr(
                raw[1:-1] if raw[:1] in "'\"" and len(raw) > 1 and raw[-1] == raw[0] else raw)
            attrs.append((a.group(1).lower(), value, a.span(2) if raw is not None else None))
            k = a.end()
        self._tag(tag, attrs, text[j:k + 1])
        if tag in _RAW_END:
            end = _RAW_END[tag].search(text, k + 1)
            body = text[k + 1:end.start() if end else n]
            if tag == "style":
                for raw in _css(body):
                    self.hits.append(_Hit(None, "", "style", {}, "", (0, 0), raw,
                                          self._resolve(raw), not self.nofollow))
            return end.start() if end else n
        return k + 1

    def _resolve(self, raw: str) -> str | None:
        if not raw or raw.startswith("#") or len(raw) > URL_MAX:
            return None
        try:
            return _usable(urljoin(self.base, raw))
        except ValueError:
            return None

    def _tag(self, tag: str, attrs: list, raw_tag: str) -> None:
        amap: dict = {}
        for name, value, _ in attrs:
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
        for name, value, vspan in attrs:
            if value is None:
                continue
            if tag == "base" and name == "target":
                self.base_target = True
            if tag == "base" and name == "href":
                self.base_hrefs.append(vspan)
                start, stop = _strip(value)
                try:
                    self.base = urljoin(self.base, value[start:stop])
                except ValueError:
                    pass  # an unusable base leaves the current one, as a browser does
                continue
            if name == "style":
                for raw in _css(value):
                    self.hits.append(_Hit(None, value, tag, amap, name, (0, 0), raw,
                                          self._resolve(raw), not self.nofollow))
                continue
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
                self.hits.append(_Hit(vspan, value, tag, amap, name, (a, b), raw,
                                      self._resolve(raw), not self.nofollow))


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
    if hit.vspan is None:
        return _css_meta(hit.url or "")
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


def page_links(body: bytes, url: str, *, frame: str = "document",
               robots: bool = True) -> list[Link]:
    """Links of the HTML page `body` fetched from `url` as Sec-Fetch-Dest `frame`, in
    document order. `robots` (robots.txt obeyed) makes meta robots nofollow count."""
    scan = _Scan(_decode(body), url, robots)
    page_frame = frame if frame in _FRAMES else ""
    link_frame = "" if scan.base_target else page_frame
    return [Link(h.url, _classify(h, page_frame, link_frame))
            for h in scan.hits if h.url and h.follow]


def css_links(body: bytes, url: str) -> list[Link]:
    """url() and @import links of the stylesheet `body` fetched from `url`."""
    out = []
    for raw in _css(_decode(body)):
        if len(raw) <= URL_MAX:
            try:
                u = _usable(urljoin(url, raw))
            except ValueError:
                u = None
            if u:
                out.append(Link(u, _css_meta(u)))
    return out


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
    scan = _Scan(text, url, robots=False)
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
