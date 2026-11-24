"""The --cookies jar of the httrack profile (HTTrack -%K, spec 5.7, #169).

A Netscape cookies.txt is loaded before the run and written back to the same file at its
end (HTTrack rewrites its -%K jar the same way), `#HttpOnly_` lines and session cookies
kept. In between, the Fetcher sends the matching cookies (`header`) and takes in every
response's Set-Cookie (`take`); the browser pass pushes the jar into Chromium's context
(`to_browser`) and merges what the context holds back at its end (`merge`).

Set-Cookie parsing is the stdlib's (http.cookiejar: attributes, expiry, the Domain a host
may claim). Matching is RFC 6265's, done here: the stdlib reads a host without a dot
(localhost, an intranet `wiki`) as `<host>.local`, so it never sends that host a cookie
from the file or the browser, and it would write the `.local` name back. The file is read
and written here too, not by MozillaCookieJar, which drops an expiry-0 session cookie,
forgets the HttpOnly of a Set-Cookie and quotes a bad line, cookie value included, in its
error.

Every string the jar holds is wire bytes as latin-1, the byte model of HTTP headers: the
file is read that way, http.client decodes Set-Cookie that way, and a browser's cookie is
taken as the UTF-8 bytes Chromium sends. Every byte round-trips to the wire and back to the
file, and no byte can fail to decode (contract 7).
"""

import http.cookiejar
import ipaddress
import logging
import re
import threading
import time
import urllib.request
from urllib.parse import urlsplit

from ...utils.atomic_write import atomic_write_bytes
from ...utils.http_headers import check_value

logger = logging.getLogger(__name__)

# C0 controls (HTAB and an obs-fold's CRLF included) and DEL: no cookie-octet (RFC 6265 4.1.1)
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
HTTPONLY_PREFIX = "#HttpOnly_"
_SECURE_PREFIXES = ("__Secure-", "__Host-")  # RFC 6265bis 4.1.3: set over https only
_FIRST_LINE = "# Netscape HTTP Cookie File\n"  # what curl and MozillaCookieJar look for
_BOM = "\xef\xbb\xbf"  # UTF-8's, as latin-1 reads it
# shortcut: no cap on the jar's size (HTTrack's COOKIE_MAX_JAR); add one if a site floods it


class _Response:
    """What CookieJar.make_cookies reads of a response: its headers (get_all)."""

    def __init__(self, headers):
        self._headers = headers

    def info(self):
        return self._headers


def _httponly(cookie: http.cookiejar.Cookie) -> bool:
    # a Set-Cookie spells the flag as it likes; Cookie has no public list of its extras
    return any(name.lower() == "httponly" for name in cookie._rest)


def _pair(cookie: http.cookiejar.Cookie) -> tuple[str, str]:
    """(name, value) as a cookies.txt line holds it: a cookie with no `=` is a value alone
    (MozillaCookieJar's reading)."""
    return ("", cookie.name) if cookie.value is None else (cookie.name, cookie.value)


def _wire(text: str) -> str:
    """A browser's string as the bytes Chromium puts on the wire (UTF-8), held as latin-1."""
    return text.encode("utf-8").decode("latin-1")


def _cookie(domain, path, secure, expires, name, value, httponly) -> http.cookiejar.Cookie:
    """A Netscape cookie: `domain` with a leading dot is a domain cookie, else host-only;
    `expires` None is a session cookie."""
    dotted = domain.startswith(".")
    return http.cookiejar.Cookie(0, name, value, None, False, domain.lower(), dotted, dotted,
                                 path, True, secure, expires, expires is None, None, None,
                                 {"HttpOnly": ""} if httponly else {})


def _clean(*fields) -> bool:
    """No control character in any of `fields` (None: an absent value)."""
    return not any(f is not None and _CONTROL.search(f) for f in fields)


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def _domain_match(host: str, domain: str) -> bool:
    """RFC 6265 5.1.3: a host-only cookie's domain is the host itself; a domain cookie's
    (leading dot) is the host or one of its parents, never by suffix on an IP host."""
    if not domain.startswith("."):
        return host == domain
    return host == domain[1:] or (not _is_ip(host) and host.endswith(domain))


def _claimable(host: str, domain: str) -> bool:
    """Whether `host` may set a cookie for Domain `domain`: never from an IP host, never an
    IP or a name with no dot (a top-level name; shortcut: no public suffix list, see
    docs/DEBT.md). The stdlib checks the rest (the host is in that domain)."""
    name = domain.lstrip(".")
    return not _is_ip(host) and "." in name and not _is_ip(name)


