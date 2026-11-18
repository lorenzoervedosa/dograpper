"""`download --downloader fire-engine`: curl_cffi browser-fingerprint profile (ADR-0011).

The cascade is ``_httrack_profile.run_profile``, shared with the httrack profile; this
module only differs in the ``CurlCffiFetcher`` transport, the messages and the
headless rule.
"""
import click

from ..lib.fire_engine.fetcher import CurlCffiFetcher, CurlCffiMissing
from ._httrack_profile import run_profile

_SPA_MSG = ("fire-engine: the content looks client-rendered (SPA); it runs no "
            "JavaScript. Use --downloader wget --headless.")
_SOLVER_MSG = ("fire-engine: the site challenged the request even with a browser "
               "TLS fingerprint. A manual-login browser solver is planned "
               "(ADR-0011); for now try --proxy with a different IP, or "
               "--downloader wget.")


def _front_failed(discovered: bool, challenged: bool) -> str:
    if challenged:
        return _SOLVER_MSG
    where = "every seed URL" if discovered else "the start URL"
    return (f"fire-engine: {where} was blocked by robots.txt, redirected out of scope "
            "or failed (see the report above).")


def run_fire_engine(url, output, depth, delay, include_extensions, headless, verbose,
                    policy_kw, from_config, discover, filters, *, proxy, impersonate):
    """run_profile over a curl_cffi transport. Returns (downloaded, skipped, report lines,
    file -> URL)."""
    if headless:
        raise click.ClickException(
            "fire-engine: --headless is not supported (it runs its own "
            "browser-fingerprint transport). Omit --headless.")
    try:  # curl_cffi is imported by the first GET: robots.txt, or discovery under --no-robots
        return run_profile(
            "fire-engine",
            lambda policy: CurlCffiFetcher(policy, proxy=proxy, impersonate=impersonate),
            url, output, depth, delay, include_extensions, verbose, policy_kw, from_config,
            discover, filters, None, front_failed=_front_failed, fallback=_SPA_MSG)[:4]
    except CurlCffiMissing as e:
        raise click.ClickException(str(e))
