"""--header lines and the User-Agent of the downloader profiles (#136): each line checked by
the shared wire guard (utils/http_headers.py), and the one User-Agent among its sources."""

from typing import Dict

import click

from ..utils.http_headers import check_value, parse_header


def user_headers(lines, src: str):
    """The --header lines, each checked by parse_header (the shared wire guard), as
    (the User-Agent among them or None, the other (name, value) pairs); `src` is the
    config_note of the lines."""
    pairs, seen = [], set()
    for position, line in enumerate(lines, 1):
        try:
            name, value = parse_header(line, position)
        except ValueError as e:
            raise click.UsageError(f"--header {e}{src}") from None
        if name.lower() in seen:  # no silent last-one-wins
            raise click.UsageError(f"--header {name} is given more than once; give it once{src}")
        seen.add(name.lower())
        pairs.append((name, value))
    agent = next((value for name, value in pairs if name.lower() == "user-agent"), None)
    return agent, tuple(pair for pair in pairs if pair[0].lower() != "user-agent")


def checked_user_agent(value: str | None, src: str) -> str | None:
    """The --user-agent value, through the check --header lines get (it goes on the wire
    the same way); `src` is its config_note."""
    if value is not None:
        try:
            check_value("User-Agent", value)
        except ValueError as e:
            raise click.UsageError(f"--user-agent: {e}{src}") from None
    return value


def single_user_agent(sources: Dict[str, str | None]) -> str | None:
    """The one User-Agent among `sources` (flag text -> value, or None when not given).
    Given two ways it is a usage error (exit 2) naming the flags, never the values (#136;
    #171 adds --browser-login as a source)."""
    given = [flag for flag, value in sources.items() if value is not None]
    if len(given) > 1:
        raise click.UsageError(f"{' and '.join(given)} both set the User-Agent; give one")
    return sources[given[0]] if given else None
