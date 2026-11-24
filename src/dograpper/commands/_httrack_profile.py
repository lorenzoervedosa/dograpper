"""`download --downloader httrack`: profile options, discovery fetch, seeded fetch or crawl.

download.py keeps the click options and the dispatch; this module owns the mode.
"""

import dataclasses
import logging
import os
from typing import Callable, Dict, List, Tuple
from urllib.parse import urljoin, urlsplit

import click

from ..lib.config_loader import is_explicit
from ..lib.httrack.browser import Navigator
from ..lib.httrack.changes import CHANGES_FILE
from ..lib.httrack.cookies import Jar, load_jar
from ..lib.httrack.crawl import MAX_REDIRECTS, RunResponses, fetch_url_list
from ..lib.httrack.escape import request_target
from ..lib.httrack.fetcher import REDIRECTS, Fetcher, same_host
from ..lib.httrack.mirror import mirror_site
from ..lib.httrack.policy import build_policy, warn_if_old_openssl
from ..lib.httrack.report import RunReport, format_report
from ..lib.manifest import Manifest
from ..lib.playwright_crawl import run_browser_login, run_playwright_crawl
from ..lib.spa_detector import is_spa
from ..utils.atomic_write import atomic_write_bytes
from ..utils.portable_names import resolve_under
from ..utils.redact import redact_url
from ._profile_headers import checked_user_agent, single_user_agent, user_headers

logger = logging.getLogger(__name__)

# The [httrack] options of `download` (single list; sync forwards these plus --downloader).
PROFILE_OPTIONS = ('user_agent', 'header', 'no_robots', 'connections', 'max_conn_rate',
                   'max_bandwidth', 'timeout', 'retries', 'max_links', 'max_retry_after',
                   'disable_security_limits', 'no_parse_scripts', 'no_extended_parsing',
                   'cache', 'updatehack', 'do_not_recatch', 'changes')
# The [httrack] options of `download`, which fire-engine lacks (#152); sync forwards them too.
HTTRACK_OPTIONS = ('cookies', 'browser_headers', 'browser_login')
# Of them, the ones the profile runner takes (run_httrack keyword arguments), not the policy
_RUN_OPTIONS = ('cookies', 'browser_login')
# --no-X flags: the policy holds the positive switch
_NEGATED = {'no_robots': 'obey_robots', 'no_parse_scripts': 'parse_scripts',
            'no_extended_parsing': 'extended_parsing'}


def _flag(name: str) -> str:
    return "--" + name.replace('_', '-')


FROM_CONFIG = " (from .dograpper.json)"


def config_note(from_config: bool) -> str:
    """The suffix of a usage error about a value read from .dograpper.json."""
    return FROM_CONFIG if from_config else ""


def resolve_profile(ctx: click.Context, merged_params: dict, downloader: str):
    """Return (policy_kw, from_config, session) for the profile options, `session` the
    _RUN_OPTIONS for run_httrack. A value not set on the command line goes through its
    option's click type (ranges, booleans), so config gets the CLI's checks and messages;
    under wget a profile option, and under any downloader but httrack an [httrack] one,
    given on the command line or set away from its default in config, is a usage error."""
    names = (*PROFILE_OPTIONS, *HTTRACK_OPTIONS)
    params = [p for p in ctx.command.params if p.name in names]
    from_config = frozenset(k for k in (*names, 'delay') if not is_explicit(ctx, k))
    values = {}
    for param in params:
        value = merged_params[param.name]
        if param.multiple:  # --header: a CLI tuple, or a JSON list of strings
            # Second copy of download.py's _url_filters list check; a third gets a helper.
            if not isinstance(value, (list, tuple)) or not all(isinstance(v, str) for v in value):
                raise click.UsageError(f"{_flag(param.name)}{FROM_CONFIG} must be a "
                                       "list of 'Name: value' strings")
            value = tuple(value)
        elif param.name in from_config and not (value is None and param.default is None):
            try:
                # The text a user would type: "false" is False, 2.0 is not an int.
                value = param.type.convert(str(value), param, ctx)
            except click.BadParameter as e:
                raise click.BadParameter(
                    e.message, ctx,
                    param_hint=f"'{_flag(param.name)}'{FROM_CONFIG}") from None
        values[param.name] = value
    for param in params:
        only_httrack = param.name in HTTRACK_OPTIONS
        allowed = downloader == 'httrack' if only_httrack else downloader != 'wget'
        if not allowed and (param.name not in from_config or values[param.name] != param.default):
            needs = "httrack" if only_httrack else "httrack or fire-engine"
            flags = "/".join((*param.opts, *param.secondary_opts))  # --x/--no-x: both
            raise click.UsageError(f"{flags} requires --downloader {needs}")
    session = {k: values.pop(k) for k in _RUN_OPTIONS}
    header_ua, headers = user_headers(values.pop('header'), config_note('header' in from_config))
    user_agent = checked_user_agent(values['user_agent'],
                                    config_note('user_agent' in from_config))
    login = session['browser_login']  # its User-Agent is the browser's, known after the login
    agent = single_user_agent({"--user-agent": user_agent,
                               "--header 'User-Agent: …'": header_ua,
                               "--browser-login": "" if login else None})
    values['user_agent'] = None if login else agent
    policy_kw = {_NEGATED.get(k, k): (not v if k in _NEGATED else v) for k, v in values.items()}
    policy_kw['headers'] = headers
    return policy_kw, from_config, session


