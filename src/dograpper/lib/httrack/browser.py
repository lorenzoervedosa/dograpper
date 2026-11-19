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
import os
import threading
from urllib.parse import urlsplit

from dograpper.lib.url_filter import UrlFilters
from dograpper.utils.atomic_write import atomic_write_bytes
from dograpper.utils.redact import redact_url

from .crawl import extension_set, fetch_page, record_of, relink, stamp
from .fetcher import Fetcher, same_host
from .links import url_key
from .mirror import outside, skipped_by_extension, start_rule
from .naming import NameRegistry
from .report import RunReport

logger = logging.getLogger(__name__)

# The Fetcher hands the body over decoded; fulfill() sets its own length.
_DROPPED = frozenset({"content-encoding", "content-length", "transfer-encoding",
                      "connection", "keep-alive"})


def _is_page(res) -> bool:
    return (res.headers.get("content-type") or "").split(";")[0].strip().lower() == "text/html"


class Navigator:
    def __init__(self, fetcher: Fetcher, output_dir: str, start_url: str,
                 include_extensions: str, *, filters: UrlFilters | None = None,
                 seeded: bool = False):
        self.fetcher, self.filters, self._seeded = fetcher, filters, seeded
        self.report = RunReport()
        self._start, self._rule, self._front = start_url, start_rule(start_url), False
        self._lock = threading.Lock()  # fetch_page's report lock
        self._names, self._exts = NameRegistry(output_dir), extension_set(include_extensions)
        self._armed = None  # the FetchResult the next main-frame navigation is served
        self._last = None   # (final URL, FetchResult) of the last prepare()
        self._prepared = 0  # URLs prepare() fetched: policy.max_links caps them
        self._frame = None
        self._files: dict[str, str] = {}  # saved file -> URL it came from
        self._pages: dict[str, str] = {}  # the HTML pages among them, for relink
        self._local: dict[str, str] = {}  # url_key -> saved file
        self._referers: dict[str, str] = {}  # link -> the page that first linked it
        self.records: dict[str, dict] = {}  # saved file -> manifest RECORD_FIELDS

    def context_options(self) -> dict:
        """browser.new_context() options: the profile's User-Agent on every request, and no
        service worker, which would answer navigations past the route."""
        return {"user_agent": self.fetcher.policy.user_agent, "service_workers": "block"}

    def attach(self, context, page) -> None:
        """Route every request of `context`; `page` is the one the crawl saves."""
        self._frame = page.main_frame
        context.route("**/*", self._route)

    def follows(self, url: str, page: str) -> bool:
        """Whether the crawl follows `url`, a link of `page`, as mirror_site queues one: in
        scope (mirror.outside) and not a non-page type --include-extensions leaves out.
        `page` is then its Referer (the first page linking it, as HTTrack sends it)."""
        if outside(url, self._start, self._rule, self.filters) is not None \
                or skipped_by_extension(url, self._exts):
            return False
        self._referers.setdefault(url, page)
        return True

    def _redirect_ok(self, url: str, nxt: str) -> bool:
        if self._seeded:  # as fetch_url_list's redirect_ok (the first copy): host and --filter
            if not same_host(url, nxt):
                self.report.out_of_scope.append(redact_url(nxt))
                return False
            return self.filters is None or self.filters.decide(nxt) is not False
        why = outside(nxt, self._start, self._rule, self.filters)
        if why == "directory" and self._front:  # deviation (spec 5.5), as mirror_site
            logger.info("start URL redirected to %s; the crawl scope follows it",
                        redact_url(nxt))
            self._rule, why = start_rule(nxt), None
        if why not in (None, "rule"):  # a rule's refusal lands in filters.excluded
            self.report.out_of_scope.append(redact_url(nxt))
        return why is None

    def prepare(self, url: str) -> str | None:
        """Fetch `url` under the policy, its redirects followed while they stay in scope
        (fetch_page); return the URL the browser is to open, its answer armed for that
        navigation, or None when the policy refused it (the report says why)."""
        self._armed = None  # never a stale answer for whatever the browser opens next
        if self._prepared >= self.fetcher.policy.max_links:
            self.report.partial = True
            return None
        self._prepared += 1
        self._front = url == self._start
        outcome, final, res = fetch_page(url, self.fetcher, self.report, self._lock,
                                         self._redirect_ok, referer=self._referers.get(url))
        if outcome != "ok":
            return None
        saved = self._local.get(url_key(final))
        if saved is not None:  # a redirect to a page already saved: its links lead there too
            self._local[url_key(url)] = saved
        self._armed, self._last = res, (final, res)
        return final

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
        ctype = res.headers.get("content-type")
        path = self._names.assign(final, ctype)
        if path is None:
            self.report.errors.append((redact_url(final), "unsafe local path", None))
            return None
        if self._exts and os.path.splitext(path)[1].lower() not in self._exts:
            self.report.filtered.append(redact_url(final))
            return None
        page = _is_page(res)
        try:
            atomic_write_bytes(path, html.encode("utf-8") if page else res.body)
        except OSError as exc:  # e.g. file/dir conflict or disk full: recorded, run continues
            self.report.errors.append((redact_url(final), f"write failed: {exc}", None))
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

    def _route(self, route) -> None:
        req = route.request
        if urlsplit(req.url).path.startswith("/cdn-cgi/"):  # never requested (spec 5.4)
            route.abort("blockedbyclient")
            return
        if not req.is_navigation_request():  # a subresource: the browser's own request
            route.continue_()
            return
        if req.frame is not self._frame:  # an iframe or a popup: never part of the saved page
            route.abort("blockedbyclient")
            return
        res, self._armed = self._armed, None
        if res is None:  # one the page started itself (meta refresh, script): not followed
            logger.debug("browser: navigation to %s not followed", redact_url(req.url))
            route.abort("blockedbyclient")
            return
        route.fulfill(status=res.status, body=res.body,
                      headers={k: v for k, v in res.headers.items() if k not in _DROPPED})
