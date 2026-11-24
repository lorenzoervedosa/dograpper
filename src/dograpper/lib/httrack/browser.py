"""The httrack profile's side of the Playwright crawl (spec 7, PR 4).

Every navigation of the crawled page is fetched by the profile's own transport through
crawl.fetch_page (robots.txt before each hop, pacing, retries, Retry-After, the challenge
and status policy) and handed to the browser with route.fulfill(), so it carries the
profile's identity on the wire. A navigation the policy refuses is aborted before
anything renders: no challenge script ever runs.

Redirects are resolved here, before the browser opens the page: Chromium follows a
fulfilled 3xx without routing the next hop, which would leave the policy.

Playwright is never imported: the crawl (lib/playwright_crawl.py) passes its objects in.
"""

import logging
import threading
from urllib.parse import urlsplit

from dograpper.lib.url_filter import UrlFilters
from dograpper.utils.redact import redact_url

from .crawl import (RunResponses, extension_set, fetch_page, record_of, relink, save_file, seed_redirect_ok,
                    stamp)
from .fetcher import Fetcher
from .links import page_links, url_key
from .mirror import outside, rescope, skipped_by_extension, start_rule
from .naming import NameRegistry, mime_type
from .policy import NAVIGATION, FetchMeta
from .report import RunReport

logger = logging.getLogger(__name__)

# The Fetcher hands the body over decoded; fulfill() sets its own length.
_DROPPED = frozenset({"content-encoding", "content-length", "transfer-encoding",
                      "connection", "keep-alive"})
# a replayed subresource sets no cookie again: the first answer already did
_NOT_REPLAYED = _DROPPED | {"set-cookie"}


# Subresources the browser fetched, kept in memory for the run (spec 5.2): bounded in total
# bytes, no eviction. 64 MiB holds the shared scripts and styles of a documentation site.
SUBRESOURCE_CACHE_BYTES = 64 * 1024 * 1024


def _is_page(res) -> bool:
    return mime_type(res.headers.get("content-type")) == "text/html"


