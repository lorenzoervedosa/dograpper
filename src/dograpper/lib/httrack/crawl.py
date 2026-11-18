"""Seeded-list fetch for the httrack profile: fetch each URL, write only clean 2xx bodies."""

import logging
import os
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

from dograpper.lib.url_filter import UrlFilters
from dograpper.utils.atomic_write import atomic_write_bytes
from dograpper.utils.progress import ProgressReporter
from dograpper.utils.redact import redact_url

from .escape import request_target
from .fetcher import REDIRECTS, Fetcher, FetchResult, same_host
from .links import rewrite_links
from .naming import NameRegistry
from .policy import NAVIGATION, FetchMeta, HttrackPolicy
from .report import RunReport

logger = logging.getLogger(__name__)

MAX_REDIRECTS = 5


@dataclass
class HttrackResult:
    success: bool
    files_downloaded: list[str]
    files_skipped: int
    report: RunReport
    front_failed: bool
    urls: dict[str, str] = field(default_factory=dict)  # written file -> seed URL requested


def _count(report: RunReport, status: int | None, error: bool) -> None:
    key = "error" if error or status is None else f"{status // 100}xx"
    report.status_counts[key] = report.status_counts.get(key, 0) + 1


def fetch_page(url: str, fetcher: Fetcher, report: RunReport, lock: threading.Lock,
               redirect_ok: Callable[[str, str], bool] | None, *, kind: str = "navigate",
               referer: str | None = None,
               meta: FetchMeta = NAVIGATION) -> tuple[str, str, FetchResult | None]:
    """GET `url` for every fetch path: /cdn-cgi/ is never requested, robots.txt is checked
    before each hop, and a redirect is followed (at most MAX_REDIRECTS) only when
    `redirect_ok(url, target)`, called under `lock`, accepts the target. Return ("ok",
    final URL, result) for a 2xx that is no challenge, else ("scoped" | "refused", URL,
    None) with the cause recorded in `report` (an error names `referer`). Without
    `redirect_ok` a redirect is not followed: ("moved", target, result)."""
    via, hops = (redact_url(referer) if referer else None), 0
    while True:
        safe = redact_url(url)
        try:
            parts = urlsplit(url)
        except ValueError:
            with lock:
                report.errors.append((safe, "malformed URL", via))
            return "refused", url, None
        if parts.path.startswith("/cdn-cgi/"):
            with lock:
                report.out_of_scope.append(safe)
            return "scoped", url, None
        try:
            target = request_target(parts)  # robots sees exactly what goes on the wire
        except ValueError:
            with lock:
                report.errors.append((safe, "malformed URL", via))
            return "refused", url, None
        if not fetcher.robots_for(f"{parts.scheme}://{parts.netloc}").allowed(target):
            with lock:
                report.robots_blocked.append(safe)
            logger.info("robots.txt disallows %s", safe)
            return "refused", url, None
        res = fetcher.get(url, kind=kind, referer=referer, meta=meta)
        # the fetcher keeps a 3xx's Location even when its body fails to decode
        redirect = bool(res.status in REDIRECTS and res.location)
        with lock:
            report.retried += max(res.attempts - 1, 0)
            _count(report, res.status, res.error is not None and not redirect)
            if res.error is not None and not redirect:
                report.errors.append((safe, res.error, via))
                return "refused", url, None
            if redirect:
                try:
                    nxt = urljoin(url, res.location)
                except ValueError:
                    report.errors.append((safe, "malformed redirect Location", via))
                    return "refused", url, None
                if redirect_ok is None:
                    return "moved", nxt, res
                if not redirect_ok(url, nxt):
                    return "scoped", url, None
                if hops >= MAX_REDIRECTS:
                    report.errors.append((safe, "too many redirects", via))
                    return "refused", url, None
                url, hops = nxt, hops + 1
                continue
            if res.challenged:
                report.challenged.append(safe)
                return "refused", url, None
            if not (res.status and 200 <= res.status < 300):
                report.errors.append((safe, f"HTTP {res.status}", via))
                return "refused", url, None
        return "ok", url, res


