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

from dograpper.lib.manifest import Manifest
from dograpper.lib.url_filter import UrlFilters
from dograpper.utils.progress import ProgressReporter
from dograpper.utils.redact import redact_url

from .changes import Changes
from .crawl import (MAX_REDIRECTS, HttrackResult, KeptResponses, Previous, extension_set, fetch_page,
                    moved_request, previous_files, record_of, relink, reserve_names, save_file,
                    sends, stamp, uncached)
from .fetcher import Fetcher, same_host
from .links import JS_MIMES, css_links, page_links, script_links, url_key
from .naming import NameRegistry, mime_type, no_page, url_extension
from .policy import NAVIGATION, FetchMeta, HttrackPolicy
from .report import RunReport

logger = logging.getLogger(__name__)

@dataclass(frozen=True)
class _Entry:
    url: str
    hop: int                       # link hops from the start URL (a redirect adds none)
    referer: str | None = None
    meta: FetchMeta = NAVIGATION
    front: bool = False            # the start URL or a redirect target it led to
    redirects: int = 0
    initiator: str | None = None   # page whose link began the chain (Sec-Fetch-Site)
    prev: Previous | None = None   # update: the previous run's file this request revalidates
    carry: Previous | None = None  # update: the file a redirect of this URL leads to


def _revalidates(own: Previous | None, carried: Previous | None, mine: bool) -> tuple:
    """(prev, carry) of an _Entry: its own record, whose validators go on the hop after the
    redirect it was recorded through, else the record its redirect chain carried, when
    this hop is the one whose name is that file's (`mine`, crawl.sends)."""
    if own is not None:
        return own, (own if own.redirected else None)
    return (carried._replace(redirected=False) if carried and mine else None), carried


_KEPT_ROOT = "http://kept.invalid/"  # output_dir as a URL, to resolve a kept page's own links


def _kept_links(read, url: str, path: str, root: str, url_of: dict[str, str],
                page: str | None = None, page_path: str | None = None) -> list:
    """Links of the file `url` kept from the previous run at `path`, which HTTrack
    re-parses from its cache (htsback.c:4437-4494); `read(base, page base)` scans it (a
    script loaded by `page`, saved at `page_path`, takes that page's base). relink() made
    its links to saved files relative paths: one that resolves, against the file's own
    path under `root` (a script's, against its page's), to a file there maps back through
    the previous manifest (`url_of`: local path -> URL recorded), and is not followed when
    no URL was recorded. Any other link (absolute, or one relink leaves as written)
    resolves against `url` (or `page`). Both readings come from the same scan, so they pair
    up one to one."""
    def local(p: str) -> str:  # as links._local_ref writes a saved file's name
        return _KEPT_ROOT + os.path.relpath(p, root).replace(os.sep, "/").replace(
            "%", "%25").replace("#", "%23")
    links = []
    for real, link in zip(read(url, page or url), read(local(path), local(page_path or path)),
                          strict=True):
        # unquote: a scan's rewritten link is percent-encoded whole (links._uri_utf)
        name = unquote(urlsplit(link.url).path[1:]) if link.url.startswith(_KEPT_ROOT) else None
        if name is not None and os.path.isfile(os.path.join(root, name)):
            if name in url_of:
                links.append(real._replace(url=url_of[name]))
        else:
            links.append(real)
    return links


def start_rule(url: str) -> UrlFilters:
    """HTTrack's implicit first rule, +<host>/<directory of url>* (htswizard.c), as
    wget_mirror.url_filter_args first wrote it: /docs/a.html -> /docs/, /docs -> /."""
    parts = urlsplit(url)
    directory = parts.path[:parts.path.rfind("/") + 1] or "/"
    return UrlFilters([f"+{parts.netloc.rpartition('@')[2]}{directory}*"])


def outside(u: str, start: str, rule: UrlFilters, filters: UrlFilters | None) -> str | None:
    """Why `u` is out of the crawl scope of `start` ("host" | "cdn-cgi" | "rule" |
    "directory") or None: the start host, never /cdn-cgi/, then --filter, whose verdict
    beats `rule` (start_rule of the start URL, or of where it was re-based)."""
    if urlsplit(u).scheme not in ("http", "https") or not same_host(start, u):
        return "host"
    if urlsplit(u).path.startswith("/cdn-cgi/"):
        return "cdn-cgi"
    verdict = filters.decide(u) if filters is not None else None
    if verdict is False:
        return "rule"
    return "directory" if verdict is None and not rule.decide(u) else None


def rescope(u: str, start: str, rule: UrlFilters, filters: UrlFilters | None,
            front: bool) -> tuple[str | None, UrlFilters]:
    """outside() for a crawl whose scope `rule` follows its start URL: when the start's own
    redirect chain (`front`) leaves the directory, the scope is re-based on the target, not
    an empty mirror (deviation, spec 5.5). Returns (why, the rule from now on)."""
    why = outside(u, start, rule, filters)
    if why == "directory" and front:
        logger.info("start URL redirected to %s; the crawl scope follows it", redact_url(u))
        return None, start_rule(u)
    return why, rule