def _path_match(path: str, cpath: str) -> bool:
    """RFC 6265 5.1.4: `path` is `cpath` or below it."""
    return path == cpath or path.startswith(cpath if cpath.endswith("/") else cpath + "/")


def _matches(cookie: http.cookiejar.Cookie, host: str, path: str, secure: bool,
             now: float) -> bool:
    """RFC 6265 5.4: domain-match, path-match, Secure over https only, not expired."""
    return (_domain_match(host, cookie.domain) and _path_match(path, cookie.path)
            and (secure or not cookie.secure) and not cookie.is_expired(now))


def _overlap(a: str, b: str) -> bool:
    """Whether one of two cookie domains domain-matches the other (RFC 6265bis 5.6 step 16)."""
    a, b = a.lstrip("."), b.lstrip(".")
    return a == b or a.endswith("." + b) or b.endswith("." + a)


class _Store(http.cookiejar.CookieJar):
    """The stdlib's jar, its deletion (an expired Set-Cookie: make_cookies calls clear())
    kept to what the request may erase: over plain http, never a Secure cookie (RFC 6265bis
    5.6, htslib.c:1983-1987). `secure` is the request's scheme, set under the Jar's lock."""
    secure = True

    def clear(self, domain=None, path=None, name=None):
        if not self.secure and name is not None and any(
                c.secure for c in self if (c.domain, c.path, c.name) == (domain, path, name)):
            return
        super().clear(domain, path, name)

    def hides_secure(self, cookie: http.cookiejar.Cookie) -> bool:
        """Whether `cookie`, from plain http, would shadow a Secure one: same name, either
        domain matching the other, its path below the Secure one's."""
        return any(c.secure and c.name == cookie.name and _overlap(c.domain, cookie.domain)
                   and _path_match(cookie.path, c.path) for c in self)


