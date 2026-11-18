"""Seeded-list fetch for the httrack profile: fetch each URL, write only clean 2xx bodies."""

import logging
import os
import re
import threading
from collections.abc import Callable, Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import NamedTuple
from urllib.parse import urljoin, urlsplit

from dograpper.lib.manifest import RECORD_FIELDS, Manifest
from dograpper.lib.url_filter import UrlFilters
from dograpper.utils.atomic_write import atomic_write_bytes
from dograpper.utils.portable_names import resolve_under
from dograpper.utils.progress import ProgressReporter
from dograpper.utils.redact import redact_url

from .escape import request_target
from .fetcher import REDIRECTS, Fetcher, FetchResult, same_host
from .links import rewrite_links, url_key
from .naming import NameRegistry, no_page
from .policy import (NAVIGATION, SITES, FetchMeta, HttrackPolicy, conditional_headers,
                     response_validators, site_of)
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
    kept: list[str] = field(default_factory=list)  # files an update kept as they were
    records: dict[str, dict] = field(default_factory=dict)  # file -> manifest RECORD_FIELDS


class Previous(NamedTuple):
    """A file of the previous run that this one revalidates (HTTrack update mode)."""
    url: str                                 # the URL recorded for it
    path: str                                # where it is saved (real path)
    validators: tuple[tuple[str, str], ...]  # policy.conditional_headers
    redirected: bool                         # its URL reached it through a redirect
    record: dict                             # its manifest RECORD_FIELDS, kept with it


def _named(name: str | None, path: str) -> bool:
    """`path` is `name` or the -N suffixed name a collision gives it (claim_unique)."""
    if name is None:
        return False
    stem, ext = os.path.splitext(name)
    return re.fullmatch(re.escape(stem) + r"(-[0-9]+)?" + re.escape(ext), path) is not None


def previous_files(previous: Manifest | None, names: NameRegistry,
                   output_dir: str) -> dict[str, Previous]:
    """url_key of the recorded URL -> Previous, for each file `previous` recorded from a
    200 with a validator and still on disk, not empty: HTTrack revalidates a cached 200
    only (htsback.c:2557-2607; 203 is stored as 200, 4224-4226) and fetches a file erased
    or emptied since in full (2414-2492). A file not named as its URL would be (an edited
    manifest) is left out, so a manifest never chooses where a page is written; one reached
    through a redirect is checked against the hop that reaches it (sends)."""
    root, out = os.path.realpath(output_dir), {}
    for key, e in sorted((previous.files if previous else {}).items()):
        validators = conditional_headers(e.etag, e.last_modified)
        path = resolve_under(root, e.local_path or key)
        if not (e.url and e.status in (200, 203) and validators and path
                and os.path.isfile(path) and os.path.getsize(path) > 0):
            continue
        try:
            k = url_key(e.url)
            if not e.redirected and not _named(names.name_of(e.url, e.content_type), path):
                continue
        except ValueError:  # an unusable URL (an edited manifest)
            continue
        out.setdefault(k, Previous(e.url, path, validators, bool(e.redirected),
                                   {f: getattr(e, f) for f in RECORD_FIELDS}))
    return out


def reserve_names(names: NameRegistry, prev: Mapping[str, Previous]) -> None:
    """Keep the names of the files an update may leave as they are: only the URL each was
    saved from gets it back (NameRegistry.reserve)."""
    for p in prev.values():
        names.reserve(p.path)


def sends(p: Previous | None, url: str, redirected: bool, names: NameRegistry | None) -> bool:
    """Whether `url` (reached through a redirect or not) is where `p`'s file came from: its
    request carries p's validators and its answer takes p's name. A file recorded through a
    redirect is the hop whose name is exactly that file's; a chain leading elsewhere now
    gets plain requests, as HTTrack has no cache entry for its new target."""
    if p is None or redirected != p.redirected:
        return False
    return not p.redirected or names.name_of(url, p.record["content_type"]) == p.path


