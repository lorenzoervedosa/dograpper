"""Log-safe URL rendering."""

from urllib.parse import urlsplit, urlunsplit


def redact_url(url: str) -> str:
    """Drop userinfo (user and password) from the URL; fail closed on anything unparseable."""
    try:
        p = urlsplit(url)
        if "@" not in p.netloc:
            return url
        # Rebuild from parsed parts: urlsplit strips \t\r\n, so a text replace of the netloc
        # would miss userinfo containing them.
        return urlunsplit(p._replace(netloc=p.netloc.rpartition("@")[2]))
    except ValueError:
        return "<redacted url>"
