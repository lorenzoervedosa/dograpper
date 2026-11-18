"""Wrapper for wget --mirror command."""

import os
import re
import subprocess
import logging
import tempfile
import time
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from pathlib import Path
from urllib.parse import unquote, urlsplit

from dograpper.lib.url_filter import UrlFilters, rule_regex
from dograpper.utils.dep_resolver import resolve_wget
from dograpper.utils.redact import neutralize_controls, redact_url

logger = logging.getLogger(__name__)

BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
BROWSER_HEADERS = {
    "Accept-Language": "en-US,en;q=0.9",
}

# The text extension set callers default to. When this exact set is requested,
# we translate it into a binary --reject denylist (see _content_filter_args)
# instead of an --accept allowlist, so that extensionless "pretty URLs" survive.
DEFAULT_TEXT_EXTENSIONS = ("html", "md", "txt")

# Binary/asset extensions that are never useful as LLM text context. Used as a
# wget --reject denylist so that extensionless pretty URLs are still followed.
ASSET_REJECT_EXTENSIONS = (
    "png,jpg,jpeg,gif,svg,webp,ico,bmp,tiff,"
    "css,js,mjs,map,"
    "woff,woff2,ttf,eot,otf,"
    "pdf,zip,gz,tar,bz2,7z,rar,"
    "mp4,webm,mov,avi,mp3,wav,ogg,"
    "exe,dmg,bin,wasm"
)


def _content_filter_args(include_extensions: str) -> List[str]:
    """Build wget content-filter args (``--accept`` / ``--reject``).

    An ``--accept`` allowlist silently rejects extensionless *pretty URLs*
    (e.g. ``.../README``, ``.../01-Test_Name``) emitted by static-site
    generators such as Jekyll / GitHub Pages: wget matches the allowlist
    against the URL's filename suffix, and these URLs have none, so they are
    dropped *before* download (``--adjust-extension`` never runs). On sites
    like the OWASP WSTG this fetched only the directory-index pages and missed
    the bulk of the content.

    To fetch those documents while still skipping binary assets, the default
    text extension set is translated into a binary ``--reject`` denylist:
    pretty URLs and HTML/MD/TXT pass, images/CSS/JS are dropped. A caller that
    narrows the set to anything other than the text default keeps the strict
    ``--accept`` allowlist as an explicit escape hatch.
    """
    if not include_extensions:
        return []
    normalized = {
        ext.strip().lstrip(".").lower()
        for ext in include_extensions.split(",")
        if ext.strip()
    }
    if normalized == set(DEFAULT_TEXT_EXTENSIONS):
        return [f"--reject={ASSET_REJECT_EXTENSIONS}"]
    return [f"--accept={include_extensions}"]


def url_filter_args(filters: UrlFilters | None, url: str) -> List[str]:
    """wget's scope for a crawl from `url` under the --filter rules.

    No +rule: ``--no-parent``, plus the -rules as ``--reject-regex``. A +rule lifts
    ``--no-parent``; the start directory then becomes HTTrack's implicit first rule,
    ``+<host>/<directory>*`` (htswizard.c), so links no rule matches keep that scope.
    wget takes a link that matches ``--accept-regex`` and not ``--reject-regex``,
    which says exactly what the rules say only when no +rule follows a -rule (after
    the last bare ``*`` rule, which overrides every rule before it); other orders
    raise ValueError.
    """
    rules = list(filters.rules) if filters is not None else []
    if not any(accepts for accepts, _, _ in rules):
        reject = "|".join(rx for _, _, rx in rules)
        return ["--no-parent"] + ([f"--reject-regex={reject}"] if reject else [])
    parts = urlsplit(url)
    directory = parts.path[:parts.path.rfind("/") + 1] or "/"
    rules.insert(0, (True, None, rule_regex(parts.netloc.rpartition("@")[2] + directory + "*")))
    stars = [i for i, (_, pattern, _) in enumerate(rules) if pattern == "*"]
    if stars:
        rules = rules[stars[-1]:]
        while rules and not rules[0][0]:  # after "-*", -rules before the first +rule change nothing
            rules.pop(0)
    first_refusal = next((i for i, rule in enumerate(rules) if not rule[0]), len(rules))
    late = next((rule for rule in rules[first_refusal:] if rule[0]), None)
    if late is not None:
        raise ValueError(
            f"under --downloader wget, '+{late[1]}' follows '-{rules[first_refusal][1]}': "
            "wget's --accept-regex/--reject-regex cannot let a +rule override an earlier "
            "-rule. Put the -rules after the +rules (they then win), or start with '-*'")
    accept = "|".join(rx for accepts, _, rx in rules if accepts)
    reject = "|".join(rx for accepts, _, rx in rules if not accepts)
    if not accept:  # "-*" with no +rule after it: only the start URL is fetched
        return ["--reject-regex=.*"]
    return [f"--accept-regex={accept}"] + ([f"--reject-regex={reject}"] if reject else [])


