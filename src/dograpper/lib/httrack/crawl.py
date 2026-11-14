"""Seeded-list fetch for the httrack profile: fetch each URL, write only clean 2xx bodies."""

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

from dograpper.utils.atomic_write import atomic_write_bytes
from dograpper.utils.redact import redact_url

from .fetcher import REDIRECTS, Fetcher
from .naming import NameRegistry
from .policy import HttrackPolicy
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


def _same_host(a: str, b: str) -> bool:
    try:
        return urlsplit(a).hostname == urlsplit(b).hostname
    except ValueError:
        return False


def fetch_url_list(urls: list[str], output_dir: str, policy: HttrackPolicy,
                   include_extensions: str, *, fetcher: Fetcher | None = None) -> HttrackResult:
    fetcher = fetcher or Fetcher(policy)
    names = NameRegistry(output_dir)
    exts = {"." + e.strip().lower().lstrip(".") for e in include_extensions.split(",") if e.strip()}
    report, lock, written = RunReport(), threading.Lock(), []
    seeds = list(dict.fromkeys(urls))
    if len(seeds) > policy.max_links:
        seeds, report.partial = seeds[:policy.max_links], True
    refused = [0]  # seeds that ended challenged, refused, errored or robots-blocked

    def count(status: int | None, error: bool) -> None:
        key = "error" if error or status is None else f"{status // 100}xx"
        report.status_counts[key] = report.status_counts.get(key, 0) + 1

    def fetch_one(url: str) -> str:
        """Return "refused", "scoped" (skipped by scope/filter) or "written"."""
        hops = 0
        while True:
            safe = redact_url(url)
            try:
                parts = urlsplit(url)
            except ValueError:
                with lock:
                    report.errors.append((safe, "malformed URL", None))
                return "refused"
            if parts.path.startswith("/cdn-cgi/"):
                with lock:
                    report.out_of_scope.append(safe)
                return "scoped"
            target = (parts.path or "/") + (f"?{parts.query}" if parts.query else "")
            if not fetcher.robots_for(f"{parts.scheme}://{parts.netloc}").allowed(target):
                with lock:
                    report.robots_blocked.append(safe)
                logger.info("robots.txt disallows %s", safe)
                return "refused"
            res = fetcher.get(url, kind="navigate")
            with lock:
                report.retried += max(res.attempts - 1, 0)
                count(res.status, res.error is not None)
                if res.error is not None:
                    report.errors.append((safe, res.error, None))
                    return "refused"
                if res.status in REDIRECTS and res.location:
                    try:
                        nxt = urljoin(url, res.location)
                    except ValueError:
                        report.errors.append((safe, "malformed redirect Location", None))
                        return "refused"
                    if not _same_host(url, nxt):
                        report.out_of_scope.append(redact_url(nxt))
                        return "scoped"
                    if hops >= MAX_REDIRECTS:
                        report.errors.append((safe, "too many redirects", None))
                        return "refused"
                    url, hops = nxt, hops + 1
                    continue
                if res.challenged:
                    report.challenged.append(safe)
                    return "refused"
                if not (res.status and 200 <= res.status < 300):
                    report.errors.append((safe, f"HTTP {res.status}", None))
                    return "refused"
            return write(url, safe, res)

    def write(url: str, safe: str, res) -> str:
        path = names.assign(url, res.headers.get("content-type"))
        if path is None:
            with lock:
                report.errors.append((safe, "unsafe local path", None))
            return "refused"
        if exts and os.path.splitext(path)[1].lower() not in exts:
            with lock:
                report.filtered.append(safe)
            return "scoped"
        with lock:
            if path in written:  # same final URL reached from several seeds
                return "written"
            written.append(path)
        try:
            atomic_write_bytes(path, res.body)
        except OSError as exc:  # e.g. file/dir conflict or disk full: recorded, run continues
            with lock:
                written.remove(path)
                report.errors.append((safe, f"write failed: {exc}", None))
            return "refused"
        return "written"

    def run(seed: str) -> None:
        if fetch_one(seed) == "refused":
            with lock:
                refused[0] += 1

    with ThreadPoolExecutor(max_workers=max(policy.connections, 1)) as pool:
        list(pool.map(run, seeds))  # list() re-raises any worker exception

    report.challenged.sort()
    report.robots_blocked.sort()
    report.out_of_scope.sort()
    report.filtered.sort()
    report.errors.sort(key=lambda e: (e[0], e[1]))
    files = sorted(written)
    front_failed = not files and bool(seeds) and refused[0] == len(seeds)
    return HttrackResult(bool(files), files, 0, report, front_failed)
