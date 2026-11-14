"""Download subcommand with 4-layer discovery cascade."""

import os
import click
import logging
from typing import List, Tuple

from urllib.parse import urlsplit

from ..lib.config_loader import is_explicit_source, load_config
from ..lib.httrack.crawl import fetch_url_list
from ..lib.httrack.fetcher import Fetcher, request_target
from ..lib.httrack.policy import build_policy, warn_if_old_openssl
from ..lib.httrack.report import format_report
from ..utils.redact import redact_url
from ..lib.llms_txt_parser import fetch_llms_txt
from ..lib.manifest import load_manifest, save_manifest, build_manifest, merge_manifests
from ..lib.playwright_crawl import run_playwright_crawl
from ..lib.sitemap_parser import fetch_sitemap
from ..lib.spa_detector import is_spa
from ..lib.url_filter import filter_urls
from ..lib.wget_mirror import run_wget_mirror, run_wget_urls

logger = logging.getLogger(__name__)

# Minimum URLs a discovery layer must yield to be declared the cascade winner.
# Below this, the layer "falls through" to the next one so that a 2-URL
# llms.txt boilerplate stub does not short-circuit the full crawl.
MIN_URLS_TO_CONSIDER_DISCOVERED = 3


def _snapshot_dir(path: str) -> dict:
    """Snapshot existing files under ``path`` mapping absolute path -> mtime."""
    snapshot: dict = {}
    if not os.path.exists(path):
        return snapshot
    for root, _, files in os.walk(path):
        for f in files:
            fp = os.path.join(root, f)
            try:
                snapshot[fp] = os.path.getmtime(fp)
            except OSError:
                pass
    return snapshot


def _compute_stats(
    files_downloaded: List[str],
    pre_snapshot: dict,
    is_incremental: bool,
) -> Tuple[int, int]:
    """Compare post-wget file list against pre-snapshot mtimes.

    Returns (touched, unchanged) counts. In non-incremental mode, everything
    counts as touched.
    """
    if not is_incremental:
        return len(files_downloaded), 0
    touched = 0
    unchanged = 0
    for p in files_downloaded:
        prev_mtime = pre_snapshot.get(p)
        try:
            curr_mtime = os.path.getmtime(p)
        except OSError:
            continue
        if prev_mtime is None or curr_mtime > prev_mtime:
            touched += 1
        else:
            unchanged += 1
    return touched, unchanged


def _normalize_extensions(value) -> str:
    if isinstance(value, (list, tuple)):
        return ",".join(str(x).strip().lstrip('.') for x in value if str(x).strip())
    return str(value)


def _discover_urls(url: str, depth: int, fetcher=None) -> Tuple[List[str], str]:
    """Run Layer 1 (llms.txt) then Layer 2 (sitemap). Return (urls, layer).

    Layers 1+2 run unconditionally (regardless of --headless) because
    llms.txt/sitemap are the canonical authoritative indexes for SPAs like
    Mintlify; skipping them under --headless would throw away the strongest
    signal on the exact code path designed for SPAs.

    With an httrack ``fetcher`` the parsers fetch through it (shared pacing and
    robots cache); without one they use their own HTTP, exactly as before.
    """
    parser_kw: dict = {}
    sitemap_kw: dict = {}
    if fetcher is not None:
        def fetch(u: str):
            # Robots are checked BEFORE the GET so forbidden discovery URLs are never requested.
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
            if r.status is not None and 300 <= r.status < 400:
                logger.warning(f"[cascade] discovery: {redact_url(u)} redirected (not followed)")
                return None
            if r.error is not None or r.status is None or not 200 <= r.status < 300:
                return None
            return r.body

        parts = urlsplit(url)
        sitemaps = fetcher.robots_for(f"{parts.scheme}://{parts.netloc}").sitemaps
        parser_kw = {"fetch": fetch}
        sitemap_kw = {"fetch": fetch, "extra_candidates": sitemaps}

    logger.info("[cascade] layer-1 llms.txt: probing")
    llms_urls = fetch_llms_txt(url, **parser_kw)
    filtered_llms = filter_urls(llms_urls, url, depth)
    logger.info(
        f"[cascade] layer-1 llms.txt: raw={len(llms_urls)} in-scope={len(filtered_llms)}"
    )
    if len(filtered_llms) >= MIN_URLS_TO_CONSIDER_DISCOVERED:
        logger.info(
            f"[cascade] layer-1 llms.txt: WIN (>={MIN_URLS_TO_CONSIDER_DISCOVERED})"
        )
        return filtered_llms, "llms.txt"

    logger.info("[cascade] layer-2 sitemap.xml: probing")
    sitemap_urls = fetch_sitemap(url, **sitemap_kw)
    filtered_sitemap = filter_urls(sitemap_urls, url, depth)
    logger.info(
        f"[cascade] layer-2 sitemap: raw={len(sitemap_urls)} in-scope={len(filtered_sitemap)}"
    )
    if len(filtered_sitemap) >= MIN_URLS_TO_CONSIDER_DISCOVERED:
        logger.info(
            f"[cascade] layer-2 sitemap: WIN (>={MIN_URLS_TO_CONSIDER_DISCOVERED})"
        )
        return filtered_sitemap, "sitemap.xml"

    return [], "none"