def relink(pages: Mapping[str, str], local: Mapping[str, str], report: RunReport) -> None:
    """Rewrite the links of the saved HTML `pages` (file -> URL it was fetched from) as
    HTTrack -K0 does, `local` mapping links.url_key() to saved files; a failure is an error
    of the report, the page keeps its links."""
    for path, url in pages.items():
        try:
            with open(path, "rb") as f:
                body = f.read()
            new = rewrite_links(body, url, path, local)
            if new is not body:
                atomic_write_bytes(path, new)
        except OSError as exc:
            report.errors.append((redact_url(url), f"link rewrite failed: {exc}", None))


def fetch_url_list(urls: list[str], output_dir: str, policy: HttrackPolicy,
                   include_extensions: str, *, fetcher: Fetcher | None = None,
                   filters: UrlFilters | None = None) -> HttrackResult:
    """Fetch `urls` (already scoped and filtered); a redirect target goes through the
    same-host check and `filters` (refusals land in `filters.excluded`) before its GET."""
    fetcher = fetcher or Fetcher(policy)
    names = NameRegistry(output_dir)
    exts = {"." + e.strip().lower().lstrip(".") for e in include_extensions.split(",") if e.strip()}
    report, lock, written = RunReport(), threading.Lock(), set()
    # written file -> (redirected?, seed): of several seeds reaching one file, the one
    # that needed no redirect, else the smallest, whichever thread wrote first
    requested: dict[str, tuple[bool, str]] = {}
    seeds = list(dict.fromkeys(urls))
    if len(seeds) > policy.max_links:
        seeds, report.partial = seeds[:policy.max_links], True
    refused = [0]  # seeds that ended challenged, refused, errored or robots-blocked
    finished, size = [0], [0]  # seeds done, bytes written
    progress = ProgressReporter("httrack", total=len(seeds))

    def redirect_ok(url: str, nxt: str) -> bool:
        if not same_host(url, nxt):
            report.out_of_scope.append(redact_url(nxt))
            return False
        return filters is None or filters.decide(nxt) is not False

    def fetch_one(url: str) -> str:
        """Return "refused", "scoped" (skipped by scope/filter) or "written"."""
        outcome, final, res = fetch_page(url, fetcher, report, lock, redirect_ok)
        return write(final, url, redact_url(final), res) if outcome == "ok" else outcome

    def write(url: str, seed: str, safe: str, res) -> str:
        path = names.assign(url, res.headers.get("content-type"))
        if path is None:
            with lock:
                report.errors.append((safe, "unsafe local path", None))
            return "refused"
        if exts and os.path.splitext(path)[1].lower() not in exts:
            with lock:
                report.filtered.append(safe)
            return "scoped"
        key = (url != seed, seed)
        with lock:
            if path in written:  # same final URL reached from several seeds
                requested[path] = min(requested[path], key)
                return "written"
            written.add(path)
            requested[path] = key
        try:
            atomic_write_bytes(path, res.body)
        except OSError as exc:  # e.g. file/dir conflict or disk full: recorded, run continues
            with lock:
                written.remove(path)
                del requested[path]
                report.errors.append((safe, f"write failed: {exc}", None))
            return "refused"
        with lock:
            size[0] += len(res.body)
        return "written"

    def run(seed: str) -> None:
        if fetch_one(seed) == "refused":
            with lock:
                refused[0] += 1
        with lock:
            finished[0] += 1
            progress.update(done=finished[0], size_bytes=size[0])

    with ThreadPoolExecutor(max_workers=max(policy.connections, 1)) as pool:
        list(pool.map(run, seeds))  # list() re-raises any worker exception
    progress.finish()

    report.challenged.sort()
    report.robots_blocked.sort()
    report.out_of_scope.sort()
    report.filtered.sort()
    report.errors.sort(key=lambda e: (e[0], e[1]))
    files = sorted(written)
    front_failed = not files and bool(seeds) and refused[0] == len(seeds)
    chosen = {path: seed for path, (_, seed) in requested.items()}
    return HttrackResult(bool(files), files, 0, report, front_failed, chosen)
