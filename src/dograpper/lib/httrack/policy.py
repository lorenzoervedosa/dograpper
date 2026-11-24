"""HTTrack 3.51 request policy: clamps, wire-identical headers, TLS context."""

import functools
import importlib
import ipaddress
import logging
import ssl
from dataclasses import dataclass
from typing import NamedTuple
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from urllib.parse import urlsplit

from ...utils.http_headers import merge_headers
from ...utils.redact import drop_userinfo
from .escape import escape_unsafe, request_target

logger = logging.getLogger(__name__)

# Deliberate second copy of cli.py's version lookup: lib must not import the CLI layer.
try:
    _VERSION = _pkg_version("dograpper")
except PackageNotFoundError:
    _VERSION = "0.0.0+unknown"

DEFAULT_USER_AGENT = f"Mozilla/5.0 (compatible; dograpper/{_VERSION})"
ACCEPT = ("text/html,image/png,image/jpeg,image/pjpeg,image/x-xbitmap,"
          "image/svg+xml,image/gif;q=0.9,*/*;q=0.1")
ACCEPT_LANGUAGE = "en, *"

# --browser-headers (HTTrack -%Q, #170): what the browser a --user-agent names sends, from
# HTTrack's tables (Chrome 155 and Firefox 158 captures). Accept by Sec-Fetch-Dest,
# htsfetch.c:549-578 (embed was never captured, so it follows object):
_CHROME_NAV = ("text/html,application/xhtml+xml,application/xml;q=0.9,image/jxl,image/avif,"
               "image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7")
_FIREFOX_NAV = "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
_STYLE = "text/css,*/*;q=0.1"
BROWSER_ACCEPT = {
    "chrome": {"document": _CHROME_NAV, "iframe": _CHROME_NAV, "frame": _CHROME_NAV,
               "image": "image/jxl,image/avif,image/webp,image/apng,image/svg+xml,image/*,"
                        "*/*;q=0.8",
               "style": _STYLE, "script": "*/*", "font": "*/*", "audio": "*/*",
               "video": "*/*", "object": _CHROME_NAV, "embed": _CHROME_NAV},
    "firefox": {"document": _FIREFOX_NAV, "iframe": _FIREFOX_NAV, "frame": _FIREFOX_NAV,
                "image": "image/avif,image/jxl,image/webp,image/png,image/svg+xml,"
                         "image/*;q=0.8,*/*;q=0.5",
                "style": _STYLE, "script": "*/*",
                "font": "application/font-woff2;q=1.0,application/font-woff;q=0.9,*/*;q=0.8",
                "audio": "audio/webm,audio/ogg,audio/wav,audio/*;q=0.9,application/ogg;q=0.7,"
                         "video/*;q=0.6,*/*;q=0.5",
                "video": "video/webm,video/ogg,video/*;q=0.9,application/ogg;q=0.7,"
                         "audio/*;q=0.6,*/*;q=0.5",
                "object": "*/*", "embed": "*/*"}}
BROWSER_ACCEPT_LANGUAGE = "en-US,en;q=0.9"  # htsfetch.h:135
# htslib.c:913-946 header_orders: HTTrack's own, then Chrome's navigation and subresource
# orders and Firefox's, without the headers the profile never sends (Content-length, From,
# Origin)
_CH = ("sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform")
_FETCH = ("Sec-Fetch-Site", "Sec-Fetch-Mode", "Sec-Fetch-User", "Sec-Fetch-Dest")
_ORDERS = {
    None: ("Referer", "Connection", "Host", *_CH, "Upgrade-Insecure-Requests", "User-Agent",
           "Accept", *_FETCH, "Accept-Language", "Accept-Encoding"),
    ("chrome", True): ("Host", "Connection", *_CH, "Accept-Language",
                       "Upgrade-Insecure-Requests", "User-Agent", "Accept", *_FETCH, "Referer",
                       "Accept-Encoding"),
    ("chrome", False): ("Host", "Connection", "sec-ch-ua-platform", "Accept-Language",
                        "sec-ch-ua", "Upgrade-Insecure-Requests", "User-Agent",
                        "sec-ch-ua-mobile", "Accept", *_FETCH, "Referer", "Accept-Encoding"),
    "firefox": ("Host", "User-Agent", "Accept", "Accept-Language", "Accept-Encoding",
                "Connection", "Referer", "Upgrade-Insecure-Requests", "Sec-Fetch-Dest",
                "Sec-Fetch-Mode", "Sec-Fetch-Site", "Sec-Fetch-User", *_CH)}

