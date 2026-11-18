"""HTTrack's script parser (htsparse.c): the quote/comment automaton, the keyword scan of
-j (hts_js_scan_link) and the quoted-string guess of -%P (hts_dirty_link_is_url), with the
rules that cut and clean a link once found.

links.py hands it each context its tokenizer reads (a <script>/<style> body, an
onXxx=/style= value, a javascript: URL, a fetched stylesheet or script) and runs the tag
part of -%P through dirty(). Every scan jumps with regexes and bounds its look-ahead, so a
page is read in linear time.
"""

import html
import re
from html.entities import html5 as _ENTITIES
from typing import NamedTuple

from .naming import KNOWN_EXTS

URL_MAX = 1024  # htsglobal.h HTS_URLMAXSIZE: a longer link is not processed
_CHARREF = re.compile(r"&(#[0-9]{1,8};?|#[xX][0-9a-fA-F]{1,8};?|[A-Za-z][A-Za-z0-9]{0,31};?)")


def unescape_attr(value: str) -> str:
    """HTML5 character references in an attribute value: a named one without ";" stays
    literal unless it is a whole legacy name not followed by "=" (?a=1&copy=2 keeps &copy).
    HTTrack decodes them in every link it takes (hts_unescapeEntities), so links.py's
    attribute values and this module's links share it."""
    def ref(m):
        token = m.group(1)
        if token[0] == "#" or token.endswith(";"):
            return html.unescape(m.group())
        after = value[m.end():m.end() + 1]
        return html.unescape(m.group()) if token in _ENTITIES and after != "=" else m.group()
    return _CHARREF.sub(ref, value) if "&" in value else value


REAL = frozenset(" \n\r\t\f\v")         # is_realspace, HTS_REALSPACES (htssafe.h:682)
QUOTES = frozenset("\"'")
_SPACE = REAL | QUOTES                   # is_space (htslib.h:807)
_CSPACE = frozenset(" \t\n\v\f\r")        # C isspace
NEUTRAL = "x"                            # a parseall_lastc that opens no -%P string
_C0 = "".join(map(chr, range(33)))
_AFTER = frozenset("=(,\0")               # strchr("=(,", lastc); "\0": nothing seen yet
_DIRTY_NEXT = frozenset("),;>/+\r\n\0")   # strchr("),;>/+\r\n", c), "\0": end of page
# htsparse.c:161-167 hts_nodetect: attributes whose value is never a link
_NODETECT = frozenset("""accept-charset accesskey action align alt axes axis char charset cite
class classid code color datetime dir enctype face height id lang language media method name
prompt scheme size style target title type valign version width""".split())
_BINDINGS = (":", "@", "[", "(", "v-", "x-bind:", "x-on:")  # hts_attr_is_js_binding
_MAIN_MIME = ("application", "audio", "image", "message", "multipart", "text", "video")
_METHODS = frozenset("GET POST PUT DELETE HEAD OPTIONS PATCH TRACE".split())  # is_http_method
# js_glues_keyword: the Unicode spaces that end a name (U+00A0, U+1680, U+2000-200A...)
_USPACES = frozenset("\u00a0\u1680\u2028\u2029\u202f\u205f\u3000\ufeff"
                     + "".join(map(chr, range(0x2000, 0x200b))))
_ENTITY_QUOTES = (("&quot;", '"'), ("&QUOT;", '"'), ("&#34;", '"'), ("&#x22;", '"'),
                  ("&#X22;", '"'), ("&apos;", "'"), ("&#39;", "'"), ("&#x27;", "'"),
                  ("&#X27;", "'"))  # html_entity_quote, case matters
_ENTITY_END = {q: re.compile("[\"'>]|" + "|".join(re.escape(e) for e, eq in _ENTITY_QUOTES
                                                  if eq == q)) for q in QUOTES}
# every position where one of hts_js_scan_link's keywords starts (overlaps included)
_KEYWORD = re.compile(r"(?=\.src|src|\.location|:location|location|\.href|\.open|\.replace"
                      r"|\.link|\.url|url|import|from)", re.IGNORECASE | re.ASCII)
_ANY_QUOTE = re.compile("[\"']")
_CUT = re.compile("[ \n\r\t\f\v\"'>#\\\\&)]")         # the bytes that may end a link

