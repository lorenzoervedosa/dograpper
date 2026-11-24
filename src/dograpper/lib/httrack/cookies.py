"""The --cookies jar of the httrack profile (HTTrack -%K, spec 5.7, #169).

A Netscape cookies.txt is loaded before the run and written back to the same file at its
end (HTTrack rewrites its -%K jar the same way), `#HttpOnly_` lines and session cookies
kept. In between, the Fetcher sends the matching cookies (`header`) and takes in every
response's Set-Cookie (`take`); the browser pass pushes the jar into Chromium's context
(`to_browser`) and merges what the context holds back at its end (`merge`).

Matching and Set-Cookie parsing are the stdlib's (http.cookiejar), with a host-only cookie
kept to its host (RFC 6265 5.3 step 6). The file is read and written here rather than by
MozillaCookieJar, which drops an expiry-0 session cookie, forgets the HttpOnly of a
Set-Cookie and quotes a bad line, cookie value included, in its error.

The file is read as latin-1, the byte model of HTTP headers: every byte round-trips to the
wire and back to the file, and no byte can fail to decode (contract 7).
"""

import http.cookiejar
import urllib.request

from ...utils.atomic_write import atomic_write_bytes

HTTPONLY_PREFIX = "#HttpOnly_"
_FIRST_LINE = "# Netscape HTTP Cookie File\n"  # what curl and MozillaCookieJar look for
_BOM = "\xef\xbb\xbf"  # UTF-8's, as latin-1 reads it
# shortcut: no cap on the jar's size (HTTrack's COOKIE_MAX_JAR); add one if a site floods it


class _Response:
    """What CookieJar.extract_cookies reads of a response: its headers (get_all)."""

    def __init__(self, headers):
        self._headers = headers

    def info(self):
        return self._headers


def _httponly(cookie: http.cookiejar.Cookie) -> bool:
    # a Set-Cookie spells the flag as it likes; Cookie has no public list of its extras
    return any(name.lower() == "httponly" for name in cookie._rest)


def _cookie(domain, path, secure, expires, name, value, httponly) -> http.cookiejar.Cookie:
    """A Netscape cookie: `domain` with a leading dot is a domain cookie, else host-only;
    `expires` None is a session cookie."""
    dotted = domain.startswith(".")
    return http.cookiejar.Cookie(0, name, value, None, False, domain, dotted, dotted, path,
                                 True, secure, expires, expires is None, None, None,
                                 {"HttpOnly": ""} if httponly else {})


class Jar:
    def __init__(self, path: str | None):
        self.path = path  # None: a jar for the run alone (--browser-login without --cookies)
        self._jar = http.cookiejar.CookieJar(http.cookiejar.DefaultCookiePolicy(
            strict_ns_domain=http.cookiejar.DefaultCookiePolicy.DomainStrictNonDomain))

    def header(self, url: str) -> str | None:
        """The Cookie header value for a request to `url`, or None when nothing matches."""
        request = urllib.request.Request(url)
        self._jar.add_cookie_header(request)
        return request.get_header("Cookie")

    def take(self, url: str, headers) -> None:
        """Store the Set-Cookie lines of the response to `url` (`headers`, an
        email.message.Message such as http.client's)."""
        self._jar.extract_cookies(_Response(headers), urllib.request.Request(url))

    def add(self, cookie: http.cookiejar.Cookie) -> None:
        self._jar.set_cookie(cookie)

    def to_browser(self) -> list[dict]:
        """The jar as Playwright's context.add_cookies() takes it."""
        out = []
        for c in self._jar:
            name, value = ("", c.name) if c.value is None else (c.name, c.value)
            entry = {"name": name, "value": value, "domain": c.domain, "path": c.path,
                     "httpOnly": _httponly(c), "secure": bool(c.secure)}
            if c.expires is not None:
                entry["expires"] = c.expires
            out.append(entry)
        return out

    def merge(self, cookies: list[dict]) -> None:
        """Take in what a browser context holds (Playwright's context.cookies()): each one
        replaces the jar's of the same domain, path and name."""
        for c in cookies:
            expires = c.get("expires", -1)
            self.add(_cookie(c["domain"], c["path"], bool(c.get("secure")),
                             None if expires < 0 else int(expires), c["name"], c["value"],
                             bool(c.get("httpOnly"))))

    def save(self) -> None:
        """Write the jar back to its file: created owner-only (0600), an existing file's
        mode kept; expired cookies left out, session ones kept (expiry 0, as curl)."""
        self._jar.clear_expired_cookies()
        lines = [_FIRST_LINE]
        for c in sorted(self._jar, key=lambda c: (c.domain, c.path, c.name)):
            name, value = ("", c.name) if c.value is None else (c.name, c.value)
            lines.append("\t".join((
                (HTTPONLY_PREFIX if _httponly(c) else "") + c.domain,
                "TRUE" if c.domain.startswith(".") else "FALSE", c.path,
                "TRUE" if c.secure else "FALSE", str(c.expires or 0), name, value)) + "\n")
        atomic_write_bytes(self.path, "".join(lines).encode("latin-1", "replace"),
                           private=True)


def load_jar(path: str) -> Jar:
    """The jar of the cookies.txt at `path`, empty when there is no file yet. ValueError
    names the bad line by number, never by its content (it holds a cookie value)."""
    jar = Jar(path)
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
        if len(fields) != 7 or "\r" in line or "\0" in line:
            raise ValueError(f"line {number} is not a cookies.txt record "
                             "(7 tab-separated fields, no CR or NUL)")
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
