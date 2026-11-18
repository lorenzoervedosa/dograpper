"""`download --downloader fire-engine`: curl_cffi browser-fingerprint profile (ADR-0011).

This mirrors the discovery -> fetch cascade of ``_httrack_profile.run_httrack``
(the first copy). The only differences are the ``CurlCffiFetcher`` transport and
the user-facing messages, so the httrack profile stays identical to HTTrack and
is left untouched. If this cascade needs a third copy, extract the shared core.
"""
import logging
from urllib.parse import urlsplit

import click

from ..lib.fire_engine.fetcher import CurlCffiFetcher
from ..lib.httrack.crawl import fetch_url_list
from ..lib.httrack.mirror import mirror_site
from ..lib.httrack.report import format_report
from ..lib.spa_detector import is_spa
from ._httrack_profile import _build_policy, discovery_fetch

logger = logging.getLogger(__name__)

_SPA_MSG = ("fire-engine: the content looks client-rendered (SPA); it runs no "
            "JavaScript. Use --downloader wget --headless.")
_SOLVER_MSG = ("fire-engine: the site challenged the request even with a browser "
               "TLS fingerprint. A manual-login browser solver is planned "
               "(ADR-0011); for now try --proxy with a different IP, or "
               "--downloader wget.")


def run_fire_engine(url, output, depth, delay, include_extensions, headless, verbose,
                    policy_kw, from_config, discover, filters, *, proxy, impersonate):
    """Seeded fetch when discovery finds a URL list, else the recursive crawl, both
    over a curl_cffi transport. Returns (downloaded, skipped, report lines, file -> URL)."""
    if headless:
        raise click.ClickException(
            "fire-engine: --headless is not supported (it runs its own "
            "browser-fingerprint transport). Omit --headless.")
    policy = _build_policy(delay, policy_kw, from_config)
    fetcher = CurlCffiFetcher(policy, proxy=proxy, impersonate=impersonate)
    parts = urlsplit(url)
    try:  # curl_cffi is imported on first use; this main-thread GET is that first use
        sitemap_hints = fetcher.robots_for(f"{parts.scheme}://{parts.netloc}").sitemaps
    except RuntimeError as e:  # curl_cffi not installed
        raise click.ClickException(str(e))
    discovered, winning_layer = discover(url, depth, discovery_fetch(fetcher), sitemap_hints,
                                         filters)
    if discovered:
        logger.info(f"[cascade] fire-engine: fetching {len(discovered)} URLs from {winning_layer}")
        res = fetch_url_list(discovered, output, policy, include_extensions, fetcher=fetcher,
                             filters=filters)
    else:
        logger.info("[cascade] fire-engine crawl: link-graph fallback")
        res = mirror_site(url, output, policy, include_extensions, depth=depth,
                          fetcher=fetcher, filters=filters)
    if res.front_failed or not res.success:
        for line in format_report(res.report, verbose):
            click.echo(f"  {line}", err=True)
    if res.front_failed:
        if res.report.challenged:
            raise click.ClickException(_SOLVER_MSG)
        where = "every seed URL" if discovered else "the start URL"
        raise click.ClickException(
            f"fire-engine: {where} was blocked by robots.txt, redirected out of scope "
            "or failed (see the report above).")
    if not res.success:
        raise click.ClickException("fire-engine fetch failed.")
    html_count = sum(f.lower().endswith((".html", ".htm")) for f in res.files_downloaded)
    if is_spa(output) or (not discovered and html_count <= 1):
        raise click.ClickException(_SPA_MSG)
    return len(res.files_downloaded), 0, format_report(res.report, verbose), res.urls
