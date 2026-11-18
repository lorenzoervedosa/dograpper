"""Recursive crawl of the httrack profile, HTTrack's mirror loop (htscore.c, htsmirror.c).

From the start URL, links (links.py) are followed breadth-first within scope: the start
host, the start URL's directory (HTTrack -D; the implicit first rule +<host>/<dir>*),
--filter rules (the last match wins, never across hosts) and --depth link hops. A
redirect is not followed in place: its target is queued as a fresh link (htscore.c:1783)
and passes the same checks. Only clean 2xx responses are written (crawl.fetch_page), and
their links are rewritten once every name is known (-K0).

Determinism: requests run on up to policy.connections threads, but responses are handled
strictly in queue order on the calling thread, so the queue, the names (and their -N
suffixes), the files and the report never depend on which request finished first.
"""

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import unquote, urlsplit

from dograpper.lib.url_filter import UrlFilters
from dograpper.utils.atomic_write import atomic_write_bytes
from dograpper.utils.progress import ProgressReporter
from dograpper.utils.redact import redact_url

from .crawl import MAX_REDIRECTS, HttrackResult, fetch_page, relink
from .fetcher import Fetcher, same_host
from .links import css_links, page_links, url_key
from .naming import KNOWN_EXTS, PAGE_EXTS, NameRegistry
from .policy import NAVIGATION, FetchMeta, HttrackPolicy
from .report import RunReport

logger = logging.getLogger(__name__)

_UNCLASSIFIED = FetchMeta("", "no-cors", False)


@dataclass(frozen=True)
class _Entry:
    url: str
    hop: int                       # link hops from the start URL (a redirect adds none)
    referer: str | None = None
    meta: FetchMeta = NAVIGATION
    front: bool = False            # the start URL or a redirect target it led to
    redirects: int = 0


def _start_rule(url: str) -> UrlFilters:
    """HTTrack's implicit first rule, +<host>/<directory of url>* (htswizard.c), as
    wget_mirror.url_filter_args first wrote it: /docs/a.html -> /docs/, /docs -> /."""
    parts = urlsplit(url)
    directory = parts.path[:parts.path.rfind("/") + 1] or "/"
    return UrlFilters([f"+{parts.netloc.rpartition('@')[2]}{directory}*"])


def _skipped_by_extension(url: str, exts: set) -> bool:
    """--include-extensions before the request: an extension HTTrack knows as a type that is
    no page, and that the list leaves out, is not fetched (a page may come from any other)."""
    name = unquote(urlsplit(url).path).rsplit("/", 1)[-1]
    ext = os.path.splitext(name)[1].lower()
    return bool(exts) and ext in KNOWN_EXTS and ext not in PAGE_EXTS and ext not in exts