def _build_policy(delay, policy_kw, from_config):
    """build_policy with failures reported in CLI terms; config-sourced values say so."""
    src = lambda k: config_note(k in from_config)
    # --delay is shared with wget, so resolve_profile does not convert it
    if isinstance(delay, bool) or not isinstance(delay, (int, float)):
        raise click.UsageError(f"--delay must be a number, got {delay!r}{src('delay')}")
    try:
        return build_policy(delay_ms=delay, **policy_kw)
    except ValueError as e:  # a negative delay, or nan (click's float ranges let it through)
        msg = str(e).replace('delay_ms', 'delay')
        for k in (*PROFILE_OPTIONS, 'delay'):
            if msg.startswith(k + ' '):
                raise click.UsageError(f"{_flag(k)}{msg[len(k):]}{src(k)}")
        raise click.UsageError(msg)


def discovery_fetch(fetcher) -> Callable[[str], bytes | None]:
    """The parsers' `fetch` for layers 1 and 2: the shared fetcher, robots checked before
    every GET, same-host redirects followed as fetch_url_list follows them (spec 5.4)."""
    def fetch(u: str):
        for _ in range(MAX_REDIRECTS + 1):
            # Robots are checked BEFORE each GET so forbidden discovery URLs are never requested.
            try:
                parts = urlsplit(u)
                rules = fetcher.robots_for(f"{parts.scheme}://{parts.netloc}")
                # request_target raises ValueError (UnicodeEncodeError) on lone
                # surrogates; urlsplit raises it on malformed ports.
                allowed = rules.allowed(request_target(parts))
            except ValueError:
                logger.warning("[cascade] discovery: unusable URL skipped")
                return None
            if not allowed:
                logger.warning(f"[cascade] discovery: {redact_url(u)} blocked by robots.txt")
                return None
            r = fetcher.get(u, kind="robots")
            if r.challenged:
                logger.warning(f"[cascade] discovery: {redact_url(u)} challenged (bot protection)")
                return None
            if r.status in REDIRECTS and r.location:
                try:
                    nxt = urljoin(u, r.location)
                except ValueError:  # e.g. "http://[bad"
                    logger.warning(f"[cascade] discovery: {redact_url(u)} redirected to a "
                                   "malformed URL (not followed)")
                    return None
                if not same_host(u, nxt):
                    logger.warning(f"[cascade] discovery: {redact_url(u)} redirected off-host "
                                   f"to {redact_url(nxt)} (not followed)")
                    return None
                u = nxt
                continue
            if r.error is not None or r.status is None or not 200 <= r.status < 300:
                return None
            return r.body
        logger.warning(f"[cascade] discovery: {redact_url(u)} too many redirects")
        return None
    return fetch


def _unreached(previous: Manifest, output: str, reached) -> List[str]:
    """The files of `previous` still on disk that this run neither saved nor kept: HTTrack
    purges them (-X); the profile only lists them (spec 5.6). URL when recorded, else path."""
    root, seen = os.path.realpath(output), {os.path.realpath(f) for f in reached}
    out = []
    for key, e in previous.files.items():
        path = resolve_under(root, e.local_path or key)
        if path and path not in seen and os.path.isfile(path):
            out.append(redact_url(e.url) if e.url else e.local_path or key)
    return sorted(out)


# The flags about the previous run's files (an update's --cache, --updatehack and
# --do-not-recatch, the --changes report against them): --headless revalidates no page.
_PREVIOUS_RUN_FLAGS = (("--cache", lambda p: p.cache is not None),
                       ("--updatehack", lambda p: p.updatehack),
                       ("--do-not-recatch", lambda p: p.do_not_recatch),
                       ("--changes", lambda p: p.changes))


