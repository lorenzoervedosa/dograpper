"""User request headers (`download --header`): the check that guards the wire, and the
in-place merge both downloader profiles use (#136)."""

import re

_TOKEN = re.compile(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+")  # RFC 9110 5.6.2 field-name token
# The client frames and routes the request with these; a user value would break that.
REFUSED = frozenset({"host", "content-length", "transfer-encoding", "connection"})


def parse_header(text: str, position: int) -> tuple[str, str]:
    """'Name: value' -> (name, value), the value's outer spaces stripped. ValueError names
    the header (its position while the name is unusable) and never quotes the value, which
    can carry a credential."""
    name, sep, value = text.partition(":")
    if not sep or not _TOKEN.fullmatch(name):
        raise ValueError(f"#{position} must be 'Name: value' with a header name made of "
                         "letters, digits and !#$%&'*+-.^_`|~")
    if name.lower() in REFUSED:
        raise ValueError(f"{name} is set by the downloader itself and cannot be given")
    check_value(name, value)
    return name, value.strip(" \t")


def check_value(name: str, value: str) -> None:
    """ValueError naming `name` when `value` holds a CR, LF or NUL, which would end the
    header line and start one of the value's own on the wire."""
    if any(c in value for c in "\r\n\0"):
        raise ValueError(f"{name} has a CR, LF or NUL character in its value")


def merge_headers(base, extra) -> list:
    """`base` (name, value) pairs with each of `extra` taking the place of the same-named
    one (case-insensitive; the extra's spelling kept), or appended; a later one wins."""
    out = list(base)
    at = {name.lower(): i for i, (name, _) in enumerate(out)}
    for name, value in extra:
        i = at.get(name.lower())
        if i is None:
            at[name.lower()] = len(out)
            out.append((name, value))
        else:
            out[i] = (name, value)
    return out