# The script automaton (htsparse.c:97-108, 1229-1254): the state after each byte.
_START, _ESC, _Q1, _Q2, _SLASH, _LINE, _COMMENT, _COMMENT2, _ESC_Q1, _ESC_Q2 = range(10)
_RUN = {_START: re.compile(r"[\\'\"/]"), _Q1: re.compile(r"['\\]"), _Q2: re.compile(r"[\"\\]"),
        _LINE: re.compile("\n"), _COMMENT: re.compile(r"\*")}  # the byte that leaves the state
_IN_QUOTES = re.compile(r"['\"\\]")  # in a string: its end, an escape, or the other quote


def _step(st: int, ch: str, css_file: bool) -> int:
    if st == _START:
        return {"\\": _ESC, "'": _Q1, '"': _Q2, "/": _SLASH}.get(ch, _START)
    if st in (_Q1, _Q2):
        if ch == ("'" if st == _Q1 else '"'):
            return _START
        return (_ESC_Q1 if st == _Q1 else _ESC_Q2) if ch == "\\" else st
    if st == _SLASH:
        if ch == "/":
            return _SLASH if css_file else _LINE  # a stylesheet has no // comment (#139)
        return _COMMENT if ch == "*" else _START
    if st == _LINE:
        return _START if ch == "\n" else _LINE
    if st == _COMMENT:
        return _COMMENT2 if ch == "*" else _COMMENT
    if st == _COMMENT2:
        return _START if ch == "/" else _COMMENT2 if ch == "*" else _COMMENT
    return _Q1 if st == _ESC_Q1 else _Q2 if st == _ESC_Q2 else _START


def _feed(t: str, st: int, i: int, end: int, css_file: bool) -> int:
    """The automaton's state after t[i:end] (hts_automate_increment)."""
    while i < end:
        run = _RUN.get(st)
        if run is not None:
            m = run.search(t, i, end)
            if m is None:
                return st
            i = m.start()
        st = _step(st, t[i], css_file)
        i += 1
    return st


def at(t: str, i: int) -> str:
    return t[i] if 0 <= i < len(t) else "\0"


def field(t: str, i: int, word: str) -> int:
    """strfield: len(word) when t continues at i with word, ASCII case ignored, else 0."""
    got = t[i:i + len(word)]
    return len(word) if got.isascii() and got.lower() == word else 0


def _skip_real(t: str, i: int) -> int:
    while at(t, i) in REAL:
        i += 1
    return i


def _js_glues(t: str, i: int) -> bool:
    """js_glues_keyword: the byte before i continues a name, so no keyword starts at i."""
    c = t[i - 1] if i > 0 else " "
    if c < "\x80":
        return c.isalnum() or c in "_$."
    if c == "\udca0" and (i < 2 or t[i - 2] < "\x80"):  # a lone 0xA0, the page not UTF-8
        return False
    return c not in _USPACES


def _css_glues(t: str, i: int) -> bool:
    """css_glues_keyword: CSS also continues an ident across "-", U+1680 and U+FEFF."""
    return (t[i - 1] if i > 0 else " ") in "-\u1680\ufeff" or _js_glues(t, i)


def _entity_quote(t: str, i: int) -> tuple[str, int]:
    for name, quote in _ENTITY_QUOTES:
        if t.startswith(name, i):
            return quote, len(name)
    return "", 0


class Ctx(NamedTuple):
    """Where a script is: CSS lets url() go unquoted; a whole stylesheet has no // comment;
    in_tag is an onXxx=/style= value or a javascript: URL, which ends on tag_lastc (the
    byte after its "="); tag_start is its tag's "<" (-1 outside a tag)."""
    css: bool = False
    css_file: bool = False
    in_tag: bool = False
    tag_lastc: str = ""
    tag_start: int = -1