def _record_refused(log_path: str, filters: UrlFilters) -> None:
    """Re-decide each link wget's regexes refused (its --rejected-log) so that only the
    ones a rule refused land in ``filters.excluded``; the others were outside the scope."""
    with open(log_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            reason, _, rest = line.partition("\t")
            if reason == "REGEX":
                filters.decide(unquote(rest.split("\t", 1)[0]))


MAX_SHOWN_FAILURES = 5

# wget prints "--YYYY-MM-DD HH:MM:SS--  <URL>" per request and later
# "YYYY-MM-DD HH:MM:SS ERROR <code>: <message>." when the server refuses it, or
# a line naming the file it saved or found up to date. A redirect it follows
# prints "Location: <URL> [following]" and, on the next line, a new request.
_REQUEST_LINE = re.compile(r"^--\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}--\s+(\S+)")
_ERROR_LINE = re.compile(r"\bERROR (\d{3}): ")
_FOLLOWING_LINE = re.compile(r"^Location: .* \[following\]$")
_FILE_LINE = re.compile(
    r"^(?:Saving to: |File |Server file no newer than local file )(\u2018.*\u2019|'.*')"
    r"(?: not modified on server\. Omitting download\.| -- not retrieving\.)?$")
# gnulib quotearg: \\, the closing quote and, outside UTF-8 locales, every
# non-ASCII byte (as \ooo) are backslash-escaped inside the quotes.
_QUOTE_ESCAPE = re.compile(rb"\\([0-7]{3}|.)", re.DOTALL)

# wget localizes these lines; LANGUAGE=C makes gettext return the untranslated msgid and leaves LC_CTYPE (IRI encoding) alone.
_WGET_ENV = {**os.environ, "LANGUAGE": "C"}


@dataclass
class WgetFailure:
    url: str
    status: int


@dataclass
class WgetResult:
    success: bool
    output_dir: str
    files_downloaded: List[str]
    errors: List[str]
    files_skipped: int = 0
    failed: List[WgetFailure] = field(default_factory=list)
    # Saved file, as wget printed its path -> URL requested for it.
    urls: Dict[str, str] = field(default_factory=dict)


def _unquote(quoted: str) -> str:
    raw = _QUOTE_ESCAPE.sub(
        lambda m: bytes([int(m.group(1), 8)]) if len(m.group(1)) == 3 else m.group(1),
        quoted[1:-1].encode())
    return os.fsdecode(raw)


class WgetLog:
    """wget's stderr, parsed one line at a time as wget prints it.

    Pairs each request URL with what became of it: ``failed`` holds the
    ``ERROR <code>`` failures and ``saved`` maps each file wget saved, or found
    up to date, to the URL requested for it: the first of a redirect chain,
    never one a server handed back (it may carry a signed token).
    """

    def __init__(self):
        self.failed: List[WgetFailure] = []
        self.saved: Dict[str, str] = {}
        self._current = self._requested = None
        self._following = False

    def feed(self, line: str) -> None:
        request = _REQUEST_LINE.match(line)
        if request:
            self._current = request.group(1)
            if not self._following:
                self._requested = self._current
            self._following = False
            return
        self._following = bool(_FOLLOWING_LINE.match(line))
        kept = _FILE_LINE.match(line)
        if kept and self._requested:
            self.saved[_unquote(kept.group(1))] = self._requested
            return
        error = _ERROR_LINE.search(line)
        # A missing robots.txt is routine, not a failed page.
        if error and self._current and not self._current.endswith("/robots.txt"):
            self.failed.append(WgetFailure(self._current, int(error.group(1))))


def parse_wget_log(stderr: str) -> Tuple[List[WgetFailure], Dict[str, str]]:
    """``WgetLog`` over a whole log: the failures and saved file -> URL requested."""
    log = WgetLog()
    for line in stderr.splitlines():
        log.feed(line)
    return log.failed, log.saved


def _run_wget(cmd: List[str], log: WgetLog) -> int:
    """Run wget, feeding its stderr to ``log`` line by line while it runs. wget prints
    nothing on stdout here (no ``-O -``), so stdout goes to DEVNULL: the only pipe is
    read to EOF and cannot fill up and stall wget."""
    with subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True,
                          errors="replace", env=_WGET_ENV) as proc:
        for line in proc.stderr:
            log.feed(line)
    return proc.returncode


