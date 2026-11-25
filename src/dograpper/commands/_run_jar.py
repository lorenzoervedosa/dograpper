"""The cookie jar of one httrack-profile run: --cookies (#169) and --browser-login (#171).

`run_httrack` (_httrack_profile.py) opens it in its fetcher factory, past the run's usage
checks and before the first request, and closes it when the run ends, a failed one
included: the jar goes back to the --cookies file then (HTTrack -%K).
"""

import dataclasses
import logging
from urllib.parse import urlsplit

import click

from ..lib.httrack.cookies import Jar, load_jar
from ..lib.httrack.fetcher import wire_host
from ..lib.httrack.policy import HttrackPolicy
from ..lib.playwright_crawl import run_browser_login

logger = logging.getLogger(__name__)


def _wire_hostname(url: str) -> str | None:
    """The start host as the Fetcher asks the jar for it: the name on the wire (IDNA,
    wire_host), lowercase, without port. One IDNA cannot encode keeps its own form: no
    request reaches it either (the Fetcher calls its URL invalid)."""
    parts = urlsplit(url)
    try:
        return urlsplit("//" + wire_host(parts)).hostname
    except ValueError:
        return parts.hostname


def _press_enter() -> None:
    """--browser-login's terminal side: the person says the login is done."""
    click.echo("Log in, or pass the challenge, in the browser window, then press Enter "
               "here.", err=True)
    try:
        input()
    except EOFError:
        raise click.ClickException("--browser-login waits for you to press Enter, and the "
                                   "terminal input is closed. Run it in an interactive "
                                   "terminal.") from None


class RunJar:
    """`cookies`: the --cookies FILE or None, `note` its config_note; `browser_login`: open
    the login window on `url` first."""

    def __init__(self, url: str, cookies: str | None, note: str, browser_login: bool):
        self._url, self._path, self._note, self._login = url, cookies, note, browser_login
        self._host = _wire_hostname(url)  # the jar's cookies go to the start host alone
        self.jar: Jar | None = None

    def open(self, policy: HttrackPolicy) -> tuple[HttrackPolicy, Jar | None]:
        """Load the --cookies file (a bad line is exit 2, naming its number, never its
        content), then run the login: its cookies go into the jar over the file's, and its
        User-Agent into the policy. Returns (the policy, the jar or None)."""
        jar = self._load()
        if self._login:
            try:
                found, agent = run_browser_login(self._url, _press_enter)
            except RuntimeError as e:  # Playwright, Chromium or a display missing
                raise click.ClickException(str(e))
            except ValueError as e:  # check_value: a User-Agent no header line can carry
                raise click.ClickException(f"--browser-login: {e}")
            jar = jar if jar is not None else Jar(None, self._host)  # no FILE: the run's alone
            jar.merge(found)
            policy = dataclasses.replace(policy, user_agent=agent)
        self.jar = jar
        return policy, jar

    def _load(self) -> Jar | None:
        if self._path is None:
            return None
        try:
            return load_jar(self._path, self._host)
        except ValueError as e:
            raise click.UsageError(f"--cookies {self._path}: {e}{self._note}")
        except OSError as e:
            raise click.ClickException(f"--cookies: cannot read {self._path}: "
                                       f"{e.strerror or e}")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        """Write the jar back to its file, if the run opened one."""
        if self.jar is None or self.jar.path is None:
            return
        try:
            self.jar.save()
        except OSError as e:
            msg = f"--cookies: cannot write {self.jar.path}: {e.strerror or e}"
            if exc_type is not None:  # the run's own error stays the one shown
                logger.error(msg)
            else:
                raise click.ClickException(msg) from None