def _js_link(t: str, p: int, ctx: Ctx) -> tuple[int, int, str, str, bool] | None:
    """hts_js_scan_link (htsparse.c:557-788) at t[p]: (start and end of the URL, byte ending
    an unquoted one, quote its entity stands for, module specifier) or None."""
    expected, ends = "=", ";\"'" if ctx.in_tag else ";"
    avoid_quotes, unquoted_end = False, ""
    not_mime = not_method = is_import = is_specifier = False
    prev = t[p - 1] if p > 0 else " "
    nc = field(t, p, ".src")
    if not nc and ctx.in_tag and ctx.tag_lastc == prev:
        nc = field(t, p, "src")
    nc = nc or field(t, p, ".location") or field(t, p, ":location")
    if not nc and prev in _CSPACE:
        nc = field(t, p, "location")
    nc = nc or field(t, p, ".href")
    if not nc and (nc := field(t, p, ".open")):
        expected, ends, not_mime, not_method = "(", "),", True, True
    if not nc and (nc := field(t, p, ".replace") or field(t, p, ".link")
                   or field(t, p, ".url")):
        expected, ends = "(", ")"
    if not nc and not (_css_glues(t, p) if ctx.css else _js_glues(t, p)) \
            and (nc := field(t, p, "url")):
        expected, ends, avoid_quotes, unquoted_end = "(", ")", ctx.css, ")"
    if not nc and (nc := field(t, p, "import")):
        if at(t, p + nc) in _SPACE:
            expected, is_import = "", True
        else:
            nc = 0
    if not nc and not _js_glues(t, p) and prev not in "\"'`" and (nc := field(t, p, "from")):
        expected, is_specifier = "", True
    if not nc:
        return None
    a = _skip_real(t, p + nc)
    if expected:
        if at(t, a) != expected:
            return None
        a = _skip_real(t, a + 1)
    if at(t, a) not in QUOTES and not avoid_quotes:
        return None
    entity, ndelim = _entity_quote(t, a) if ctx.in_tag and avoid_quotes else ("", 0)
    close = 1
    if entity:  # a style attribute may quote url() with an entity: url(&quot;a.png&quot;)
        a += ndelim
        m = _ENTITY_END[entity].search(t, a)
        b = m.start() if m else len(t)
        if b < len(t) and t[b] in "\"'>":
            return None  # a raw quote or ">" ends the attribute before the closing entity
        close = len(m.group()) if m else 0
    elif at(t, a) in QUOTES:
        a, ndelim = a + 1, 1
        m = _ANY_QUOTE.search(t, a)
        b = m.start() if m else len(t)
    else:  # an unquoted url( not closed within 2 KiB is no link
        b = t.find(unquoted_end, a, a + 2 * URL_MAX + 1)
        b, close = (b if b >= 0 else len(t)), 0
    if b >= len(t):
        return None  # no closing delimiter
    c = b + close
    while at(t, c) == " ":
        c += 1
    if not (at(t, c) in ends or at(t, c) in "\0\n\r"
            or (is_import and at(t, b + close) == " ")):
        return None
    url = t[a:b]
    if not url:
        return None
    if not_mime and any(field(t, a, m) and at(t, a + len(m)) == "/" for m in _MAIN_MIME):
        return None
    if not_method and url.isascii() and url.upper() in _METHODS:
        return None  # xhr.open("GET", url)
    if is_specifier and not (url[:1] == "/" or url.startswith(("./", "../"))
                             or field(t, a, "http:") or field(t, a, "https:")
                             or field(t, a, "ftp:")):
        return None  # a module id the loader resolves ("jquery"), not a path
    if "${" in url or any(ch in url for ch in "\"'\t\r\n") or url.lstrip(" ")[:1] in (",", ";"):
        return None  # a template, or code (htsparse.c:747-777)
    return a, b, (unquoted_end if avoid_quotes and not ndelim else ""), entity, \
        (is_import or is_specifier) and not ctx.css


def _take(t: str, i: int, inscript: bool, ending: str = "",
          entity: str = "") -> tuple[str | None, int]:
    """htsparse.c:2318-2565: the link starting at t[i], past the blanks and the quote before
    it, cut where HTTrack cuts it; (link or None, index of the byte that ended it). The
    caller resumes after that byte, whether a link came out or not."""
    n, quote = len(t), ""
    while i < n and t[i] in _SPACE and not quote:
        quote = t[i] if t[i] in QUOTES else ""
        i += 1
    if inscript and at(t, i) == "\\" and at(t, i + 1) in QUOTES:
        i += 2
    if not inscript and field(t, i, "javascript:"):
        return None, i  # HTTrack parses it as a script instead
    j = i
    while True:
        m = _CUT.search(t, j, min(n, i + URL_MAX + 1))
        if m is None:
            if n - i > URL_MAX:
                return None, i + URL_MAX + 1  # too long (HTS_URLMAXSIZE)
            j = n  # the end of the page ends it
            break
        j, ch = m.start(), m.group()
        if ch in _SPACE:
            if ch == quote or (inscript and ch in QUOTES) or (
                    not inscript and not quote and ch in REAL):
                break
        elif ch == ")":
            if ending == ")":
                break
        elif ch == "&":
            if entity and _entity_quote(t, j)[0] == entity:
                break
        elif ch == ">":
            if not quote:
                break
        elif ch == "#":
            if t[j - 1] != "&":  # &#40; is no fragment
                break
        elif inscript:  # a backslash
            break
        j += 1
    link = t[i:j]
    if not link or field(t, i, "(empty reference!)"):
        return None, j
    # both ends lose every control byte and space, as a browser trims them; CR, LF, TAB go
    link = link.strip(_C0).translate({9: None, 10: None, 13: None})
    return link or None, j