def format_failures(failed: List[WgetFailure], verbose: bool) -> List[str]:
    """Summary lines for the failed URLs: first MAX_SHOWN_FAILURES, all with verbose."""
    if not failed:
        return []
    shown = failed if verbose else failed[:MAX_SHOWN_FAILURES]
    note = "" if len(shown) == len(failed) else f" (first {len(shown)} shown)"
    lines = [f"Failed: {len(failed)} URLs{note}"]
    lines.extend(neutralize_controls(f"  {redact_url(f.url)}: {f.status}") for f in shown)
    return lines

def run_wget_mirror(
    url: str,
    output_dir: str,
    depth: int = 0,
    delay: int = 0,
    include_extensions: str = "html,md,txt",
    incremental: bool = False,
    filters: UrlFilters | None = None,
) -> WgetResult:
    """Run wget --mirror with the specified options. URLs the --filter rules refused are
    recorded in ``filters.excluded``."""
    
    # Check if wget is installed
    wget_bin = resolve_wget()
    try:
        subprocess.run([wget_bin, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except FileNotFoundError:
        raise RuntimeError("wget is required. Install with: brew install wget (macOS) or apt install wget (Linux)")

    cmd = [wget_bin]
    cmd.extend(["--timestamping", "--recursive"] if incremental else ["--mirror"])
    cmd.extend([
        "--convert-links",
        "--adjust-extension",
        "--page-requisites",
        f"--directory-prefix={output_dir}",
        f"--user-agent={BROWSER_UA}",
    ])
    cmd.extend(url_filter_args(filters, url))

    for header_name, header_value in BROWSER_HEADERS.items():
        cmd.append(f"--header={header_name}: {header_value}")

    if depth > 0:
        cmd.append(f"--level={depth}")
    
    if delay > 0:
        delay_seconds = delay / 1000.0
        cmd.append(f"--wait={delay_seconds}")
    
    cmd.extend(_content_filter_args(include_extensions))

    rejected_log = None
    if filters is not None and filters.rules:
        fd, rejected_log = tempfile.mkstemp(suffix=".rejected.tsv")
        os.close(fd)
        cmd.append(f"--rejected-log={rejected_log}")

    cmd.append(url)

    max_retries = 3
    attempt = 0
    success = False
    errors = []
    failed: List[WgetFailure] = []
    saved: Dict[str, str] = {}

    try:
        while attempt < max_retries and not success:
            attempt += 1
            logger.info(f"Running wget (attempt {attempt}/{max_retries}): {' '.join(cmd)}")
        
            log = WgetLog()
            returncode = _run_wget(cmd, log)
            saved.update(log.saved)  # a failed attempt's files are on disk too
        
            if returncode == 0:
                success = True
            elif returncode == 8:
                logger.warning("wget returned 8 (Server error). Treating as partial success.")
                success = True
                errors.append("Server error on some URLs (exit code 8)")
                failed = log.failed
            else:
                logger.error(f"wget failed with exit code {returncode}")
                errors.append(f"Attempt {attempt} failed with exit code {returncode}")
                if attempt < max_retries:
                    backoff_time = 2 ** attempt
                    logger.info(f"Retrying in {backoff_time} seconds...")
                    time.sleep(backoff_time)
            
        if rejected_log and success:
            _record_refused(rejected_log, filters)
    finally:
        if rejected_log:
            os.unlink(rejected_log)

    files_downloaded = []
    if success:
        outpath = Path(output_dir)
        if outpath.exists():
            files_downloaded = [str(p) for p in outpath.rglob('*') if p.is_file()]

    return WgetResult(
        success=success,
        output_dir=output_dir,
        files_downloaded=files_downloaded,
        errors=errors,
        failed=failed,
        urls=saved,
    )


def run_wget_urls(
    urls: List[str],
    output_dir: str,
    delay: int = 0,
    include_extensions: str = "html,md,txt",
) -> WgetResult:
    """Download an explicit URL list via `wget -i <file>`.

    Always uses `--timestamping` so that `_compute_stats` mtime-diff semantics
    work correctly on both first-run and subsequent-run invocations.
    """
    if not urls:
        return WgetResult(success=True, output_dir=output_dir, files_downloaded=[], errors=[])

    wget_bin = resolve_wget()
    try:
        subprocess.run([wget_bin, "--version"], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
    except FileNotFoundError:
        raise RuntimeError("wget is required. Install with: brew install wget (macOS) or apt install wget (Linux)")

    url_list_file = tempfile.NamedTemporaryFile(
        mode="w", suffix=".urls.txt", delete=False, encoding="utf-8"
    )
    try:
        for u in urls:
            url_list_file.write(u + "\n")
        url_list_file.close()

        cmd = [
            wget_bin,
            "--timestamping",
            "--convert-links",
            "--adjust-extension",
            "--page-requisites",
            "--no-parent",
            f"--directory-prefix={output_dir}",
            f"--user-agent={BROWSER_UA}",
            "-i", url_list_file.name,
        ]
        for header_name, header_value in BROWSER_HEADERS.items():
            cmd.append(f"--header={header_name}: {header_value}")

        if delay > 0:
            cmd.append(f"--wait={delay / 1000.0}")
        cmd.extend(_content_filter_args(include_extensions))

        max_retries = 3
        attempt = 0
        success = False
        errors: List[str] = []
        failed: List[WgetFailure] = []
        saved: Dict[str, str] = {}

        while attempt < max_retries and not success:
            attempt += 1
            logger.info(
                f"Running wget -i (attempt {attempt}/{max_retries}) "
                f"on {len(urls)} URLs: {' '.join(cmd)}"
            )
            log = WgetLog()
            returncode = _run_wget(cmd, log)
            saved.update(log.saved)
            if returncode == 0:
                success = True
            elif returncode == 8:
                logger.warning("wget -i returned 8 (Server error). Treating as partial success.")
                success = True
                errors.append("Server error on some URLs (exit code 8)")
                failed = log.failed
            else:
                logger.error(f"wget -i failed with exit code {returncode}")
                errors.append(f"Attempt {attempt} failed with exit code {returncode}")
                if attempt < max_retries:
                    time.sleep(2 ** attempt)

        files_downloaded: List[str] = []
        if success:
            outpath = Path(output_dir)
            if outpath.exists():
                files_downloaded = [str(p) for p in outpath.rglob("*") if p.is_file()]

        return WgetResult(
            success=success,
            output_dir=output_dir,
            files_downloaded=files_downloaded,
            errors=errors,
            failed=failed,
            urls=saved,
        )
    finally:
        try:
            Path(url_list_file.name).unlink()
        except OSError:
            pass