MAX_CONNECTIONS = 8
MAX_CONN_RATE = 5.0
MAX_BANDWIDTH = 10_000_000
ZSTD_MAX_WINDOW = 8 * 1024 * 1024  # RFC 9659 lets a client refuse larger windows
MAX_RETRY_AFTER_CAP = 3600  # never lifted, even by disable_security_limits


class FetchMeta(NamedTuple):
    """What a browser declares for a request (htsfetch.c hts_fetch_meta): Sec-Fetch-Dest
    (hts_fetch_dest_name; "" when HTTrack cannot classify the link, which then gets no
    fetch metadata), Sec-Fetch-Mode, Sec-Fetch-User for a user navigation, and the
    Sec-Fetch-Site a redirect chain fixed (None: from the Referer)."""
    dest: str = "document"
    mode: str = "navigate"
    user: bool = True
    site: str | None = None


# htsfetch.h hts_fetch_site, from best to worst: hts_fetch_through keeps the worst hop
SITES = ("none", "same-origin", "same-site", "cross-site")


NAVIGATION = FetchMeta()  # a start URL, as if typed in, or a followed <a href>


@dataclass(frozen=True)
class HttrackPolicy:
    user_agent: str
    connections: int
    max_conn_rate: float
    max_bandwidth: int
    timeout: float
    retries: int
    max_links: int
    max_retry_after: int
    delay_ms: int
    obey_robots: bool
    parse_scripts: bool     # HTTrack -j: scan scripts and stylesheets for links
    extended_parsing: bool  # HTTrack -%P: guess links in strings and other attributes
    # HTTrack -C: 0 no cache, 1 trust it, 2 revalidate; None is HTTrack's default, 2 over a
    # finished mirror (a previous manifest), else 1 (htscoremain.c:1263-1285)
    cache: int | None = None
    updatehack: bool = False  # HTTrack -%s: a 200 announcing the size on disk keeps the file
    do_not_recatch: bool = False  # HTTrack -%n: an erased file stays empty, not fetched
    changes: bool = False  # HTTrack -%d: write hts-changes.json (lib/httrack/changes.py)
    # --header pairs, checked by utils/http_headers.py; request_headers() merges them in place
    headers: tuple[tuple[str, str], ...] = ()
    browser_headers: bool = True  # HTTrack -%Q: Sec-Fetch-*, the browser tables, client hints


def _clamp(name, value, cap, disabled):
    if not disabled and value > cap:
        logger.warning("%s=%s exceeds the safety limit; clamped to %s "
                       "(--disable-security-limits lifts it)", name, value, cap)
        return cap
    return value