def mirror_site(url: str, output_dir: str, policy: HttrackPolicy, include_extensions: str, *,
                depth: int = 0, fetcher: Fetcher | None = None,
                filters: UrlFilters | None = None) -> HttrackResult:
    """Crawl from `url` into `output_dir`; `depth` caps link hops (0: unlimited) and
    policy.max_links the URLs queued (the report then says partial). The result maps each
    written file to the URL requested for it (preferring one that needed no redirect, then
    the smallest), and front_failed is set when the start URL, or the redirect chain it
    starts, ends without a page."""
    fetcher = fetcher or Fetcher(policy)
    names = NameRegistry(output_dir)
    exts = {"." + e.strip().lower().lstrip(".") for e in include_extensions.split(",") if e.strip()}
    report, lock = RunReport(), threading.Lock()
    scope = [_start_rule(url)]
    queue = [_Entry(url, 0, front=True)]
    entry_of = {url_key(url): url}       # url_key -> URL queued for it
    requested = {url_key(url): {url}}    # url_key -> URLs links asked for (not redirects)
    moved: dict[str, str] = {}           # url_key -> url_key of its redirect target
    saved: dict[str, str] = {}           # url_key -> file written from that URL
    pages: dict[str, str] = {}           # HTML file -> URL fetched, for the link rewrite
    progress = ProgressReporter("httrack crawl")
    state = {"bytes": 0, "front_ok": False, "front_failed": False}

    def outside(u: str) -> str | None:
        """Why `u` is out of scope ("host" | "cdn-cgi" | "rule" | "directory") or None."""
        if urlsplit(u).scheme not in ("http", "https") or not same_host(url, u):
            return "host"
        if urlsplit(u).path.startswith("/cdn-cgi/"):
            return "cdn-cgi"
        verdict = filters.decide(u) if filters is not None else None
        if verdict is False:
            return "rule"
        return "directory" if verdict is None and not scope[0].decide(u) else None

    def enqueue(u: str, *, hop: int, referer: str | None, meta: FetchMeta,
                front: bool = False, redirects: int = 0) -> str:
        """Queue `u` unless known or out of scope: "queued", "known" or "refused"."""
        k = url_key(u)
        if k in entry_of:
            return "known"
        entry_of[k] = u
        why = outside(u)
        if why == "directory" and front:  # deviation (spec 5.5): re-base, not an empty mirror
            logger.info("start URL redirected to %s; the crawl scope follows it",
                        redact_url(u))
            scope[0], why = _start_rule(u), None
        if why == "rule":
            return "refused"
        if why is not None:
            report.out_of_scope.append(redact_url(u))
            return "refused"
        if depth and hop > depth:
            return "refused"
        if _skipped_by_extension(u, exts):
            report.filtered.append(redact_url(u))
            return "refused"
        if len(queue) >= policy.max_links:
            report.partial = True
            return "refused"
        queue.append(_Entry(u, hop, referer, meta, front, redirects))
        return "queued"

    def work(entry: _Entry):
        return fetch_page(entry.url, fetcher, report, lock, None,
                          kind="linked" if entry.referer else "navigate",
                          referer=entry.referer, meta=entry.meta)

    def handle(entry: _Entry, outcome: str, final: str, res) -> None:
        safe, via = redact_url(entry.url), redact_url(entry.referer) if entry.referer else None
        if outcome == "moved":
            final = urlsplit(final)._replace(fragment="").geturl()  # htsmirror.c drops it
            moved[url_key(entry.url)] = url_key(final)
            if entry.redirects >= MAX_REDIRECTS:
                report.errors.append((safe, "too many redirects", via))
                state["front_failed"] |= entry.front
                return
            # the start URL's target has no initiator to compare with: no fetch metadata
            got = enqueue(final, hop=entry.hop, referer=entry.referer,
                          meta=_UNCLASSIFIED if entry.front else entry.meta,
                          front=entry.front, redirects=entry.redirects + 1)
            state["front_failed"] |= entry.front and got != "queued"
            return
        if outcome != "ok":
            state["front_failed"] |= entry.front
            return
        state["front_ok"] |= entry.front
        ctype = res.headers.get("content-type")
        mime = (ctype or "").split(";")[0].strip().lower()
        if mime == "text/html":
            links = page_links(res.body, entry.url, frame=entry.meta.dest,
                               robots=policy.obey_robots)
        elif mime == "text/css":
            links = css_links(res.body, entry.url)
        else:
            links = []
        # second copy of crawl.fetch_url_list's write(): name, --include-extensions, write
        path = names.assign(entry.url, ctype)
        if path is None:
            report.errors.append((safe, "unsafe local path", via))
        elif exts and os.path.splitext(path)[1].lower() not in exts:
            report.filtered.append(safe)
        else:
            try:
                atomic_write_bytes(path, res.body)
            except OSError as exc:  # e.g. file/dir conflict or disk full: recorded, run continues
                report.errors.append((safe, f"write failed: {exc}", via))
            else:
                saved[url_key(entry.url)] = path
                state["bytes"] += len(res.body)
                if mime == "text/html":
                    pages[path] = entry.url
        for link in links:
            got = enqueue(link.url, hop=entry.hop + 1, referer=entry.url, meta=link.meta)
            if got != "refused":
                requested.setdefault(url_key(link.url), set()).add(entry_of[url_key(link.url)])

    window = 2 * policy.connections  # responses held at once stay bounded
    with ThreadPoolExecutor(max_workers=policy.connections) as pool:
        futures: dict[int, object] = {}
        done = 0
        while True:
            while len(futures) < window and done + len(futures) < len(queue):
                i = done + len(futures)
                futures[i] = pool.submit(work, queue[i])
            if done == len(queue):
                break
            entry = queue[done]
            result = futures.pop(done).result()  # re-raises a worker's exception
            with lock:  # workers record into the same report
                handle(entry, *result)
            done += 1
            progress.update(done=len(saved), size_bytes=state["bytes"],
                            queued=len(queue) - done, last_url=entry.url)
    progress.finish()

    def file_of(k: str) -> str | None:
        hops = set()
        while k not in saved and k in moved and k not in hops:
            hops.add(k)
            k = moved[k]
        return saved.get(k)

    local = {k: f for k in (*saved, *moved) if (f := file_of(k))}
    relink(pages, local, report)
    chosen: dict[str, tuple[bool, str]] = {}
    for k, asked in requested.items():
        if (f := file_of(k)) is not None:
            for u in asked:
                cand = (k not in saved, u)  # reached through a redirect, URL requested
                chosen[f] = min(chosen[f], cand) if f in chosen else cand

    report.challenged.sort()
    report.robots_blocked.sort()
    report.out_of_scope.sort()
    report.filtered.sort()
    report.errors.sort(key=lambda e: (e[0], e[1]))
    files = sorted(saved.values())
    front_failed = state["front_failed"] and not state["front_ok"]
    return HttrackResult(bool(files), files, 0, report, front_failed,
                         {f: u for f, (_, u) in sorted(chosen.items())})
