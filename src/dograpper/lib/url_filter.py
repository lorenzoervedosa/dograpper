"""Filter discovered URLs to the scope of the download command.

Two rules are applied against each URL:
  1. Same-netloc: URL must share `base_url`'s host (no cross-host leakage).
  2. Path-prefix / depth: URL path must live under `base_url`'s canonicalized
     path prefix; if `depth > 0`, the URL must not exceed `depth` additional
     segments beyond the base path.

Path canonicalization appends a trailing slash to BOTH sides
(`rstrip('/') + '/'`) before the startswith check, so that `/docs` does not
accidentally match `/docsextra`.

`--filter` rules (UrlFilters) override rule 2 for the URLs they match, on every
downloader path: HTTrack's scan-rule syntax, the last matching rule wins.
"""

from __future__ import annotations

import logging
import re
import string
from typing import List, Optional, Sequence
from urllib.parse import urlparse, urlsplit, urlunsplit

logger = logging.getLogger(__name__)


def _canonical_prefix(path: str) -> str:
    """Normalize a path to a slash-terminated prefix safe for startswith()."""
    if not path:
        return "/"
    return path.rstrip("/") + "/"


def _path_segments(path: str) -> List[str]:
    return [seg for seg in path.split("/") if seg]


# Characters a regex reads specially outside a bracket; "]" and "}" are literal there.
_REGEX_SPECIAL = set(".[()*+?{|^$\\")
# Members a bracket expression cannot hold alike in Python re and POSIX ERE (wget),
# matched outside it instead.
_CLASS_UNSAFE = {"\\": r"\\", "]": "]", "^": r"\^", "-": "-", "[": r"\["}
# An optional "scheme://user@" lets one regex match HTTrack's two URL forms
# (htscore.c hts_url_forms): host/path without credentials, and the full URL.
_URL_FORMS = r"^([^:/?#]+://([^/?#@]*@)?)?"


def _literal(c: str) -> str:
    if c in string.ascii_letters:  # HTTrack compares ASCII letters case-insensitively (streql)
        return f"[{c.lower()}{c.upper()}]"
    return "\\" + c if c in _REGEX_SPECIAL else c


def _one_of(chars: set) -> str:
    """A regex for one character of `chars`, read alike by Python re and POSIX ERE."""
    safe = sorted(c for c in chars if c not in _CLASS_UNSAFE)
    alts = []
    if safe:
        runs, start = [], safe[0]
        for prev, c in zip(safe, safe[1:] + [None]):
            if c is None or ord(c) != ord(prev) + 1:
                runs.append(start if start == prev else f"{start}-{prev}")
                start = c
        alts.append("[" + "".join(runs) + "]")
    alts += [esc for c, esc in _CLASS_UNSAFE.items() if c in chars]
    return alts[0] if len(alts) == 1 else "(" + "|".join(alts) + ")"


def _class_chars(pattern: str, j: int) -> tuple[set, int]:
    """Members of the "*[...]" class whose body starts at `j`, and the index of its "]"
    (htsfilters.c strjoker_impl): "\\x" escapes, "a-z" ranges, "," or ";" separators."""
    chars, n = set(), len(pattern)
    while j < n and pattern[j] != "]":
        if pattern[j] == "\\" and j + 1 < n:
            chars.add(pattern[j + 1])
            j += 2
        elif pattern[j] in "<>":
            if pattern[j + 1:j + 2].isdigit():
                raise ValueError("size rules (*[<NN], *[>NN]) are not supported")
            j += 1  # HTTrack skips a bare < or >
        elif j + 2 < n and pattern[j + 1] == "-":
            if pattern[j + 2] > pattern[j]:
                chars.update(chr(k) for k in range(ord(pattern[j]), ord(pattern[j + 2]) + 1))
            j += 3
        else:
            chars.add(pattern[j])
            j += 1
        if j < n and pattern[j] in ",;":
            j += 1
    return chars, j


def rule_regex(pattern: str) -> str:
    """Translate an HTTrack scan-rule pattern (its +/- sign removed) to a regex.

    Faithful to htsfilters.c strjoker: anchored at the start; `*` is any run;
    `*[file]`/`*[name]` a run without / or ?; `*[path]` a run without ?;
    `*[param]` an optional query; `*[a-z,0-9,...]` a run of the listed characters
    (case-sensitive); `*[]` ends the URL there. Literals ignore ASCII case, and a
    pattern that ends without `*[]` still matches when a query follows. The result
    means the same to Python re and to wget's POSIX extended regex.
    """
    out, i, n = [_URL_FORMS], 0, len(pattern)
    while i < n:
        c = pattern[i]
        opener = pattern[i + 1:i + 2]
        if c != "*":
            out.append(_literal(c))
            i += 1
        elif opener not in ("[", "(") or pattern[i + 2:i + 3] == opener:
            out.append(".*")  # HTTrack reads "*[[" as a plain star
            i += 1
        elif opener == "(":
            raise ValueError("*(...) single-character classes are not supported")
        else:
            body = pattern[i + 2:].lower()
            if body.startswith(("file", "name", "path", "param")):
                end = pattern.find("]", i + 2)
                out.append(r"(\?.*)?" if body.startswith("param")
                           else "[^?]*" if body.startswith("path") else "[^?/]*")
                i = (n if end < 0 else end) + 1
            elif body.startswith("]"):
                return "".join(out) + "$"  # *[]: the rest of the pattern is never read
            else:
                chars, end = _class_chars(pattern, i + 2)
                if chars:
                    out.append(_one_of(chars) + "*")
                i = end + 1
    return "".join(out) + r"(\?.*)?$"