def build_policy(*, user_agent: str | None = None, connections: int = 4,
                 max_conn_rate: float = 5.0, max_bandwidth: int = 100_000,
                 timeout: float = 120.0, retries: int = 2, max_links: int = 100_000,
                 max_retry_after: int = 60, delay_ms: int = 0, obey_robots: bool = True,
                 disable_security_limits: bool = False, parse_scripts: bool = True,
                 extended_parsing: bool = True, cache: int | None = None,
                 updatehack: bool = False, do_not_recatch: bool = False,
                 changes: bool = False,
                 headers: tuple[tuple[str, str], ...] = (),
                 browser_headers: bool = True) -> HttrackPolicy:
    # Fail at build time: 0 rates divide by zero mid-run, negative retries skip every attempt.
    for name, value in (("connections", connections), ("max_conn_rate", max_conn_rate),
                        ("max_bandwidth", max_bandwidth), ("timeout", timeout),
                        ("max_links", max_links)):
        if not value > 0:
            raise ValueError(f"{name} must be positive, got {value!r}")
    for name, value in (("retries", retries), ("max_retry_after", max_retry_after),
                        ("delay_ms", delay_ms)):
        if not value >= 0:
            raise ValueError(f"{name} must not be negative, got {value!r}")
    if cache not in (None, 0, 1, 2):
        raise ValueError(f"cache must be 0, 1 or 2, got {cache!r}")
    if max_retry_after > MAX_RETRY_AFTER_CAP:
        logger.warning("max_retry_after=%s exceeds the hard maximum; clamped to %s",
                       max_retry_after, MAX_RETRY_AFTER_CAP)
        max_retry_after = MAX_RETRY_AFTER_CAP
    off = disable_security_limits
    return HttrackPolicy(
        # "" sends no User-Agent, as HTTrack -F "" (htslib.c:1249-1252); None is the default
        user_agent=DEFAULT_USER_AGENT if user_agent is None else user_agent,
        connections=_clamp("connections", connections, MAX_CONNECTIONS, off),
        max_conn_rate=_clamp("max_conn_rate", max_conn_rate, MAX_CONN_RATE, off),
        max_bandwidth=_clamp("max_bandwidth", max_bandwidth, MAX_BANDWIDTH, off),
        timeout=timeout,
        retries=retries,
        max_links=max_links,
        max_retry_after=max_retry_after,
        delay_ms=delay_ms,
        obey_robots=obey_robots,
        parse_scripts=parse_scripts,
        extended_parsing=extended_parsing,
        cache=cache,
        updatehack=updatehack,
        do_not_recatch=do_not_recatch,
        changes=changes,
        headers=tuple(headers),
        browser_headers=browser_headers,
    )


def _ua_parts(user_agent: str):
    """(product tokens, first comment or None) of a User-Agent, read as htslib.c reads it;
    None when a comment never closes or a token is empty (a control character)."""
    tokens, comment, i = [], None, 0
    while i < len(user_agent):
        if user_agent[i] == " ":
            i += 1
        elif user_agent[i] == "(":
            end = user_agent.find(")", i)
            if end < 0:
                return None
            if comment is None:
                comment = user_agent[i + 1:end]
            i = end + 1
        else:
            n = i
            while n < len(user_agent) and user_agent[n] > " " and user_agent[n] != "(":
                n += 1
            if n == i:  # every caller refuses an empty token (htslib.c:776-778)
                return None
            tokens.append(user_agent[i:n])
            i = n
    return tokens, comment


def _product(token: str, name: str) -> int | None:
    """htslib.c:692-714 ua_product_is: None when `token` is no `name`/version; else the
    version's first number, -1 when the version is malformed."""
    if not token.startswith(name + "/"):
        return None
    version = token[len(name) + 1:]
    digits = len(version) - len(version.lstrip("0123456789"))
    if (version[:1] == "0" or not digits or int(version[:digits]) >= 100000
            or version[digits:].strip(".0123456789")):
        return -1
    return int(version[:digits])


_GREASE_CHARS, _GREASE_VERSIONS = " (:-./);=?_", ("8", "99", "24")
_BRAND_ORDERS = ((0, 1, 2), (0, 2, 1), (1, 0, 2), (1, 2, 0), (2, 0, 1), (2, 1, 0))
_PLATFORMS = (("Android", '"Android"'), ("CrOS", '"Chrome OS"'), ("Windows", '"Windows"'),
              ("Macintosh", '"macOS"'), ("Linux", '"Linux"'))  # Android before Linux