def record_of(res: FetchResult) -> dict:
    """RECORD_FIELDS of the 2xx response `res` a file is saved from ("redirected" aside)."""
    etag, last_modified = response_validators(res.headers)
    return {"status": res.status, "content_type": res.headers.get("content-type"),
            "etag": etag, "last_modified": last_modified}


def _count(report: RunReport, status: int | None, error: bool) -> None:
    key = "error" if error or status is None else f"{status // 100}xx"
    report.status_counts[key] = report.status_counts.get(key, 0) + 1


def moved_request(url: str, referer: str | None, meta: FetchMeta, target: str, *, front: bool,
                  initiator: str | None) -> tuple[str | None, FetchMeta]:
    """Referer and fetch metadata of `target`, where `url` (requested with `referer` and
    `meta`) redirected, as htsmirror.c hts_mirror_check_moved sends it. A target with a
    known non-page extension, or one saved under the same name, is a fresh link with the
    moved link's parent (htsmirror.c:190-261); any other becomes the link of a stub page
    standing for the moved URL (279-324), so that URL is its Referer (its precedent,
    htscore.c:3424-3426). Both keep the moved link's metadata, with the worst Sec-Fetch-Site
    of the chain (htsfetch.c:452-465); a start URL's (`front`) "none" stays. `initiator` is
    the page whose link began the chain."""
    same_name = url_key(url).casefold() == url_key(target).casefold()  # #159
    referer = referer if no_page(target) or same_name else url
    if front or not meta.dest:
        site = "none" if front else meta.site
    else:
        hops = (meta.site or site_of(initiator, url), site_of(initiator, target))
        site = max(hops, key=SITES.index)
    return referer, meta._replace(site=site)