def _fragment_or_query(s: str) -> bool:
    """htstools.c link_dir_has_fragment_or_query."""
    cut = next((k for k, ch in enumerate(s) if ch in "#?&"), len(s))
    if cut == 0 or cut == len(s) or s[cut] == "&" or s[cut - 1] != "/":
        return False
    return cut == 1 or len(s) - len(s.lstrip("/")) < cut


def _dirty_is_url(s: str, after: str, inscript: bool) -> bool:
    """htsparse.c:376-448 hts_dirty_link_is_url: does the string s, followed by `after`,
    name a file?"""
    if len(s) >= URL_MAX or (" " in s and not inscript):
        return False  # a space reads as prose outside script code
    opens_path = _fragment_or_query(s)
    s = unescape_attr(s).split("#", 1)[0].split("?", 1)[0]
    if not s or any(ch in s for ch in "*<>,\"'") or (s[0] == "." and s[1:2].isascii()
                                                      and s[1:2].isalnum()):
        return False  # code punctuation, or a bare extension (".gif")
    if after != "+":  # a string the code continues with "+": only an extension speaks
        if field(s, 0, "http:") or field(s, 0, "ftp:") or field(s, 0, "https:"):
            return True
        if s.endswith("/") and inscript and (opens_path or (
                s.count("/") >= 2 and len(s) > s.count("/"))):
            return True  # #1612, #1618
    k = max(s.rfind("."), s.rfind("/"), 0)  # get_httptype_sized / is_dyntype
    ext = s[k:].lower() if s[k] == "." and len(s) - k < 32 else ""
    return ext not in ("", ".") and ext in KNOWN_EXTS and "@" not in s


def _attr_name(t: str, q: int, tag_start: int) -> tuple[int, int] | None:
    """htsparse.c hts_dirty_attr_name: the span of the attribute name before the "=" before
    the quote t[q], or None."""
    a = q - 1
    while a > tag_start and t[a] in " \t":
        a -= 1
    if a == tag_start or t[a] != "=":
        return None
    a -= 1
    while a > tag_start and t[a] in " \t":
        a -= 1
    nend = a + 1
    while a > tag_start and t[a] not in "=\"'" and t[a] not in REAL:
        a -= 1
    a += 1
    return (a, nend) if tag_start + 1 < a < nend else None


def _refused(name: str) -> bool:
    """hts_dirty_attr_refused: an attribute that never holds a link, or xmlns."""
    low = name.lower() if name.isascii() else ""
    return low in _NODETECT or low == "xmlns" or low.startswith("xmlns:")


def _binding(name: str) -> bool:
    """hts_attr_is_js_binding: Vue :x, v-x, @x, Angular [x], (x), Alpine x-bind:x."""
    return any(len(name) > len(b) and field(name, 0, b) for b in _BINDINGS)


def _import_arg(t: str, q: int) -> bool:
    """hts_js_quote_is_import_arg: the quote t[q] opens the argument of import()."""
    i = q
    while i and t[i - 1] in REAL:
        i -= 1
    if not i or t[i - 1] != "(":
        return False
    i -= 1
    while i and t[i - 1] in REAL:
        i -= 1
    return i >= 6 and t[i - 6:i] == "import" and not _js_glues(t, i - 6)