_PLAYWRIGHT_MSG = ("httrack profile: Playwright fallback is not implemented yet "
                   "(planned); use --downloader wget")

def _httrack_defaults(ctx: click.Context) -> dict:
    """httrack-only params (help prefixed "[httrack]") -> click default; single source of truth."""
    return {p.name: p.default for p in ctx.command.params
            if (getattr(p, 'help', None) or '').startswith('[httrack]')}


_NUMERIC = ('connections', 'max_conn_rate', 'max_bandwidth', 'timeout', 'retries',
            'max_links', 'max_retry_after')


def _flag(name: str) -> str:
    return "--" + name.replace('_', '-')


def _build_policy(delay, policy_kw, from_config):
    """build_policy with failures reported in CLI terms; config-sourced values say so."""
    src = lambda k: " (from .dograpper.json)" if k in from_config else ""
    for k in _NUMERIC + ('delay',):
        v = delay if k == 'delay' else policy_kw[k]
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise click.UsageError(f"{_flag(k)} must be a number, got {v!r}{src(k)}")
    try:
        return build_policy(delay_ms=delay, **policy_kw)
    except (ValueError, TypeError) as e:
        msg = str(e).replace('delay_ms', 'delay')
        for k in _NUMERIC + ('delay',):
            if msg.startswith(k + ' '):
                raise click.UsageError(f"{_flag(k)}{msg[len(k):]}{src(k)}")
        raise click.UsageError(msg)


def _run_httrack(url, output, depth, delay, include_extensions, headless,
                 verbose, policy_kw, from_config=frozenset()) -> Tuple[int, int, List[str]]:
    """httrack profile: seeded fetch only. Returns (downloaded, skipped, report lines)."""
    warn_if_old_openssl()
    if headless:
        raise click.ClickException(_PLAYWRIGHT_MSG)
    policy = _build_policy(delay, policy_kw, from_config)
    fetcher = Fetcher(policy)
    discovered, winning_layer = _discover_urls(url, depth, fetcher)
    if not discovered:
        raise click.ClickException(
            "httrack profile: recursive crawl is not implemented yet (planned); "
            "use --downloader wget")
    logger.info(f"[cascade] httrack: fetching {len(discovered)} URLs from {winning_layer}")
    res = fetch_url_list(discovered, output, policy, include_extensions, fetcher=fetcher)
    if res.front_failed or not res.success:
        for line in format_report(res.report, verbose):
            click.echo(f"  {line}", err=True)
    if res.front_failed:
        raise click.ClickException(
            "httrack profile: the site refused or challenged every seed URL (likely bot "
            "protection). See the README section \"Downloader profiles\".")
    if not res.success:
        raise click.ClickException("httrack fetch failed.")
    if is_spa(output):
        raise click.ClickException(_PLAYWRIGHT_MSG)
    return len(res.files_downloaded), 0, format_report(res.report, verbose)