def client_hints(user_agent: str) -> tuple[str, bool, str] | None:
    """(sec-ch-ua, mobile, sec-ch-ua-platform) Chrome or Edge >= 108 sends with
    `user_agent`, with Chromium's GREASE brand seeded by the major (htslib.c:728-811
    hts_client_hints_of), or None for any other User-Agent."""
    parts = _ua_parts(user_agent)
    if parts is None:
        return None
    tokens, comment = parts
    chrome, edge, mobile, mozilla = -1, 0, False, False
    for token in tokens:  # every product must be one Chrome or Edge sends
        if (major := _product(token, "Chrome")) is not None:
            chrome = major
        elif (major := _product(token, "Edg")) is not None:
            edge = major
        elif _product(token, "Mozilla") is not None:
            mozilla = True
        elif token == "Mobile":
            mobile = True
        elif _product(token, "AppleWebKit") is None and _product(token, "Safari") is None:
            return None
    if not mozilla or chrome < 108 or (edge != 0 and edge != chrome):
        return None
    platform = next((value for word, value in _PLATFORMS if word in (comment or "")), None)
    if platform is None:
        return None
    brands = (f'"Not{_GREASE_CHARS[chrome % 11]}A{_GREASE_CHARS[(chrome + 1) % 11]}Brand";'
              f'v="{_GREASE_VERSIONS[chrome % 3]}"', f'"Chromium";v="{chrome}"',
              f'"Microsoft Edge";v="{edge}"' if edge > 0 else f'"Google Chrome";v="{chrome}"')
    shuffled = [""] * 3
    for i, at in enumerate(_BRAND_ORDERS[chrome % 6]):
        shuffled[at] = brands[i]
    return ", ".join(shuffled), mobile, platform


def _is_firefox(user_agent: str) -> bool:
    """htslib.c:820-857 ua_is_firefox: Firefox from 90 (its first Sec-Fetch-*), with only
    the products Firefox sends."""
    parts = _ua_parts(user_agent)
    if parts is None:
        return False
    firefox, gecko, mozilla = -1, False, False
    for token in parts[0]:
        if (major := _product(token, "Firefox")) is not None:
            firefox = major
        elif _product(token, "Gecko") is not None:
            gecko = True
        elif _product(token, "Mozilla") is not None:
            mozilla = True
        else:
            return False
    return mozilla and gecko and firefox >= 90


def browser_family(user_agent: str) -> str | None:
    """"chrome" (Chrome or Edge), "firefox" or None, as htslib.c:859-866 tells them."""
    if client_hints(user_agent) is not None:
        return "chrome"
    return "firefox" if _is_firefox(user_agent) else None


def _importable(name: str) -> bool:
    """True when `name` imports and can decode within an output bound (fetcher relies on it)."""
    try:
        mod = importlib.import_module(name)
    except ImportError:
        return False
    if name == "brotli":  # output_buffer_limit arrived in brotli 1.2.0
        try:
            mod.Decompressor().process(b"", output_buffer_limit=1)
        except TypeError:
            return False
    if name == "zstandard":  # needs a window cap and a decompressobj that reports frame end
        try:
            d = mod.ZstdDecompressor(max_window_size=ZSTD_MAX_WINDOW).decompressobj()
        except (TypeError, AttributeError):
            return False
        return hasattr(d, "eof") and hasattr(d, "unused_data")
    if name == "compression.zstd":
        return hasattr(mod, "DecompressionParameter")
    return True


_DECODER_MODULES = {"br": ("brotli",), "zstd": ("compression.zstd", "zstandard")}


@functools.cache  # probed once per process; tests that fake availability call cache_clear()
def _decoder_modname(encoding: str) -> str | None:
    return next((m for m in _DECODER_MODULES[encoding] if _importable(m)), None)