def dirty(t: str, q: int, lastc: str, inscript: bool, tag_start: int = -1,
           startattr: str | None = None) -> tuple[str | None, int] | None:
    """htsparse.c:2160-2276, -%P at the quote t[q]: None when the string it opens is not
    taken, else what _take() makes of it. In a tag, `startattr` names the attribute
    holding a quote that has no name of its own."""
    if lastc not in _AFTER or q == 0:
        return None
    a = q + 1
    m = _ANY_QUOTE.search(t, a, a + URL_MAX)
    if m is None or m.group() != t[q] or m.start() == a:
        return None
    c = m.start() + 1
    while at(t, c) in " \t":
        c += 1
    named = _attr_name(t, q, tag_start) if tag_start >= 0 else None
    name = t[named[0]:named[1]] if named else None
    if at(t, c) not in _DIRTY_NEXT and not (
            not inscript and tag_start >= 0 and name is not None and not _refused(name)):
        return None
    if not _dirty_is_url(t[a:m.start()], at(t, c), inscript):
        return None
    if tag_start >= 0:
        if not inscript and ((name is not None and _refused(name))
                             or (startattr is not None and _refused(startattr))):
            return None
        if name is not None and _binding(name):
            return None
    return _take(t, q, inscript)


def scan_script(t: str, i: int, end: int, ctx: Ctx, lastc: str, parse_scripts: bool,
                 extended: bool) -> list[tuple[int, str, bool]]:
    """The links HTTrack's parser takes in the script t[i:end] (htsparse.c:1745-2276): -j
    tries hts_js_scan_link at each byte the automaton leaves outside strings and comments,
    -%P each quote opening a string after "=", "(" or "," (`lastc`, parseall_lastc, is the
    last such byte). Returns (position, link, module specifier) per link."""
    out: list[tuple[int, str, bool]] = []
    st, leave = _START, -1  # the next byte that leaves START; still it while i <= leave

    def take(p: int, got) -> int:
        """Record the link `got` found at byte p; return where the scan resumes."""
        link, term = got[0], got[1]
        if link:
            out.append((p, link, got[2]))
        return term + 1

    while i < end:
        if st == _START:
            if leave < i:  # an unquoted url() ends before it: search each byte once
                m = _RUN[_START].search(t, i, end)
                leave = m.start() if m else end
            k, found = leave, None
            if parse_scripts:
                for km in _KEYWORD.finditer(t, i, k):
                    if (js := _js_link(t, km.start(), ctx)) is not None:
                        found = km.start(), js
                        break
            if found:
                p, (a, _, ending, entity, module) = found
                lastc = t[p]
                link, term = _take(t, a, True, ending, entity)
                st = _feed(t, _START, p + 1, term + 1, ctx.css_file)
                i = take(a, (link, term, module))
                continue
            tail = t[i:k].rstrip(" \n\r\t\f\v")
            lastc = tail[-1] if tail else lastc
            if k >= end:
                break
            st, i = _step(_START, t[k], ctx.css_file), k + 1
            if st in (_Q1, _Q2) and extended and (got := dirty(t, k, lastc, True,
                                                               ctx.tag_start)) is not None:
                st = _feed(t, st, k + 1, got[1] + 1, ctx.css_file)
                i = take(k + 1, (got[0], got[1], _import_arg(t, k)))
        elif st in (_Q1, _Q2):
            m = _IN_QUOTES.search(t, i, end)
            if m is None:
                break
            k = m.start()
            nxt, i = _step(st, t[k], ctx.css_file), k + 1
            if nxt == st and extended and (got := dirty(t, k, lastc, True,
                                                         ctx.tag_start)) is not None:
                nxt = _feed(t, st, k + 1, got[1] + 1, ctx.css_file)
                i = take(k + 1, (got[0], got[1], _import_arg(t, k)))
            st = nxt
        elif st in (_LINE, _COMMENT):
            m = _RUN[st].search(t, i, end)
            if m is None:
                break
            st, i = _step(st, t[m.start()], ctx.css_file), m.start() + 1
        else:  # one byte decides: after a backslash, a slash or a comment's star
            nxt = _step(st, t[i], ctx.css_file)
            got = js = None
            if nxt == _START and parse_scripts and _KEYWORD.match(t, i):
                js = _js_link(t, i, ctx)
            elif nxt in (_Q1, _Q2) and t[i] in QUOTES and extended:
                got = dirty(t, i, lastc, True, ctx.tag_start)
            if js is not None:
                a, _, ending, entity, module = js
                link, term = _take(t, a, True, ending, entity)
                st = _feed(t, _START, i + 1, term + 1, ctx.css_file)
                i = take(a, (link, term, module))
            elif got is not None:
                st = _feed(t, nxt, i + 1, got[1] + 1, ctx.css_file)
                i = take(i + 1, (got[0], got[1], _import_arg(t, i)))
            else:
                st, i = nxt, i + 1
    return out