def match_form(url: str) -> str:
    """The URL as rules see it: no fragment, and "/" for an empty path (as HTTrack and wget)."""
    url = url.split("#", 1)[0]
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    return url if parts.path or not parts.netloc else urlunsplit(parts._replace(path="/"))


class UrlFilters:
    """`--filter` rules: HTTrack scan rules (`+pattern` accepts, `-pattern` refuses), the
    last matching rule wins. A URL no rule matches is left to the layer's own scope.

    `excluded` collects every URL a rule refused, for the end-of-run summary.
    """

    def __init__(self, rules: Sequence[str] = ()):
        self.rules: List[tuple[bool, str, str]] = []  # (accepts, pattern, regex)
        for rule in rules:
            if rule[:1] not in ("+", "-"):
                raise ValueError(f"rule {rule!r} must start with + or -")
            if rule[1:].startswith("mime:"):  # case-sensitive, as htsfilters.c fa_strjoker
                raise ValueError(f"rule {rule!r}: MIME rules are not supported")
            try:
                self.rules.append((rule[0] == "+", rule[1:], rule_regex(rule[1:])))
            except ValueError as e:
                raise ValueError(f"rule {rule!r}: {e}") from None
        self._compiled = [(accepts, re.compile(rx)) for accepts, _, rx in reversed(self.rules)]
        self.excluded: set = set()

    def decide(self, url: str) -> Optional[bool]:
        """True/False from the last rule matching `url`, None when no rule matches."""
        form = match_form(url)
        verdict = next((accepts for accepts, rx in self._compiled if rx.match(form)), None)
        if verdict is False:
            self.excluded.add(form)
        return verdict


def filter_urls(urls: List[str], base_url: str, depth: int = 0,
                filters: Optional[UrlFilters] = None) -> List[str]:
    """Return URLs under `base_url`'s scope, preserving order.

    Args:
        urls: candidate URLs (absolute http/https).
        base_url: scope root. URLs must share its netloc and sit under its
            (canonicalized) path prefix.
        depth: `0` means no depth limit. `>0` caps additional path segments
            beyond the base path.
        filters: `--filter` rules. A URL a rule accepts skips the path-prefix
            check (netloc and depth still apply); one a rule refuses is dropped
            and recorded in `filters.excluded`. `base_url` itself is never filtered.

    Out-of-scope URLs are dropped silently (debug-logged) so the return value
    is safe to feed directly into `run_wget_urls`.
    """
    parsed_base = urlparse(base_url)
    if not parsed_base.scheme or not parsed_base.netloc:
        logger.warning(f"url_filter: base_url missing scheme/netloc: {base_url}")
        return []

    base_netloc = parsed_base.netloc
    base_prefix = _canonical_prefix(parsed_base.path)
    base_segments = len(_path_segments(parsed_base.path))

    kept: List[str] = []
    seen = set()
    for url in urls:
        try:
            parsed = urlparse(url)
        except ValueError:
            logger.debug(f"url_filter: skip unparseable {url!r}")
            continue
        if parsed.scheme not in ("http", "https"):
            logger.debug(f"url_filter: skip non-http scheme {url!r}")
            continue
        if parsed.netloc != base_netloc:
            logger.debug(f"url_filter: skip cross-host {url!r} (base={base_netloc})")
            continue
        if depth > 0:
            url_segments = len(_path_segments(parsed.path))
            extra = url_segments - base_segments
            if extra > depth:
                logger.debug(
                    f"url_filter: skip too-deep {url!r} "
                    f"(depth={extra}, max={depth})"
                )
                continue
        verdict = filters.decide(url) if filters is not None and url != base_url else None
        if verdict is False:
            logger.debug(f"url_filter: skip {url!r} (refused by --filter)")
            continue
        url_prefix = _canonical_prefix(parsed.path)
        if verdict is None and not url_prefix.startswith(base_prefix):
            logger.debug(f"url_filter: skip out-of-scope path {url!r} (not under {base_prefix})")
            continue
        if url in seen:
            continue
        seen.add(url)
        kept.append(url)
    return kept
