"""HTTrack 3.51 request policy: clamps, wire-identical headers, TLS context."""

import functools
import importlib
import ipaddress
import logging
import ssl
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from urllib.parse import urlsplit

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

MAX_CONNECTIONS = 8
MAX_CONN_RATE = 5.0
MAX_BANDWIDTH = 10_000_000
ZSTD_MAX_WINDOW = 8 * 1024 * 1024  # RFC 9659 lets a client refuse larger windows
MAX_RETRY_AFTER_CAP = 3600  # never lifted, even by disable_security_limits


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
                 disable_security_limits: bool = False) -> HttrackPolicy:
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
    if max_retry_after > MAX_RETRY_AFTER_CAP:
        logger.warning("max_retry_after=%s exceeds the hard maximum; clamped to %s",
                       max_retry_after, MAX_RETRY_AFTER_CAP)
        max_retry_after = MAX_RETRY_AFTER_CAP
    off = disable_security_limits
    return HttrackPolicy(
        user_agent=user_agent or DEFAULT_USER_AGENT,
        connections=_clamp("connections", connections, MAX_CONNECTIONS, off),
        max_conn_rate=_clamp("max_conn_rate", max_conn_rate, MAX_CONN_RATE, off),
        max_bandwidth=_clamp("max_bandwidth", max_bandwidth, MAX_BANDWIDTH, off),
        timeout=timeout,
        retries=retries,
        max_links=max_links,
        max_retry_after=max_retry_after,
        delay_ms=delay_ms,
        obey_robots=obey_robots,
    )


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


def _fetch_site(referer: str | None, scheme: str, host: str) -> str:
    """Sec-Fetch-Site of a request from page `referer` (R16, htsfetch.c hts_fetch_site_of)."""
    if not referer:
        return "none"
    a, b = urlsplit(referer), urlsplit(f"{scheme}://{host}")
    if (a.scheme == "https") != (b.scheme == "https"):
        return "cross-site"
    if a.hostname == b.hostname:
        default = 443 if b.scheme == "https" else 80
        return "same-origin" if (a.port or default) == (b.port or default) else "same-site"
    return "same-site" if _site_key(a.hostname or "") == _site_key(b.hostname or "") \
        else "cross-site"


def request_headers(policy: HttrackPolicy, host: str, *, kind: str, referer: str | None,
                    scheme: str = "https") -> list[tuple[str, str]]:
    """Headers in HTTrack's exact order (htslib.c). kind: robots | navigate | linked.
    scheme defaults to https, the scheme of the wire fixtures."""
    if kind not in ("robots", "navigate", "linked"):
        raise ValueError(f"unknown request kind: {kind!r}")
    secure = scheme == "https"
    # htslib.c fetch_meta_sent: navigations only, to a trustworthy origin, with a browser UA
    meta = (kind != "robots" and _trustworthy(scheme, host)
            and policy.user_agent.startswith("Mozilla/5.0 "))
    h: list[tuple[str, str]] = []
    if kind != "robots" and referer and (secure or urlsplit(referer).scheme != "https"):
        h.append(("Referer", referer))  # never an https referer to an http URL
    h += [("Connection", "keep-alive"), ("Host", host)]
    if meta and secure:
        h.append(("Upgrade-Insecure-Requests", "1"))
    h += [("User-Agent", policy.user_agent), ("Accept", ACCEPT)]
    if meta:
        h += [("Sec-Fetch-Site", _fetch_site(referer, scheme, host)),
              ("Sec-Fetch-Mode", "navigate"),
              ("Sec-Fetch-User", "?1"),
              ("Sec-Fetch-Dest", "document")]
    h += [("Accept-Language", ACCEPT_LANGUAGE), ("Accept-Encoding", accept_encoding(secure))]
    return h


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