def fetch_page(url: str, fetcher: Fetcher, report: RunReport, lock: threading.Lock,
               redirect_ok: Callable[[str, str], bool] | None, *, kind: str = "navigate",
               referer: str | None = None, meta: FetchMeta = NAVIGATION,
               prev: Previous | None = None,
               names: NameRegistry | None = None) -> tuple[str, str, FetchResult | None]:
    """GET `url` for every fetch path: /cdn-cgi/ is never requested, robots.txt is checked
    before each hop, and a redirect is followed (at most MAX_REDIRECTS) only when
    `redirect_ok(url, target)`, called under `lock`, accepts the target; `url` is then a
    start URL, and each target is requested as moved_request() says. Return ("ok", final
    URL, result) for a 2xx that is no challenge, else ("scoped" | "refused", URL, None)
    with the cause recorded in `report` (an error names the request's referer). Without
    `redirect_ok` a redirect is not followed: ("moved", target, result).

    With `prev`, the file of the previous run this URL leads to, its validators go on the
    request of the hop it came from (sends; `names` checks a redirected one), and any answer
    but a 2xx or a redirect keeps that file: ("kept", URL, result), as HTTrack masks it as a
    304 (htsback.c:4266-4280, 4437-4494); a challenge is also listed as challenged. A failed
    transfer is an error that keeps it too (htsback.c:1307-1321): ("kept", URL, result)
    with result.error set."""
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
        sent = prev.validators if sends(prev, url, hops > 0, names) else ()
        res = fetcher.get(url, kind=kind, referer=referer, meta=meta,
                          **({"validators": sent} if sent else {}))
        # the fetcher keeps a 3xx's Location even when its body fails to decode
        redirect = bool(res.status in REDIRECTS and res.location)
        with lock:
            report.retried += max(res.attempts - 1, 0)
            _count(report, res.status, res.error is not None and not redirect)
            if res.error is not None and not redirect:
                report.errors.append((safe, res.error, via))
                return ("kept", url, res) if sent else ("refused", url, None)
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
                referer, meta = moved_request(url, referer, meta, nxt, front=True,
                                              initiator=None)
                via = redact_url(referer) if referer else None
                url, hops = nxt, hops + 1
                continue
            if sent and (res.challenged or res.status == 304 or not (
                    200 <= res.status < 300 or res.status in REDIRECTS)):
                if res.challenged:
                    report.challenged.append(safe)
                elif res.status == 304:
                    report.not_modified += 1
                else:
                    report.kept.append((safe, f"HTTP {res.status}"))
                return "kept", url, res
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
                   filters: UrlFilters | None = None,
                   previous: Manifest | None = None) -> HttrackResult:
    """Fetch `urls` (already scoped and filtered); a redirect target goes through the
    same-host check and `filters` (refusals land in `filters.excluded`) before its GET.
    The links of the saved HTML pages are then rewritten (relink), as wget -i
    --convert-links does. With the `previous` run's manifest, its files are revalidated
    (fetch_page) and a kept one is left byte-identical, relink included."""
    fetcher = fetcher or Fetcher(policy)
    names = NameRegistry(output_dir)
    prev = previous_files(previous, names, output_dir)
    reserve_names(names, prev)
    kept: set[str] = set()
    fields: dict[str, dict] = {}  # file -> record_of() its response, or its previous record
    exts = {"." + e.strip().lower().lstrip(".") for e in include_extensions.split(",") if e.strip()}
    report, lock, written = RunReport(), threading.Lock(), set()
    # written file -> (redirected?, seed): of several seeds reaching one file, the one
    # that needed no redirect, else the smallest, whichever thread wrote first
    requested: dict[str, tuple[bool, str]] = {}
    pages: dict[str, str] = {}  # written HTML file -> URL it came from, for relink
    reached: list[tuple[str, str]] = []  # (seed or final URL, file it reached)
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
        """Return "refused", "scoped" (skipped by scope/filter), "written" or "kept"."""
        try:
            p = prev.get(url_key(url))
        except ValueError:  # a malformed URL: fetch_page records it
            p = None
        outcome, final, res = fetch_page(url, fetcher, report, lock, redirect_ok, prev=p,
                                         names=names)
        if outcome == "kept":
            return keep(final, url, p, res.challenged or res.error is not None)
        if outcome != "ok":
            return outcome
        mine = p.path if sends(p, final, final != url, names) else None
        return write(final, url, redact_url(final), res, mine)

    def keep(url: str, seed: str, p: Previous, failed: bool) -> str:
        names.assign(url, p.record["content_type"], prefer=p.path)
        key = (url != seed, seed)
        with lock:
            requested[p.path] = min(requested[p.path], key) if p.path in requested else key
            reached.extend(((url, p.path), (seed, p.path)))
            if p.path not in written:
                kept.add(p.path)
                fields[p.path] = p.record
        return "refused" if failed else "kept"  # still fails the front (spec 5.4, 5.8)

    def write(url: str, seed: str, safe: str, res, mine: str | None = None) -> str:
        path = names.assign(url, res.headers.get("content-type"), prefer=mine)
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
            if path in written or path in kept:  # same final URL reached from several seeds
                requested[path] = min(requested[path], key)
                reached.append((seed, path))
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
            fields[path] = record_of(res)
            reached.extend(((url, path), (seed, path)))
            if (res.headers.get("content-type") or "").split(";")[0].strip().lower() == "text/html":
                pages[path] = url
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

    relink(pages, {url_key(u): p for u, p in reached if p in written or p in kept}, report)
    report.challenged.sort()
    report.robots_blocked.sort()
    report.out_of_scope.sort()
    report.filtered.sort()
    report.kept.sort()
    report.errors.sort(key=lambda e: (e[0], e[1]))
    files = sorted(written)
    front_failed = not files and bool(seeds) and refused[0] == len(seeds)
    chosen = {path: seed for path, (_, seed) in requested.items()}
    records = {path: {**fields[path], "redirected": r} for path, (r, _) in requested.items()}
    return HttrackResult(bool(files or kept), files, len(kept), report, front_failed, chosen,
                         sorted(kept), records)
