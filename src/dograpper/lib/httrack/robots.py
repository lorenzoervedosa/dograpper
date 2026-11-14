"""robots.txt parser: RFC 9309 matching with HTTrack's caps and tie rules."""

import logging
import re
from dataclasses import dataclass

logger = logging.getLogger(__name__)

MAX_TEXT_BYTES = 500 * 1024
MAX_LINE_BYTES = 1024


@dataclass(frozen=True)
class RobotsRules:
    # (kind, pattern) with kind in {"allow", "disallow"}, from the selected group.
    groups_rules: tuple[tuple[str, str], ...]
    crawl_delay: float | None
    sitemaps: tuple[str, ...]

    def allowed(self, path_and_query: str) -> bool:
        if path_and_query == "/robots.txt":
            return True
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


def _matches(pattern: str, path: str) -> bool:
    anchored = pattern.endswith("$")
    body = pattern[:-1] if anchored else pattern
    regex = ".*".join(re.escape(part) for part in body.split("*"))
    return re.match(regex + ("\\Z" if anchored else ""), path, re.DOTALL) is not None


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
                groups[-1][1].append((key, value))

    specific = [g for g in groups if any(a.startswith(agent_token) for a in g[0])]
    selected = specific or [g for g in groups if "*" in g[0]]
    rules = tuple(r for g in selected for r in g[1])
    delays = [d for g in selected for d in g[2]]
    return RobotsRules(rules, delays[0] if delays else None, tuple(sitemaps))