def _run_download_cascade(
    url: str,
    output: str,
    depth: int,
    delay: int,
    include_extensions: str,
    manifest_data,
    headless: bool,
) -> Tuple[int, int]:
    """Orchestrate the 4-layer cascade. Returns (downloaded, skipped) counts."""
    is_incremental = bool(manifest_data)

    # Layers 1+2 — authoritative URL discovery (always, even under --headless).
    discovered_urls, winning_layer = _discover_urls(url, depth)

    if discovered_urls:
        if headless:
            logger.info(
                f"[cascade] layer-4 playwright: hydrating {len(discovered_urls)} "
                f"seed URLs from {winning_layer}"
            )
            try:
                result = run_playwright_crawl(
                    url, output, depth, delay, include_extensions,
                    manifest_data, seed_urls=discovered_urls,
                )
            except RuntimeError as e:
                raise click.ClickException(str(e))
            if not result.success:
                raise click.ClickException("Playwright seeded crawl failed.")
            skipped = result.files_skipped
            downloaded = max(0, len(result.files_downloaded) - skipped)
            return downloaded, skipped

        logger.info(
            f"[cascade] layer-3 wget -i: fetching {len(discovered_urls)} URLs from {winning_layer}"
        )
        pre_snapshot = _snapshot_dir(output) if is_incremental else {}
        try:
            wget_res = run_wget_urls(
                discovered_urls, output, delay, include_extensions,
            )
        except RuntimeError as e:
            raise click.ClickException(str(e))
        if not wget_res.success:
            raise click.ClickException("wget -i failed.")

        # Sanity: if the fetched pages are empty shells, fall through to
        # playwright with the discovered URLs as seeds (v2 Critic layer-1
        # stale-URLs gap).
        if is_spa(output):
            logger.info(
                "[cascade] layer-4 playwright: SPA detected post-wget-i, "
                "re-hydrating seed URLs"
            )
            logger.info("SPA detected, falling back to playwright")
            try:
                result = run_playwright_crawl(
                    url, output, depth, delay, include_extensions,
                    manifest_data, seed_urls=discovered_urls,
                )
            except RuntimeError as e:
                raise click.ClickException(str(e))
            if not result.success:
                raise click.ClickException("Playwright seeded fallback failed.")
            skipped = result.files_skipped
            downloaded = max(0, len(result.files_downloaded) - skipped)
            return downloaded, skipped

        return _compute_stats(wget_res.files_downloaded, pre_snapshot, is_incremental)

    # No discovery — legacy fallback path.
    if headless:
        logger.info("[cascade] layer-4 playwright: no discovered URLs, direct crawl")
        try:
            result = run_playwright_crawl(
                url, output, depth, delay, include_extensions, manifest_data,
            )
        except RuntimeError as e:
            raise click.ClickException(str(e))
        if not result.success:
            raise click.ClickException("Playwright crawl failed.")
        skipped = result.files_skipped
        downloaded = max(0, len(result.files_downloaded) - skipped)
        return downloaded, skipped

    logger.info("[cascade] layer-3 wget --mirror: link-graph fallback")
    pre_snapshot = _snapshot_dir(output) if is_incremental else {}
    try:
        wget_res = run_wget_mirror(
            url, output, depth, delay, include_extensions,
            incremental=is_incremental,
        )
    except RuntimeError as e:
        raise click.ClickException(str(e))

    touched, unchanged = _compute_stats(
        wget_res.files_downloaded, pre_snapshot, is_incremental
    )

    html_count = sum(
        1 for p in wget_res.files_downloaded if p.lower().endswith((".html", ".htm"))
    )
    mirror_too_shallow = wget_res.success and html_count <= 1

    if wget_res.success and (is_spa(output) or mirror_too_shallow):
        if mirror_too_shallow and not is_spa(output):
            logger.info(
                f"[cascade] layer-4 playwright: --mirror yielded only {html_count} "
                f"HTML file(s) (likely client-rendered index)"
            )
        logger.info("SPA detected, falling back to playwright")
        logger.info("[cascade] layer-4 playwright: SPA detected after --mirror")
        try:
            result = run_playwright_crawl(
                url, output, depth, delay, include_extensions, manifest_data,
            )
        except RuntimeError as e:
            raise click.ClickException(str(e))
        if not result.success:
            raise click.ClickException("Playwright fallback crawl failed.")
        skipped = result.files_skipped
        downloaded = max(0, len(result.files_downloaded) - skipped)
        return downloaded, skipped

    return touched, unchanged


@click.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  dograpper download https://docs.rust-lang.org -o ./rust-docs\n"
        "  dograpper download https://react.dev --headless -o ./react-docs --delay 500\n"
        "  dograpper download https://docs.python.org/3/ -o ./py -d 3 --include-extensions html,md\n"
    )
)
@click.argument('url', type=str, required=True)
@click.option('--output', '-o', required=True, type=click.Path(),
              help="Destination directory for downloaded files")
@click.option('--depth', '-d', type=int, default=0, show_default=True,
              help="Maximum link depth to follow (0 = unlimited)")
@click.option('--headless', is_flag=True, default=False, show_default=True,
              help="Skip wget and crawl directly with Playwright (use for SPAs)")
@click.option('--delay', type=int, default=0, show_default=True,
              help="Interval between requests in ms (rate limiting)")
@click.option('--include-extensions', type=str, default="html,md,txt", show_default=True,
              help="Allowed extensions, comma-separated")
@click.option('--manifest', type=str, default=".dograpper-manifest.json", show_default=True,
              help="JSON cache file for incremental downloads")
@click.option('--downloader', type=click.Choice(['wget', 'httrack']), default='wget',
              show_default=True,
              help="Download backend: wget (default) or the httrack profile (pure-Python seeded fetch)")
@click.option('--user-agent', type=str, default=None,
              help="[httrack] User-Agent header (default: dograpper identifier)")
@click.option('--no-robots', is_flag=True, default=False,
              help="[httrack] Ignore robots.txt")
@click.option('--connections', type=click.IntRange(min=1), default=4, show_default=True,
              help="[httrack] Parallel connections (clamped to 8 unless --disable-security-limits)")
@click.option('--max-conn-rate', type=click.FloatRange(min=0, min_open=True), default=5.0,
              show_default=True,
              help="[httrack] Max connections opened per second")