def skipped_by_extension(url: str, exts: set) -> bool:
    """--include-extensions before the request: an extension HTTrack knows as a type that is
    no page, and that the list leaves out, is not fetched (a page may come from any other)."""
    return bool(exts) and no_page(url) and url_extension(url) not in exts


def mirror_site(url: str, output_dir: str, policy: HttrackPolicy, include_extensions: str, *,
                depth: int = 0, fetcher: Fetcher | None = None,
                filters: UrlFilters | None = None,
                previous: Manifest | None = None,
                responses: KeptResponses | None = None) -> HttrackResult:
    """Crawl from `url` into `output_dir`; `depth` caps link hops (0: unlimited) and
    policy.max_links the URLs queued (the report then says partial). The result maps each
    written file to the URL requested for it (preferring one that needed no redirect, then
    the smallest), and front_failed is set when the start URL, or the redirect chain it
    starts, ends without a page. With the `previous` run's manifest its files are
    revalidated (crawl.fetch_page); a kept file is left byte-identical and the links of a
    kept page, stylesheet or script are followed from that copy (_kept_links)."""
    fetcher = fetcher or Fetcher(policy)
    names = NameRegistry(output_dir)
    prev = previous_files(previous, names, output_dir, policy.cache, policy.do_not_recatch)
    changes = Changes(output_dir, previous, policy.cache) if policy.changes else None
    reserve_names(names, prev)
    url_of = {e.local_path or k: e.url for k, e in (previous.files if previous else {}).items()
              if e.url}
    kept: set[str] = set()
    fields: dict[str, dict] = {}  # file -> record_of() its response, or its previous record
    exts = extension_set(include_extensions)
    report, lock = RunReport(), threading.Lock()
    scope = [start_rule(url)]
    own, carry = _revalidates(prev.get(url_key(url)), None, False)
    queue = [_Entry(url, 0, front=True, prev=own, carry=carry)]
    entry_of = {url_key(url): url}       # url_key -> URL queued for it
    requested = {url_key(url): {url}}    # url_key -> URLs links asked for (not redirects)
    moved: dict[str, str] = {}           # url_key -> url_key of its redirect target
    saved: dict[str, str] = {}           # url_key -> file written from that URL
    pages: dict[str, str] = {}           # HTML file -> URL fetched, for the link rewrite
    scripts: dict[str, tuple] = {}       # stylesheet or script -> relink's (URL, page, css?)
    progress = ProgressReporter("httrack crawl")
    state = {"bytes": 0, "front_ok": False, "front_failed": False}

    def enqueue(u: str, *, hop: int, referer: str | None, meta: FetchMeta,
                front: bool = False, redirects: int = 0, initiator: str | None = None,
                carried: Previous | None = None) -> str:
        """Queue `u` unless known or out of scope: "queued", "known" or "refused".
        `carried`: the previous file the redirect leading here was recorded to reach."""
        k = url_key(u)
        if k in entry_of:
            return "known"
        entry_of[k] = u
        why, scope[0] = rescope(u, url, scope[0], filters, front)
        if why == "rule":
            return "refused"
        if why is not None:
            report.out_of_scope.append(redact_url(u))
            return "refused"
        if depth and hop > depth:
            return "refused"
        if skipped_by_extension(u, exts):
            report.filtered.append(redact_url(u))
            return "refused"
        if len(queue) >= policy.max_links:
            report.partial = True
            return "refused"
        mine = carried is not None and sends(carried, u, True, names)
        queue.append(_Entry(u, hop, referer, meta, front, redirects, initiator,
                            *_revalidates(prev.get(k), carried, mine)))
        return "queued"

    def work(entry: _Entry):
        return fetch_page(entry.url, fetcher, report, lock, None,
                          kind="linked" if entry.referer else "navigate",
                          referer=entry.referer, meta=entry.meta, prev=entry.prev,
                          tried=changes and changes.tried, responses=responses)

    def handle(entry: _Entry, outcome: str, final: str, res) -> None:
        safe, via = redact_url(entry.url), redact_url(entry.referer) if entry.referer else None
        if outcome == "moved":
            final = urlsplit(final)._replace(fragment="").geturl()  # htsmirror.c drops it
            moved[url_key(entry.url)] = url_key(final)
            if entry.redirects >= MAX_REDIRECTS:
                report.errors.append((safe, "too many redirects", via))
                state["front_failed"] |= entry.front
                return
            referer, meta = moved_request(entry.url, entry.referer, entry.meta, final,
                                          front=entry.front, initiator=entry.initiator)
            got = enqueue(final, hop=entry.hop, referer=referer, meta=meta, front=entry.front,
                          redirects=entry.redirects + 1, initiator=entry.initiator,
                          carried=entry.carry)
            state["front_failed"] |= entry.front and got != "queued"
            return
        if outcome == "kept":
            for link in keep(entry, res, safe, via):
                # second copy of the loop at the end of handle()
                got = enqueue(link.url, hop=entry.hop + 1, referer=entry.url, meta=link.meta,
                              initiator=entry.url)
                if got != "refused":
                    requested.setdefault(url_key(link.url), set()).add(entry_of[url_key(link.url)])
            return
        if outcome != "ok":
            state["front_failed"] |= entry.front
            return
        state["front_ok"] |= entry.front
        ctype = res.headers.get("content-type")
        mime = mime_type(ctype)
        scans = {"parse_scripts": policy.parse_scripts,
                 "extended_parsing": policy.extended_parsing}
        if mime == "text/html":
            links = page_links(res.body, entry.url, frame=entry.meta.dest,
                               robots=policy.obey_robots, **scans)
        elif mime == "text/css":
            links = css_links(res.body, entry.url, **scans)
        elif mime in JS_MIMES:  # a script's links take its page's base (htsparse.c:1280-1285)
            links = script_links(res.body, entry.url, entry.referer or entry.url, **scans)
        else:
            links = []
        mine = entry.prev.path if entry.prev and not entry.prev.redirected else None
        path = save_file(names, entry.url, ctype, res.body, exts, report, safe, via,
                         prefer=mine, changes=changes)
        if path is not None:
            saved[url_key(entry.url)] = path
            fields[path] = record_of(res)
            state["bytes"] += len(res.body)
            if mime == "text/html":
                pages[path] = entry.url
            elif mime == "text/css" or mime in JS_MIMES:  # a script: its page's base
                scripts[path] = (entry.url, None if mime == "text/css" else entry.referer,
                                 mime == "text/css")
        for link in links:
            got = enqueue(link.url, hop=entry.hop + 1, referer=entry.url, meta=link.meta,
                          initiator=entry.url)
            if got != "refused":
                requested.setdefault(url_key(link.url), set()).add(entry_of[url_key(link.url)])

    def keep(entry: _Entry, res, safe: str, via: str | None) -> list:
        """Account for the previous copy a revalidation kept; return its links. A failed
        transfer follows none (HTTrack never parses it); a challenged or failed start URL
        still fails the front (spec 5.4, 5.8), and the crawl stops there."""
        p = entry.prev
        failed = res.challenged or res.error is not None
        state["front_failed" if failed else "front_ok"] |= entry.front
        names.assign(entry.url, p.record["content_type"], prefer=p.path)
        saved[url_key(entry.url)] = p.path
        kept.add(p.path)
        fields[p.path] = p.record
        mime = mime_type(p.record["content_type"])
        if mime not in ("text/html", "text/css", *JS_MIMES) or res.error is not None or (
                failed and entry.front):
            return []
        try:
            with open(p.path, "rb") as f:
                body = f.read()
        except OSError as exc:
            report.errors.append((safe, f"kept copy unreadable: {exc}", via))
            return []
        scans = {"parse_scripts": policy.parse_scripts,
                 "extended_parsing": policy.extended_parsing}
        if mime == "text/css":
            return _kept_links(lambda own, _: css_links(body, own, **scans), entry.url, p.path,
                               root, url_of)
        if mime in JS_MIMES:  # as handle() scans a fetched script, from its page's file
            page = entry.referer
            return _kept_links(lambda own, base: script_links(body, own, base, **scans),
                               entry.url, p.path, root, url_of, page,
                               saved.get(url_key(page)) if page else None)
        return _kept_links(lambda own, _: page_links(body, own, frame=entry.meta.dest,
                                                     robots=policy.obey_robots, **scans),
                           entry.url, p.path, root, url_of)

    root = os.path.realpath(output_dir)
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
    relink(pages, local, report, scripts, parse_scripts=policy.parse_scripts,
           extended_parsing=policy.extended_parsing)
    chosen: dict[str, tuple[bool, str]] = {}
    for k, asked in requested.items():
        if (f := file_of(k)) is not None:
            for u in asked:
                cand = (k not in saved, u)  # reached through a redirect, URL requested
                chosen[f] = min(chosen[f], cand) if f in chosen else cand
    stamp({f: u for f, (_, u) in chosen.items() if f not in kept}, fields, report)

    report.challenged.sort()
    report.robots_blocked.sort()
    report.out_of_scope.sort()
    report.filtered.sort()
    report.kept.sort()
    report.size_kept.sort()
    report.errors.sort(key=lambda e: (e[0], e[1]))
    files = sorted(set(saved.values()) - kept)
    front_failed = state["front_failed"] and not state["front_ok"]
    urls = {f: u for f, (_, u) in sorted(chosen.items())}
    records = {f: {**fields[f], "redirected": r} for f, (r, _) in sorted(chosen.items())}
    if policy.cache == 0:
        records = uncached(records, urls, previous, output_dir)
    report_of = changes and changes.report(dict.fromkeys(saved.values()),  # queue order
                                           set(saved.values()) - kept, urls, fields)
    return HttrackResult(bool(files or kept), files, len(kept), report, front_failed, urls,
                         sorted(kept), records, report_of)
