"""Log-safe rendering of URLs and server-supplied text, and the one userinfo strip."""

import re
from typing import Optional
from urllib.parse import SplitResult, unquote, urlsplit, urlunsplit

_CONTROL = re.compile(r"[\x00-\x1f\x7f-\x9f]")
# Logs: a query parameter name containing one of these, once casefolded and stripped
# of "-" and "_", may carry a credential (client_secret, sessionToken, apiKey...).
_SECRET_WORDS = ("token", "secret", "key", "sig", "auth", "pass", "session", "credential",
                 "pwd", "jwt", "sid", "ticket", "hmac", "nonce", "otp")
_SECRET_NAMES = frozenset({"code"})
_SECRET_PREFIXES = ("xamz", "xgoog")
_QUERY_PARAM = re.compile(r"([^&;=#]*)=([^&;#]*)")
# Recorded URLs fail closed: unknown parameters cost only the URL.
NAVIGATION_PARAMS = frozenset({
    "title", "oldid", "curid", "diff", "pagefrom", "pageuntil", "from", "until", "page", "p",
    "id", "lang", "uselang", "hl", "locale", "v", "version", "section", "tab", "topic", "view",
    "ns", "namespace", "category", "cat", "tag", "q", "query", "search",
})


def neutralize_controls(text: str, fmt: str = "\\x%02x") -> str:
    """Replace each C0, DEL or C1 control character with ``fmt % codepoint``, so text a
    server supplied cannot drive the terminal or log viewer it is printed to."""
    return _CONTROL.sub(lambda m: fmt % ord(m.group()), text)


def _is_secret_param(name: str) -> bool:
    """Credential-like query parameter name, for logs. It errs on the side of
    caution: ``design``, ``author`` or ``keyword`` match too."""
    norm = unquote(name).casefold().replace("-", "").replace("_", "")
    return (norm in _SECRET_NAMES or norm.startswith(_SECRET_PREFIXES)
            or any(w in norm for w in _SECRET_WORDS))


def _query(url: str):
    base, sep, rest = url.partition("?")
    query, hash_, fragment = rest.partition("#")
    return base, sep, query, hash_ + fragment


def recordable_url(url: str) -> Optional[str]:
    """``url`` as a manifest records it: without userinfo, and only when every query
    parameter is in NAVIGATION_PARAMS; None otherwise, since a masked URL is wrong."""
    names = (seg.partition("=")[0] for seg in re.split("[&;]", _query(url)[2]) if seg)
    if any(unquote(n).casefold() not in NAVIGATION_PARAMS for n in names):
        return None
    return redact_url(url)


def mask_secret_params(url: str) -> str:
    """``url`` with the value of each credential-like query parameter replaced by
    ``REDACTED``; every other character is kept as is."""
    base, sep, query, tail = _query(url)
    if not sep:
        return url
    masked = _QUERY_PARAM.sub(
        lambda m: f"{m.group(1)}=REDACTED" if _is_secret_param(m.group(1)) else m.group(0), query)
    return f"{base}?{masked}{tail}"


def drop_userinfo(parts: SplitResult) -> SplitResult:
    """``parts`` (a urlsplit result) without user:password: the single place that strips
    it, for logs here and for the request headers of the httrack profile."""
    return parts._replace(netloc=parts.netloc.rpartition("@")[2])


def _strip_userinfo(url: str) -> str:
    try:
        p = urlsplit(url)
        if "@" not in p.netloc:
            return url
        # Rebuild from parsed parts: urlsplit strips \t\r\n, so a text replace of the netloc
        # would miss userinfo containing them.
        return urlunsplit(drop_userinfo(p))
    except ValueError:
        return "<redacted url>"


def redact_url(url: str) -> str:
    """Drop userinfo (user and password), mask credential query values and percent-encode
    control characters, so a server-supplied URL cannot inject terminal escapes; fail
    closed on anything unparseable."""
    return neutralize_controls(mask_secret_params(_strip_userinfo(url)), "%%%02X")