@click.option('--max-bandwidth', type=click.IntRange(min=1), default=100000, show_default=True,
              help="[httrack] Max bandwidth in bytes/second")
@click.option('--timeout', type=click.FloatRange(min=0, min_open=True), default=120.0,
              show_default=True, help="[httrack] Per-request timeout in seconds")
@click.option('--retries', type=click.IntRange(min=0), default=2, show_default=True,
              help="[httrack] Retries per URL")
@click.option('--max-links', type=click.IntRange(min=1), default=100000, show_default=True,
              help="[httrack] Max URLs fetched per run")
@click.option('--max-retry-after', type=click.IntRange(min=0), default=60, show_default=True,
              help="[httrack] Max seconds honored from Retry-After / Crawl-delay")
@click.option('--disable-security-limits', is_flag=True, default=False,
              help="[httrack] Lift the connection, rate and bandwidth clamps")
@click.pass_context
def download(ctx: click.Context, url: str, output: str, depth: int, headless: bool, delay: int, include_extensions: str, manifest: str, downloader: str, user_agent, no_robots: bool, connections: int, max_conn_rate: float, max_bandwidth: int, timeout: float, retries: int, max_links: int, max_retry_after: int, disable_security_limits: bool):
    """Mirror a documentation site locally for offline processing.

    Discovers URLs via a 4-layer cascade: llms.txt → sitemap.xml → wget --mirror →
    Playwright (bounded hydration). Layers 1+2 run even with --headless so
    SPAs that publish authoritative indexes (Mintlify, Stripe, Anthropic) are
    handled correctly.

    Downloads are incremental via a JSON manifest.
    """
    ctx.ensure_object(dict)
    config_path = ctx.obj.get('CONFIG_PATH', '.dograpper.json')

    cli_params = {
        'output': output,
        'depth': depth,
        'headless': headless,
        'delay': delay,
        'include_extensions': include_extensions,
        'manifest': manifest,
        'downloader': downloader,
        'user_agent': user_agent,
        'no_robots': no_robots,
        'connections': connections,
        'max_conn_rate': max_conn_rate,
        'max_bandwidth': max_bandwidth,
        'timeout': timeout,
        'retries': retries,
        'max_links': max_links,
        'max_retry_after': max_retry_after,
        'disable_security_limits': disable_security_limits,
    }
    merged_params = load_config(config_path, 'download', cli_params, ctx)

    output = merged_params.get('output', output)
    depth = merged_params.get('depth', depth)
    headless = merged_params.get('headless', headless)
    delay = merged_params.get('delay', delay)
    include_extensions = _normalize_extensions(
        merged_params.get('include_extensions', include_extensions)
    )
    manifest_path = merged_params.get('manifest', manifest)

    downloader = merged_params.get('downloader', downloader)
    if downloader not in ('wget', 'httrack'):
        raise click.UsageError(
            f"invalid downloader {downloader!r}; allowed: wget, httrack")
    defaults = _httrack_defaults(ctx)
    httrack_params = {k: merged_params.get(k, d) for k, d in defaults.items()}
    report_lines: List[str] = []

    if downloader == 'wget':
        for k, d in defaults.items():
            if httrack_params[k] != d:
                raise click.UsageError(
                    f"--{k.replace('_', '-')} requires --downloader httrack")

    os.makedirs(output, exist_ok=True)
    manifest_data = load_manifest(manifest_path)

    if downloader == 'httrack':
        policy_kw = {k: v for k, v in httrack_params.items()
                     if k not in ('no_robots',)}
        policy_kw['obey_robots'] = not httrack_params['no_robots']
        files_downloaded, files_skipped, report_lines = _run_httrack(
            url, output, depth, delay, include_extensions, headless,
            bool(ctx.obj.get('VERBOSE')), policy_kw,
            frozenset(k for k in (*defaults, 'delay')
                      if not is_explicit_source(ctx.get_parameter_source(k))),
        )
    else:
        files_downloaded, files_skipped = _run_download_cascade(
            url, output, depth, delay, include_extensions, manifest_data, headless,
        )

    new_manifest = build_manifest(url, output)
    final_manifest = merge_manifests(manifest_data, new_manifest)
    save_manifest(final_manifest, manifest_path)

    total_size = sum(f.size_bytes for f in final_manifest.files.values())

    click.echo("Download complete:")
    click.echo(f"  URL:              {url}")
    click.echo(f"  Output:           {output}")
    click.echo(f"  Files downloaded: {files_downloaded}")
    click.echo(f"  Files skipped:    {files_skipped} (cached)")
    click.echo(f"  Total size:       {total_size / 1024 / 1024:.1f} MB")
    click.echo(f"  Manifest:         {manifest_path}")
    for line in report_lines:
        click.echo(f"  {line}")
