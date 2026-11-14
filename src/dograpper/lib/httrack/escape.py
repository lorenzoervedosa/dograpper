"""HTTrack's request-target escaping: the single source for the wire (fetcher) and for the
robots.txt rules matched against it (robots), so both sides always escape alike."""

import re

# htslib.c escape_check_url: space, '"', controls, DEL and non-ASCII; '%' and reserved stay
_UNSAFE = re.compile(r'[^\x21\x23-\x7e]')


def escape_unsafe(text: str) -> str:
    """Non-ASCII as UTF-8 bytes, lowercase hex; existing %xx escapes and reserved characters
    (including '*' and '$') untouched. UnicodeEncodeError (a ValueError) on lone surrogates."""
    return _UNSAFE.sub(lambda m: "".join("%%%02x" % b for b in m.group().encode()), text)


def request_target(parts) -> str:
    """Request target (path and query of a urlsplit result) escaped as HTTrack sends it."""
    return escape_unsafe((parts.path or "/") + (f"?{parts.query}" if parts.query else ""))
