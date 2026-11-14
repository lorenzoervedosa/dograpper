"""robots.txt parser: RFC 9309 matching with HTTrack's caps and tie rules."""

import logging
import re
from dataclasses import dataclass
from functools import lru_cache

logger = logging.getLogger(__name__)

MAX_TEXT_BYTES = 500 * 1024
MAX_LINE_BYTES = 1024


_PCT = re.compile(r"%[0-9a-fA-F]{2}")


def _upper_hex(s: str) -> str:
    """RFC 9309 2.2.2: compare percent-escapes case-insensitively."""
    return _PCT.sub(lambda m: m.group().upper(), s)


@dataclass(frozen=True)
class RobotsRules:
    # (kind, pattern) with kind in {"allow", "disallow"}, from the selected group.
    groups_rules: tuple[tuple[str, str], ...]
    crawl_delay: float | None
    sitemaps: tuple[str, ...]

    def allowed(self, path_and_query: str) -> bool:
        if path_and_query == "/robots.txt":
            return True
        path_and_query = _upper_hex(path_and_query)
        best_len, verdict = -1, True
        for kind, pattern in self.groups_rules:
            if not _matches(pattern, path_and_query):
                continue
            allow = kind == "allow"
            # Longest pattern wins; Allow wins ties.
            if len(pattern) > best_len or (len(pattern) == best_len and allow):
                best_len, verdict = len(pattern), allow
        return verdict


NO_RULES = RobotsRules((), None, ())


@lru_cache(maxsize=4096)
def _split(pattern: str) -> tuple[tuple[str, ...], bool]:
    anchored = pattern.endswith("$")
    return tuple((pattern[:-1] if anchored else pattern).split("*")), anchored


def _matches(pattern: str, path: str) -> bool:
    """Linear greedy segment search; no regex, so hostile patterns cannot backtrack."""
    pieces, anchored = _split(pattern)
    first = pieces[0]
    if not path.startswith(first):
        return False
    if len(pieces) == 1:
        return path == first if anchored else True
    pos = len(first)
    last = pieces[-1]
    for piece in pieces[1:-1]:
        i = path.find(piece, pos)
        if i < 0:
            return False
        pos = i + len(piece)
    if anchored:
        return len(path) - len(last) >= pos and path.endswith(last)
    return path.find(last, pos) >= 0


def _cap(text: str, limit: int) -> tuple[str, bool]:
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text, False
    return raw[:limit].decode("utf-8", errors="ignore"), True


def parse_robots(text: str, agent_token: str = "dograpper") -> RobotsRules:
    agent_token = agent_token.lower()
    text, cut = _cap(text, MAX_TEXT_BYTES)
    if cut:
        logger.warning("robots.txt exceeds %d bytes; truncated", MAX_TEXT_BYTES)

    # Each group: (agents, rules, crawl delays).
    groups: list[tuple[list[str], list[tuple[str, str]], list[float]]] = []
    sitemaps: list[str] = []
    in_agents = False
    for line in text.splitlines():
        line, truncated = _cap(line, MAX_LINE_BYTES)
        line = line.split("#", 1)[0]
        key, sep, value = line.partition(":")
        if not sep:
            continue
        key, value = key.strip().lower(), value.strip()
        if key == "user-agent":
            if not in_agents:
                groups.append(([], [], []))
            groups[-1][0].append(value.lower())
            in_agents = True
            continue
        if key == "sitemap":
            if value:
                sitemaps.append(value)
            continue
        if key in ("allow", "disallow", "crawl-delay"):
            in_agents = False
            if not groups:
                continue
            if truncated:
                logger.warning("robots.txt line truncated at %d bytes: %s", MAX_LINE_BYTES, key)
                if key == "allow":
                    continue
            if key == "crawl-delay":
                try:
                    groups[-1][2].append(float(value))
                except ValueError:
                    pass
            elif value:  # empty Disallow/Allow is ignored
                groups[-1][1].append((key, _upper_hex(value)))

    specific = [g for g in groups if any(a.startswith(agent_token) for a in g[0])]
    selected = specific or [g for g in groups if "*" in g[0]]
    rules = tuple(r for g in selected for r in g[1])
    delays = [d for g in selected for d in g[2]]
    return RobotsRules(rules, delays[0] if delays else None, tuple(sitemaps))