def decoder_module(encoding: str):
    """Module able to decode `encoding` ("br" | "zstd"), or None. Single source for
    both what we advertise and what the fetcher decodes."""
    name = _decoder_modname(encoding)
    return importlib.import_module(name) if name else None


def accept_encoding(secure: bool = True) -> str:
    """htscodec.c: br and zstd only over TLS, and only when this build can decode them."""
    extra = [e for e in _DECODER_MODULES if _decoder_modname(e)] if secure else []
    return ", ".join(["gzip", "deflate"] + extra + ["identity;q=0.9"])


def _trustworthy(scheme: str, host: str) -> bool:
    """htsfetch.c hts_fetch_trustworthy: TLS, a localhost name or a loopback address."""
    if scheme == "https":
        return True
    name = urlsplit("//" + host).hostname or ""
    try:
        return ipaddress.ip_address(name).is_loopback
    except ValueError:
        return name == "localhost" or name.endswith(".localhost")


def _site_key(host: str) -> str:
    """htsfetch.c site_key: IP literals and names with an empty label or a numeric last label
    key on themselves, others on their last two labels (keeping a trailing dot).
    shortcut: no public-suffix list (a.co.uk and b.co.uk read as same-site); upgrade when
    cross-host crawling lands."""
    name = host[:-1] if len(host) > 1 and host.endswith(".") else host
    labels = name.split(".")
    if ":" in host or "" in labels or labels[-1][:1].isdigit():
        return host
    return ".".join(labels[-2:]) + host[len(name):]


def _referer_value(page: str | None) -> str | None:
    """Referer for a request from `page`, built as htslib.c:1136-1163 builds it: scheme, the
    escaped host past any user:password, then the escaped path and query (no fragment).
    None when `page` is empty, does not parse or cannot be escaped: it is dropped, never
    raised."""
    if not page:
        return None
    try:
        p = drop_userinfo(urlsplit(page))
        return f"{p.scheme}://{escape_unsafe(p.netloc)}{request_target(p)}"
    except ValueError:  # "https://[bad/"; a lone surrogate UTF-8 cannot encode
        return None


def _port(parts) -> int:
    """htsfetch.c origin_of: the explicit port, else the scheme default, which is also what a
    port out of range (1-65535) or not a number gets; never a ValueError."""
    default = 443 if parts.scheme == "https" else 80
    try:
        return parts.port or default
    except ValueError:
        return default


def _fetch_site(referer: str | None, scheme: str, host: str) -> str:
    """Sec-Fetch-Site of a request from page `referer` (R16, htsfetch.c hts_fetch_site_of)."""
    if not referer:
        return "none"
    a, b = urlsplit(referer), urlsplit(f"{scheme}://{host}")
    if (a.scheme == "https") != (b.scheme == "https"):
        return "cross-site"
    if a.hostname == b.hostname:
        return "same-origin" if _port(a) == _port(b) else "same-site"
    return "same-site" if _site_key(a.hostname or "") == _site_key(b.hostname or "") \
        else "cross-site"


def site_of(page: str | None, url: str) -> str:
    """Sec-Fetch-Site of a request for `url` made from `page` (htsfetch.c hts_fetch_site_of)."""
    parts = drop_userinfo(urlsplit(url))
    return _fetch_site(_referer_value(page), parts.scheme, parts.netloc)


VALIDATOR_MAX = 64  # htslib.c treathead_opt keeps an ETag or a date only under 64 characters


def response_validators(headers: dict[str, str]) -> tuple[str | None, str | None]:
    """(ETag, Last-Modified) of a response as HTTrack records them for its update mode
    (htslib.c:1632-1653): each only under 64 characters, and the Date standing for a
    missing or oversized Last-Modified. `headers` has lowercased names."""
    def kept(name: str) -> str | None:
        value = (headers.get(name) or "").strip()
        return value if value and len(value) < VALIDATOR_MAX else None
    return kept("etag"), kept("last-modified") or kept("date")