class Jar:
    """`host`: the crawl's start host. The jar's cookies go on requests to it alone, and only
    its Set-Cookie and the browser's cookies for it come in (#169 security review: discovery
    may fetch a sub-sitemap on another host). None: no host bound (a jar outside a run)."""

    def __init__(self, path: str | None, host: str | None = None):
        self.path = path  # None: a jar for the run alone (--browser-login without --cookies)
        self.host = host
        self._jar = _Store()
        self._lock = threading.Lock()  # the Fetcher's workers share the jar; so does its walk

    def header(self, url: str) -> str | None:
        """The Cookie header value for a request to `url`, or None when nothing matches:
        longer paths first, then the older cookie (RFC 6265 5.4)."""
        parts = urlsplit(url)
        host, path, now = parts.hostname or "", parts.path or "/", time.time()
        if not self._binds(host):
            return None
        with self._lock:
            sent = [c for c in self._jar if _matches(c, host, path, parts.scheme == "https",
                                                    now)]
        sent.sort(key=lambda c: -len(c.path))
        line = "; ".join(f"{c.name}={c.value}" if c.value is not None else c.name
                         for c in sent) or None
        if line is not None:  # the --header guard: ValueError names Cookie, never the value
            check_value("Cookie", line)
        return line

    def take(self, url: str, headers) -> None:
        """Store the Set-Cookie lines of the response to `url` (`headers`, an
        email.message.Message such as http.client's), the stdlib's policy checking the
        Domain each claims; one with no Domain is the host's own, dot or no dot."""
        request = urllib.request.Request(url)
        parts = urlsplit(url)
        host, secure = parts.hostname or "", parts.scheme == "https"
        if not self._binds(host):
            return
        with self._lock:
            self._jar.secure = secure
            for cookie in self._jar.make_cookies(_Response(headers), request):
                if not _clean(cookie.name, cookie.value, cookie.path):
                    continue  # a server must not make the next run's jar unreadable
                if not cookie.domain_specified:  # not the stdlib's `<host>.local`
                    cookie.domain = host
                elif not _claimable(host, cookie.domain):
                    continue
                if not secure and (cookie.secure or cookie.name.startswith(_SECURE_PREFIXES)
                                   or self._jar.hides_secure(cookie)):
                    continue  # plain http sets, shadows or replaces no Secure cookie
                self._jar.set_cookie_if_ok(cookie, request)

    def _binds(self, host: str) -> bool:
        return self.host is None or host == self.host

    def _for_host(self, domain: str) -> bool:
        """Whether a cookie of `domain` is one the start host gets."""
        return self.host is None or _domain_match(self.host, domain)

    def add(self, cookie: http.cookiejar.Cookie) -> None:
        with self._lock:
            self._jar.set_cookie(cookie)

    def to_browser(self) -> list[dict]:
        """The jar as Playwright's context.add_cookies() takes it. A cookie whose bytes are
        no UTF-8 text cannot reach the browser: left out, and said (no value shown)."""
        out, skipped = [], 0
        with self._lock:  # no other host's cookie: a subresource request would carry it
            cookies = [c for c in self._jar if self._for_host(c.domain)]
        for c in cookies:
            try:
                name, value, path = (s.encode("latin-1").decode("utf-8")
                                     for s in (*_pair(c), c.path))
            except UnicodeDecodeError:
                skipped += 1
                continue
            entry = {"name": name, "value": value, "domain": c.domain, "path": path,
                     "httpOnly": _httponly(c), "secure": bool(c.secure)}
            if c.expires is not None:
                entry["expires"] = c.expires
            out.append(entry)
        if skipped:
            logger.warning("--cookies: %d cookie(s) of the jar are no UTF-8 text; the "
                           "browser does not get them, the requests of the profile do",
                           skipped)
        return out

    def merge(self, cookies: list[dict]) -> None:
        """Take in what a browser context holds (Playwright's context.cookies()): each one
        replaces the jar's of the same domain, path and name; another host's stays out."""
        for c in cookies:
            if not self._for_host(_wire(c["domain"]).lower()) or not _clean(
                    c["name"], c["value"], c["path"]):
                continue
            expires = c.get("expires", -1)
            self.add(_cookie(_wire(c["domain"]), _wire(c["path"]), bool(c.get("secure")),
                             None if expires < 0 else int(expires), _wire(c["name"]),
                             _wire(c["value"]), bool(c.get("httpOnly"))))

    def save(self) -> None:
        """Write the jar back to its file: created owner-only (0600), an existing file's
        mode kept; expired cookies left out, session ones kept (expiry 0, as curl)."""
        with self._lock:
            self._jar.clear_expired_cookies()
            cookies = sorted(self._jar, key=lambda c: (c.domain, c.path, c.name))
        lines = [_FIRST_LINE]
        for c in cookies:
            lines.append("\t".join((
                (HTTPONLY_PREFIX if _httponly(c) else "") + c.domain,
                "TRUE" if c.domain.startswith(".") else "FALSE", c.path,
                "TRUE" if c.secure else "FALSE", str(c.expires or 0), *_pair(c))) + "\n")
        atomic_write_bytes(self.path, "".join(lines).encode("latin-1"), private=True)


def load_jar(path: str, host: str | None = None) -> Jar:
    """The jar of the cookies.txt at `path` (bound to `host`, see Jar), empty when there is
    no file yet. ValueError names the bad line by number, never by its content (it holds a
    cookie value). Every cookie of the file stays in it, another host's too."""
    jar = Jar(path, host)
    try:
        with open(path, "rb") as f:
            text = f.read().decode("latin-1")
    except FileNotFoundError:
        return jar
    if text.startswith(_BOM):
        text = text[len(_BOM):]
    for number, line in enumerate(text.split("\n"), 1):  # splitlines() also cuts at \x85
        line = line[:-1] if line.endswith("\r") else line
        httponly = line.startswith(HTTPONLY_PREFIX)
        if httponly:
            line = line[len(HTTPONLY_PREFIX):]
        elif not line.strip() or line.startswith("#"):
            continue
        fields = line.split("\t")
        if len(fields) != 7 or not _clean(*fields):
            raise ValueError(f"line {number} is not a cookies.txt record "
                             "(7 tab-separated fields, no control character)")
        domain, flag, cpath, secure, expires, name, value = fields
        try:
            expires = int(expires)
        except ValueError:
            raise ValueError(f"line {number} has an expiry that is not a number") from None
        domain = domain.lstrip(".")
        if flag.upper() == "TRUE":  # a Netscape jar dots exactly its domain cookies
            domain = "." + domain
        if name == "":  # MozillaCookieJar's reading of a line with no name
            name, value = value, None
        jar.add(_cookie(domain, cpath, secure.upper() == "TRUE", expires or None, name,
                        value, httponly))
    return jar
