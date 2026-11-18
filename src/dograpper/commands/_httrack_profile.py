"""`download --downloader httrack`: profile options, discovery fetch, seeded fetch or crawl.

download.py keeps the click options and the dispatch; this module owns the mode.
"""

import logging
import os
from typing import Callable, Dict, List, Tuple
from urllib.parse import urljoin, urlsplit

import click

from ..lib.config_loader import is_explicit
from ..lib.httrack.crawl import MAX_REDIRECTS, fetch_url_list
from ..lib.httrack.escape import request_target
from ..lib.httrack.fetcher import REDIRECTS, Fetcher, same_host
from ..lib.httrack.mirror import mirror_site
from ..lib.httrack.policy import build_policy, warn_if_old_openssl
from ..lib.httrack.report import format_report
from ..lib.manifest import Manifest
from ..lib.spa_detector import is_spa
from ..utils.portable_names import resolve_under
from ..utils.redact import redact_url

logger = logging.getLogger(__name__)

_PLAYWRIGHT_MSG = ("httrack profile: Playwright fallback is not implemented yet "
                   "(planned); use --downloader wget")


# The [httrack] options of `download` (single list; sync forwards these plus --downloader).
PROFILE_OPTIONS = ('user_agent', 'no_robots', 'connections', 'max_conn_rate', 'max_bandwidth',
                   'timeout', 'retries', 'max_links', 'max_retry_after',
                   'disable_security_limits', 'no_parse_scripts', 'no_extended_parsing',
                   'cache')
# --no-X flags: the policy holds the positive switch
_NEGATED = {'no_robots': 'obey_robots', 'no_parse_scripts': 'parse_scripts',
            'no_extended_parsing': 'extended_parsing'}


def _flag(name: str) -> str:
    return "--" + name.replace('_', '-')


def resolve_profile(ctx: click.Context, merged_params: dict, downloader: str):
    """Return (policy_kw, from_config) for the profile options. A value not set on the
    command line goes through its option's click type (ranges, booleans), so config
    gets the CLI's checks and messages; under wget a profile option given on the
    command line, or set away from its default in config, is a usage error."""
    params = [p for p in ctx.command.params if p.name in PROFILE_OPTIONS]
    from_config = frozenset(k for k in (*PROFILE_OPTIONS, 'delay') if not is_explicit(ctx, k))
    values = {}
    for param in params:
        value = merged_params[param.name]
        if param.name in from_config and not (value is None and param.default is None):
            try:
                # The text a user would type: "false" is False, 2.0 is not an int.
                value = param.type.convert(str(value), param, ctx)
            except click.BadParameter as e:
                raise click.BadParameter(
                    e.message, ctx,
                    param_hint=f"'{_flag(param.name)}' (from .dograpper.json)") from None
        values[param.name] = value
    if downloader == 'wget':
        for param in params:
            if param.name not in from_config or values[param.name] != param.default:
                raise click.UsageError(f"{_flag(param.name)} requires --downloader httrack")
    policy_kw = {_NEGATED.get(k, k): (not v if k in _NEGATED else v) for k, v in values.items()}
    return policy_kw, from_config


def _build_policy(delay, policy_kw, from_config):
    """build_policy with failures reported in CLI terms; config-sourced values say so."""
    src = lambda k: " (from .dograpper.json)" if k in from_config else ""
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


def run_profile(name, make_fetcher, url, output, depth, delay, include_extensions, verbose,
                policy_kw, from_config, discover, filters, previous: Manifest | None, *,
                front_failed: Callable[[bool, bool], str], fallback: str
                ) -> Tuple[int, int, List[str], Dict[str, str], Dict[str, dict]]:
    """The cascade of the profiles on the httrack engine (httrack, fire-engine), over the
    transport `make_fetcher(policy)` builds: seeded fetch when `discover` (download's layers
    1+2, `_discover_urls`) finds a URL list, else the recursive crawl from `url`; `filters`
    (--filter) scopes both. With the `previous` run's manifest the run is an update (HTTrack
    -C2): its files are revalidated. `front_failed(discovered, challenged)` words the exit
    when the start URL or every seed failed; `fallback` is the exit when the result needs a
    browser. Returns (downloaded, kept unchanged, report lines, file -> URL fetched,
    file -> record)."""
    policy = _build_policy(delay, policy_kw, from_config)
    fetcher = make_fetcher(policy)
    parts = urlsplit(url)
    sitemap_hints = fetcher.robots_for(f"{parts.scheme}://{parts.netloc}").sitemaps
    discovered, winning_layer = discover(url, depth, discovery_fetch(fetcher), sitemap_hints,
                                         filters)
    if discovered:
        logger.info(f"[cascade] {name}: fetching {len(discovered)} URLs from {winning_layer}")
        res = fetch_url_list(discovered, output, policy, include_extensions, fetcher=fetcher,
                             filters=filters, previous=previous)
    else:
        logger.info(f"[cascade] layer-3 {name} crawl: link-graph fallback")
        res = mirror_site(url, output, policy, include_extensions, depth=depth,
                          fetcher=fetcher, filters=filters, previous=previous)
    if previous is not None and policy.cache != 0:  # -C0 keeps no file list (htscore.c:2147)
        res.report.unreached = _unreached(previous, output, [*res.files_downloaded, *res.kept])
    if res.front_failed or not res.success:
        for line in format_report(res.report, verbose):
            click.echo(f"  {line}", err=True)
    if res.front_failed:
        raise click.ClickException(front_failed(bool(discovered), bool(res.report.challenged)))
    if not res.success:
        raise click.ClickException(f"{name} fetch failed.")
    # the wget cascade's Playwright triggers: an SPA shell, or a crawl that found one page
    html_count = sum(f.lower().endswith((".html", ".htm"))
                     for f in (*res.files_downloaded, *res.kept))
    if is_spa(output) or (not discovered and html_count <= 1):
        raise click.ClickException(fallback)
    return (len(res.files_downloaded), res.files_skipped, format_report(res.report, verbose),
            res.urls, res.records)


def _front_failed(discovered: bool, challenged: bool) -> str:
    if discovered:
        cause = ("the site refused or challenged every seed URL (likely bot protection)"
                 if challenged else
                 "every seed URL was blocked by robots.txt or failed (see the report above)")
    else:
        cause = ("the site challenged the start URL (likely bot protection)"
                 if challenged else
                 "the start URL was blocked by robots.txt, redirected out of scope or "
                 "failed (see the report above)")
    return f"httrack profile: {cause}. See the README section \"Downloader profiles\"."


def run_httrack(url, output, depth, delay, include_extensions, headless, verbose,
                policy_kw, from_config, discover, filters, previous: Manifest | None = None
                ) -> Tuple[int, int, List[str], Dict[str, str], Dict[str, dict]]:
    """The httrack profile: run_profile over the stdlib Fetcher, HTTrack's identity."""
    warn_if_old_openssl()
    if headless:
        raise click.ClickException(_PLAYWRIGHT_MSG)
    return run_profile("httrack", Fetcher, url, output, depth, delay, include_extensions,
                       verbose, policy_kw, from_config, discover, filters, previous,
                       front_failed=_front_failed, fallback=_PLAYWRIGHT_MSG)