def _browse(fetcher, url, output, depth, include_extensions, filters, seeds, reuse=None):
    """Layer 4 under the profile: the Playwright crawl from `url`, or over the discovered
    `seeds` alone, every navigation fetched by `fetcher` under its policy (Navigator), except
    the pages `reuse` (RunResponses) holds from the engine's fetch of this run.
    Returns (CrawlResult, its RunReport, file -> record)."""
    nav = Navigator(fetcher, output, url, include_extensions, filters=filters,
                    seeded=bool(seeds), reuse=reuse)
    try:  # the Fetcher paces (policy.delay_ms); an update is the engine's
        res = run_playwright_crawl(url, output, depth, 0, include_extensions, None,
                                   seed_urls=seeds or None, filters=filters, navigator=nav)
    except RuntimeError as e:  # playwright not installed
        raise click.ClickException(str(e))
    return res, nav.report, nav.records


def run_profile(name, make_fetcher, url, output, depth, delay, include_extensions, verbose,
                policy_kw, from_config, discover, filters, previous: Manifest | None, *,
                front_failed: Callable[[bool, bool], str], fallback: str | None,
                headless: bool = False
                ) -> Tuple[int, int, List[str], Dict[str, str], Dict[str, dict]]:
    """The cascade of the profiles on the httrack engine (httrack, fire-engine), over the
    transport `make_fetcher(policy)` builds: seeded fetch when `discover` (download's layers
    1+2, `_discover_urls`) finds a URL list, else the recursive crawl from `url`; `filters`
    (--filter) scopes both. With the `previous` run's manifest the run is an update (HTTrack
    -C2): its files are revalidated. `front_failed(discovered, challenged)` words the exit
    when the start URL or every seed failed; `fallback` is the exit when the result needs a
    browser, or None to run the Playwright crawl under the policy (_browse) after the
    engine's fetch, as `headless` does in its place. Returns (downloaded, kept unchanged,
    report lines, file -> URL fetched, file -> record)."""
    policy = _build_policy(delay, policy_kw, from_config)
    if headless:
        flags = [flag for flag, on in _PREVIOUS_RUN_FLAGS if on(policy)]
        if flags:
            raise click.UsageError(f"{', '.join(flags)}: no page is revalidated under "
                                   "--headless (the browser fetches each one in full)")
    fetcher = make_fetcher(policy)
    policy = fetcher.policy  # the transport's, e.g. with --browser-login's User-Agent
    parts = urlsplit(url)
    sitemap_hints = fetcher.robots_for(f"{parts.scheme}://{parts.netloc}").sitemaps
    discovered, winning_layer = discover(url, depth, discovery_fetch(fetcher), sitemap_hints,
                                         filters)
    written, kept, urls, records, changes = [], [], {}, {}, None

    def unreached(report: RunReport) -> None:
        if previous is not None and policy.cache != 0:  # -C0 keeps no file list (htscore.c:2147)
            report.unreached = _unreached(previous, output, [*written, *kept])

    def fail(report: RunReport, message: str):
        for line in format_report(report, verbose):  # the report first, then the error
            click.echo(f"  {line}", err=True)
        raise click.ClickException(message)

    browse = headless
    # a browser pass may follow the engine's fetch: it reuses what that fetch received
    responses = RunResponses() if not headless and fallback is None else None
    if not headless:
        if discovered:
            logger.info(f"[cascade] {name}: fetching {len(discovered)} URLs from "
                        f"{winning_layer}")
            res = fetch_url_list(discovered, output, policy, include_extensions,
                                 fetcher=fetcher, filters=filters, previous=previous,
                                 responses=responses)
        else:
            logger.info(f"[cascade] layer-3 {name} crawl: link-graph fallback")
            res = mirror_site(url, output, policy, include_extensions, depth=depth,
                              fetcher=fetcher, filters=filters, previous=previous,
                              responses=responses)
        report, written, kept = res.report, res.files_downloaded, res.kept
        urls, records, changes = res.urls, res.records, res.changes
        unreached(report)
        if res.front_failed:
            fail(report, front_failed(bool(discovered), bool(report.challenged)))
        if not res.success:
            fail(report, f"{name} fetch failed.")
        # the wget cascade's Playwright triggers, on real 2xx content (spec 5.4): an SPA
        # shell, or a crawl that found one page, unless challenges stopped it there
        html_count = sum(f.lower().endswith((".html", ".htm")) for f in (*written, *kept))
        if is_spa(output) or (not discovered and html_count <= 1 and not report.challenged):
            if fallback is not None:
                raise click.ClickException(fallback)
            logger.info(f"[cascade] layer-4 playwright under {name}: the result looks "
                        "client-rendered")
            browse = True
    if not browse:
        lines = format_report(report, verbose)
    else:
        if headless:
            logger.info(f"[cascade] layer-4 playwright under {name}: "
                        + (f"{len(discovered)} URLs from {winning_layer}" if discovered
                           else "direct crawl"))
        pw, pw_report, pw_records = _browse(fetcher, url, output, depth, include_extensions,
                                            filters, discovered, responses)
        written = sorted({*written, *pw.files_downloaded})  # rendered over the engine's copy
        kept = [f for f in kept if f not in written]
        urls, records = {**urls, **pw.urls}, {**records, **pw_records}
        if headless:
            unreached(pw_report)
            if not pw.files_downloaded:  # the start URL, or every seed, refused or failed
                fail(pw_report, front_failed(bool(discovered), bool(pw_report.challenged)))
            lines = format_report(pw_report, verbose)
        else:  # the engine fetched the start URL: the browser pass is no front (spec 5.8)
            unreached(report)
            lines = [*format_report(report, verbose), "Playwright pass:",
                     *(f"  {line}" for line in format_report(pw_report, verbose))]
    path = os.path.join(output, CHANGES_FILE)
    if browse and policy.changes:  # the browser pass rewrote the files the report describes (#172)
        try:
            os.remove(path)  # a report an earlier run left would describe another run
        except FileNotFoundError:
            pass
        lines.append("Change report skipped: the browser pass rewrote the files")
    elif changes is not None:  # written for a completed run only (htscore.c:2360-2367)
        text, summary = changes
        try:
            atomic_write_bytes(path, text.encode("utf-8"))
        except OSError as e:  # HTTrack logs it and the run goes on (htschanges.c:575-586)
            summary = f"Unable to write the change report {path}: {e}"
        lines.append(summary)
    return len(written), len(kept), lines, urls, records


