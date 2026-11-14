"""Log-safe URL rendering."""

import re
from urllib.parse import urlsplit, urlunsplit

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")


def _strip_userinfo(url: str) -> str:
    try:
        p = urlsplit(url)
        if "@" not in p.netloc:
            return url
        # Rebuild from parsed parts: urlsplit strips \t\r\n, so a text replace of the netloc
        # would miss userinfo containing them.
        return urlunsplit(p._replace(netloc=p.netloc.rpartition("@")[2]))
    except ValueError:
        return "<redacted url>"


def redact_url(url: str) -> str:
    """Drop userinfo (user and password) and percent-encode control characters, so a
    server-supplied URL cannot inject terminal escapes; fail closed on anything unparseable."""
    return _CONTROL.sub(lambda m: "%%%02X" % ord(m.group()), _strip_userinfo(url))