class Navigator:
    def __init__(self, fetcher: Fetcher, output_dir: str, start_url: str,
                 include_extensions: str, *, filters: UrlFilters | None = None,
                 seeded: bool = False, reuse: RunResponses | None = None):
        self.fetcher, self.filters, self._seeded = fetcher, filters, seeded
        self._reuse = reuse  # what the engine fetched earlier in this run (#160)
        self.report = RunReport()
        self._start, self._rule, self._front = start_url, start_rule(start_url), False
        self._lock = threading.Lock()  # fetch_page's report lock
        self._names, self._exts = NameRegistry(output_dir), extension_set(include_extensions)
        self._armed = None  # the FetchResult the next main-frame navigation is served
        self._last = None   # (final URL, FetchResult) of the last prepare()
        self._prepared = 0  # URLs prepare() fetched: policy.max_links caps them
        self._frame = None
        # subresource URL -> its answer; a second byte-capped store, see crawl.RunResponses
        self._cache: dict[str, tuple[int, dict, bytes]] = {}
        self._cache_bytes, self._cache_limit = 0, SUBRESOURCE_CACHE_BYTES
        self._started: list[str] = []  # navigations the current page started itself
        self._files: dict[str, str] = {}  # saved file -> URL it came from
        self._pages: dict[str, str] = {}  # the HTML pages among them, for relink
        self._local: dict[str, str] = {}  # url_key -> saved file
        self._referers: dict[str, str] = {}  # link -> the page that first linked it
        # link -> its FetchMeta there; the page is also the initiator of its redirect chain
        self._metas: dict[str, FetchMeta] = {}
        self._page_metas: dict[str, FetchMeta] = {}  # url_key -> meta of the armed page's links
        self.records: dict[str, dict] = {}  # saved file -> manifest RECORD_FIELDS

    def context_options(self) -> dict:
        """browser.new_context() options: the profile's User-Agent on every request, and no
        service worker, which would answer navigations past the route."""
        return {"user_agent": self.fetcher.policy.user_agent, "service_workers": "block"}

    def attach(self, context, page) -> None:
        """Route every request of `context`; `page` is the one the crawl saves."""
        self._frame = page.main_frame
        context.route("**/*", self._route)
        context.on("response", self._response)

    def follows(self, url: str, page: str) -> bool:
        """Whether the crawl follows `url`, a link of `page`, as mirror_site queues one: in
        scope (mirror.outside) and not a non-page type --include-extensions leaves out.
        `page` is then its Referer (the first page linking it, as HTTrack sends it), and its
        FetchMeta is what the engine's parse of that page gives the link (a link only the
        render added is a plain navigation)."""
        if outside(url, self._start, self._rule, self.filters) is not None \
                or skipped_by_extension(url, self._exts):
            return False
        if url not in self._referers:
            self._referers[url] = page
            self._metas[url] = self._page_metas.get(url_key(url), NAVIGATION)
        return True

    def _redirect_ok(self, url: str, nxt: str) -> bool:
        if self._seeded:  # as fetch_url_list
            return seed_redirect_ok(url, nxt, self.report, self.filters)
        why, self._rule = rescope(nxt, self._start, self._rule, self.filters, self._front)
        if why not in (None, "rule"):  # a rule's refusal lands in filters.excluded
            self.report.out_of_scope.append(redact_url(nxt))
        return why is None

    def prepare(self, url: str) -> str | None:
        """Fetch `url` under the policy, its redirects followed while they stay in scope
        (fetch_page); return the URL the browser is to open, its answer armed for that
        navigation, or None when the policy refused it (the report says why)."""
        self._armed = None  # never a stale answer for whatever the browser opens next
        self._started = []  # a capture belongs to the page that produced it
        if self._prepared >= self.fetcher.policy.max_links:
            self.report.partial = True
            return None
        self._prepared += 1
        self._front = url == self._start
        reused = self._reuse.take(url) if self._reuse is not None else None
        if reused is not None and self._front and reused[0] != url:
            reused = None  # a start URL's redirect re-bases the scope (_redirect_ok): fetch it
        if reused is not None:  # fetched by the engine under the same policy: no second request
            outcome, (final, res) = "ok", reused
        else:
            outcome, final, res = fetch_page(url, self.fetcher, self.report, self._lock,
                                             self._redirect_ok,
                                             referer=self._referers.get(url),
                                             meta=self._metas.get(url, NAVIGATION),
                                             front=self._front or self._seeded,
                                             initiator=self._referers.get(url))
        if outcome != "ok":
            return None
        saved = self._local.get(url_key(final))
        if saved is not None:  # a redirect to a page already saved: its links lead there too
            self._local[url_key(url)] = saved
        self._armed, self._last = res, (final, res)
        policy = self.fetcher.policy
        self._page_metas = {} if not _is_page(res) else {
            url_key(link.url): link.meta for link in reversed(page_links(
                res.body, final, robots=policy.obey_robots, parse_scripts=False,
                extended_parsing=False))}  # reversed: the first link to a URL wins
        return final

    def initiated(self) -> list[str]:
        """The main-frame navigations the page just crawled started itself (aborted, never
        opened), once: the crawl queues them as links of that page."""
        started, self._started = self._started, []
        return started

    @property
    def renders(self) -> bool:
        """Whether the answer prepare() armed last is an HTML page for the browser to render;
        any other it would show as text or download, so it is saved as fetched."""
        return _is_page(self._last[1])

    def save(self, url: str, html: str | None) -> str | None:
        """Write what the browser rendered of the page prepare(`url`) fetched, or the body
        as fetched when it is no HTML page (the browser adds nothing to it), under the name
        the engine gives the final URL (NameRegistry). Return the file, or None when
        --include-extensions leaves it out or it cannot be written (the report says which,
        as crawl.fetch_url_list words it)."""
        final, res = self._last
        page = _is_page(res)
        path = save_file(self._names, final, res.headers.get("content-type"),
                         html.encode("utf-8") if page else res.body, self._exts, self.report,
                         redact_url(final), None)
        if path is None:
            return None
        self._files[path] = final
        if page:
            self._pages[path] = final
        self._local[url_key(final)] = self._local[url_key(url)] = path
        self.records[path] = {**record_of(res), "redirected": final != url}
        return path

    def error(self, url: str, exc: Exception) -> None:
        """A page the browser failed to open or read (timeout, crash): an error of the report,
        without the Playwright call log that follows the first line."""
        first = (str(exc).splitlines() or [repr(exc)])[0]
        self.report.errors.append((redact_url(url), f"browser: {first}", None))

    def finish(self) -> None:
        """Rewrite the links between the saved pages (-K0) and set their file times, as the
        engine does once every name is known."""
        policy = self.fetcher.policy
        relink(self._pages, self._local, self.report, parse_scripts=policy.parse_scripts,
               extended_parsing=policy.extended_parsing)
        stamp(self._files, self.records, self.report)

    def _response(self, response) -> None:
        """Keep what the server answered a subresource (GET, 200, no `no-store`), read here
        because the body is gone once the page closes, until the byte bound is reached."""
        req = response.request
        if (self._cache_bytes >= self._cache_limit or req.is_navigation_request() or req.method != "GET" or response.status != 200
                or req.url in self._cache or "no-store" in
                (response.headers.get("cache-control") or "").lower()):
            return
        try:
            body = response.body()
        except Exception as e:  # a cache miss only: the page rendered with this response
            logger.debug("browser: %s not kept: %s", redact_url(req.url), e)
            return
        if self._cache_bytes + len(body) > self._cache_limit:
            return
        self._cache_bytes += len(body)
        self._cache[req.url] = (response.status, response.headers, body)

    def _route(self, route) -> None:
        req = route.request
        if urlsplit(req.url).path.startswith("/cdn-cgi/"):  # never requested (spec 5.4)
            route.abort("blockedbyclient")
            return
        if not req.is_navigation_request():  # a subresource: the browser's own request
            cached = self._cache.get(req.url) if req.method == "GET" else None
            if cached is None:
                route.continue_()
            else:  # asked before in this run: answered from memory, nothing sent
                status, headers, body = cached
                route.fulfill(status=status, body=body, headers={
                    k: v for k, v in headers.items() if k not in _NOT_REPLAYED})
            return
        if req.frame is not self._frame:  # an iframe or a popup: never part of the saved page
            route.abort("blockedbyclient")
            return
        res, self._armed = self._armed, None
        if res is None:  # one the page started itself (meta refresh, script): a link instead
            logger.debug("browser: navigation to %s queued as a link", redact_url(req.url))
            self._started.append(req.url)
            route.abort("blockedbyclient")
            return
        route.fulfill(status=res.status, body=res.body,
                      headers={k: v for k, v in res.headers.items() if k not in _DROPPED})