def _front_failed(discovered: bool, challenged: bool) -> str:
    if discovered:
        cause = ("the site refused or challenged every seed URL (likely bot protection; "
                 "--browser-login lets you pass the challenge in a browser window)"
                 if challenged else
                 "every seed URL was blocked by robots.txt or failed (see the report above)")
    else:
        cause = ("the site challenged the start URL (likely bot protection; "
                 "--browser-login lets you pass the challenge in a browser window)"
                 if challenged else
                 "the start URL was blocked by robots.txt, redirected out of scope or "
                 "failed (see the report above)")
    return f"httrack profile: {cause}. See the README section \"Downloader profiles\"."


def _jar(path: str | None, from_config) -> Jar | None:
    """The --cookies jar, loaded before any request; a bad line is a usage error naming
    its number, never its content (lib/httrack/cookies.py)."""
    if path is None:
        return None
    try:
        return load_jar(path)
    except ValueError as e:
        raise click.UsageError(f"--cookies {path}: {e}{config_note('cookies' in from_config)}")
    except OSError as e:
        raise click.ClickException(f"--cookies: cannot read {path}: {e.strerror or e}")


def _login(url: str) -> tuple[list[dict], str]:
    """--browser-login's headed Chromium (lib/playwright_crawl.py), failures as exit 1."""
    try:
        return run_browser_login(url)
    except RuntimeError as e:  # Playwright, Chromium or a display missing; no Enter
        raise click.ClickException(str(e))
    except ValueError as e:  # check_value: a User-Agent no header line can carry
        raise click.ClickException(f"--browser-login: {e}")


def run_httrack(url, output, depth, delay, include_extensions, headless, verbose,
                policy_kw, from_config, discover, filters, previous: Manifest | None = None,
                *, cookies: str | None = None, browser_login: bool = False
                ) -> Tuple[int, int, List[str], Dict[str, str], Dict[str, dict]]:
    """The httrack profile: run_profile over the stdlib Fetcher, HTTrack's identity, with
    the Playwright crawl under its policy for --headless and client-rendered sites.
    `cookies` (--cookies FILE) is the jar the Fetcher sends and fills, written back to
    FILE when the run ends, a failed one included (HTTrack -%K). `browser_login` (#171)
    opens a headed Chromium on `url` before the first request: its cookies go into the jar
    and its User-Agent is the run's."""
    warn_if_old_openssl()
    jar, failed = None, True

    def make_fetcher(policy):  # past run_profile's usage checks: a refused run reads no jar
        nonlocal jar
        loaded = _jar(cookies, from_config)
        if browser_login:
            found, agent = _login(url)
            loaded = loaded if loaded is not None else Jar(None)  # no FILE: kept for the run
            loaded.merge(found)
            policy = dataclasses.replace(policy, user_agent=agent)
        jar = loaded
        return Fetcher(policy, cookies=jar)

    try:
        result = run_profile("httrack", make_fetcher, url, output, depth, delay,
                             include_extensions, verbose, policy_kw, from_config, discover,
                             filters, previous, front_failed=_front_failed, fallback=None,
                             headless=headless)
        failed = False
        return result
    finally:
        if jar is not None and jar.path is not None:
            try:
                jar.save()
            except OSError as e:
                msg = f"--cookies: cannot write {jar.path}: {e.strerror or e}"
                if failed:  # the run's own error stays the one shown
                    logger.error(msg)
                else:
                    raise click.ClickException(msg) from None
