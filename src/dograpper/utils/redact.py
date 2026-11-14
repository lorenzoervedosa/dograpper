"""Log-safe URL rendering."""

from urllib.parse import urlsplit


def redact_url(url: str) -> str:
    """Drop userinfo (user and password) from the URL; otherwise return it unchanged."""
    try:
        netloc = urlsplit(url).netloc
    except ValueError:
        return "<invalid url>"  # fail safe: unparseable text may still carry credentials
    if "@" not in netloc:
        return url
    return url.replace(netloc, netloc.rpartition("@")[2], 1)