def conditional_headers(etag, last_modified) -> tuple[tuple[str, str], ...]:
    """Revalidation headers for a file recorded with these validators (htsback.c:2575-2601):
    If-None-Match and If-Modified-Since, or the one whose validator exists. A value that is
    not printable ASCII under 64 characters (an edited manifest) is never sent."""
    def ok(value) -> bool:
        return (isinstance(value, str) and 0 < len(value) < VALIDATOR_MAX and value.isascii()
                and value.isprintable())
    return tuple((name, value) for name, value in (("If-None-Match", etag),
                                                  ("If-Modified-Since", last_modified))
                 if ok(value))


def request_headers(policy: HttrackPolicy, host: str, *, kind: str, referer: str | None,
                    scheme: str, meta: FetchMeta = NAVIGATION,
                    validators: tuple[tuple[str, str], ...] = ()) -> list[tuple[str, str]]:
    """Headers in HTTrack's exact order (htslib.c). kind: robots | navigate | linked;
    `meta` is the link's fetch metadata (robots requests send none); `validators`
    (conditional_headers) go first, where http_sendhead writes its xsend lines."""
    if kind not in ("robots", "navigate", "linked"):
        raise ValueError(f"unknown request kind: {kind!r}")
    secure, agent = scheme == "https", policy.user_agent
    # htslib.c fetch_meta_sent: -%Q on, a classified link, to a trustworthy origin, with a
    # browser UA; the browser tables go with it (htslib.c:1002-1004)
    sent = (policy.browser_headers and kind != "robots" and bool(meta.dest)
            and _trustworthy(scheme, host) and agent.startswith("Mozilla/5.0 "))
    family = browser_family(agent) if sent else None
    referer = _referer_value(referer)
    h: dict[str, str] = {}
    if kind != "robots" and referer and (secure or urlsplit(referer).scheme != "https"):
        h["Referer"] = referer  # never an https referer to an http URL
    h.update({"Connection": "keep-alive", "Host": host})
    # client hints: over https only, beside the User-Agent they describe (htslib.c:1213-1235)
    hints = client_hints(agent) if policy.browser_headers and secure else None
    if hints is not None:
        h.update(zip(_CH, (hints[0], "?1" if hints[1] else "?0", hints[2])))
    if sent and secure and meta.mode == "navigate":  # hts_fetch_is_navigation
        h["Upgrade-Insecure-Requests"] = "1"
    if agent:
        h["User-Agent"] = agent
    h["Accept"] = BROWSER_ACCEPT[family].get(meta.dest, ACCEPT) if family else ACCEPT
    if sent:
        h.update({"Sec-Fetch-Site": meta.site or _fetch_site(referer, scheme, host),
                  "Sec-Fetch-Mode": meta.mode})
        if meta.user:
            h["Sec-Fetch-User"] = "?1"
        h["Sec-Fetch-Dest"] = meta.dest
    h["Accept-Language"] = BROWSER_ACCEPT_LANGUAGE if family else ACCEPT_LANGUAGE
    h["Accept-Encoding"] = accept_encoding(secure)
    order = _ORDERS[(family, meta.mode == "navigate") if family == "chrome" else family]
    # HTTrack -%X: a user line replaces the engine's own of the same name, robots.txt included
    return merge_headers([*validators, *((name, h[name]) for name in order if name in h)],
                         policy.headers)


def make_ssl_context() -> ssl.SSLContext:
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.set_ciphers("DEFAULT")
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.options |= ssl.OP_ALL
    ctx.load_default_certs()
    return ctx


def warn_if_old_openssl() -> bool:
    if ssl.OPENSSL_VERSION_INFO >= (3, 5):
        return False
    logger.warning(
        "OpenSSL %s < 3.5: the TLS handshake will not match HTTrack's and some "
        "CDNs may reject it. See README section \"Downloader profiles\".",
        ssl.OPENSSL_VERSION)
    return True
