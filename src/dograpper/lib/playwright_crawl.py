"""Headless crawler using playwright."""

from dograpper.utils import dep_resolver  # noqa: F401 — triggers ensure_playwright_browsers_path()

import os
import logging
import time
from html.parser import HTMLParser
from urllib.parse import urlparse, urljoin
from dataclasses import dataclass, field
from typing import Any, Dict, List
from pathlib import Path

from dograpper.lib.url_filter import UrlFilters

logger = logging.getLogger(__name__)

@dataclass
class CrawlResult:
    success: bool
    output_dir: str
    files_downloaded: List[str]
    errors: List[str]
    files_skipped: int = 0
    # Saved file -> URL requested for it (never where a redirect led).
    urls: Dict[str, str] = field(default_factory=dict)


class _Hrefs(HTMLParser):
    """``<a href>`` values of a page saved by an earlier run."""

    def __init__(self):
        super().__init__()
        self.hrefs: List[str] = []

    def handle_starttag(self, tag, attrs):
        href = dict(attrs).get("href") if tag == "a" else None
        if href:
            self.hrefs.append(href)


def run_playwright_crawl(
    url: str,
    output_dir: str,
    depth: int = 0,
    delay: int = 0,
    include_extensions: str = "html,md,txt",
    manifest_data: Any = None,
    seed_urls: List[str] | None = None,
    filters: UrlFilters | None = None,
) -> CrawlResult:
    """Crawl SPAs using playwright.

    Hydration is bounded (domcontentloaded 10s + a[href] wait 5s + 500ms grace,
    worst-case 15.5s) to avoid the `networkidle`-pinned 30s stalls observed
    against Mintlify-class SPAs.

    `seed_urls` (optional) pre-seeds the crawl queue so the download cascade
    can feed in URLs discovered by llms.txt/sitemap layers, skipping the
    link-graph discovery phase entirely when we already know the targets.

    `filters` (optional) drops the links its --filter rules refuse, recording them
    in `filters.excluded`.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise RuntimeError("playwright is required for SPA crawling. Install with: uv add playwright && playwright install chromium")

    parsed_initial = urlparse(url)
    base_domain = parsed_initial.netloc

    visited = set()
    to_visit: List[tuple[str, int]] = [(url, 0)]
    if seed_urls:
        for seed in seed_urls:
            if seed != url:
                to_visit.append((seed, 0))
    files_downloaded = []
    urls: Dict[str, str] = {}
    errors = []
    files_skipped = 0
    
    extensions = [ext.strip().lower() for ext in include_extensions.split(',') if ext.strip()]

    def follow(links, current_url, current_depth):
        for link in links:
            parsed_link = urlparse(link)
            if parsed_link.netloc == base_domain or not parsed_link.netloc:
                absolute_link = urljoin(current_url, link)
                
                # Strip fragments
                absolute_link = urlparse(absolute_link)._replace(fragment="").geturl()
                
                # a link past --depth is dropped later anyway: not a filter decision
                within_depth = depth == 0 or current_depth < depth
                if absolute_link not in visited and not (
                        within_depth and filters is not None
                        and filters.decide(absolute_link) is False):
                    to_visit.append((absolute_link, current_depth + 1))
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        
        while to_visit:
            current_url, current_depth = to_visit.pop(0)
            
            if current_url in visited:
                continue
                
            if depth > 0 and current_depth > depth:
                continue
                
            visited.add(current_url)
            
            if current_url != url and delay > 0:
                time.sleep(delay / 1000.0)
                
            # Check manifest caching
            skip_download = False
            if manifest_data:
                # Find entry by URL
                for rel_key, entry in manifest_data.files.items():
                    if entry.url == current_url:
                        # Prefer the stored on-disk path (set by build_manifest)
                        # and fall back to the entry key for legacy manifests
                        # where the key itself was the filesystem path.
                        local_rel = getattr(entry, 'local_path', None) or rel_key
                        expected_full_path = os.path.join(output_dir, local_rel)
                        if os.path.exists(expected_full_path):
                            logger.debug(f"Skipping (cached): {current_url}")
                            files_skipped += 1
                            files_downloaded.append(expected_full_path)
                            skip_download = True
                            # its links still lead on, or the crawl would end here
                            hrefs = _Hrefs()
                            with open(expected_full_path, encoding='utf-8', errors='replace') as f:
                                hrefs.feed(f.read())
                            follow(hrefs.hrefs, current_url, current_depth)
                        break
                        
            if skip_download:
                continue
                
            logger.info(f"Downloading: {current_url}")
            
            try:
                # Bounded hydration: 10s DOM + 5s selector wait + 500ms grace
                # (worst case 15.5s). Replaces `networkidle` which can hang
                # indefinitely on Mintlify-class SPAs whose RUM beacons keep
                # the network busy.
                page.goto(current_url, wait_until="domcontentloaded", timeout=10_000)
                try:
                    page.wait_for_selector("a[href]", timeout=5_000)
                except Exception as hydrate_err:
                    logger.debug(f"hydration: a[href] wait timed out for {current_url}: {hydrate_err}")
                page.wait_for_timeout(500)
                content = page.content()
                
                # Determine file path
                parsed_current = urlparse(current_url)
                path = parsed_current.path
                if not path or path.endswith('/'):
                    path += 'index.html'
                elif not any(path.endswith(f".{ext}") for ext in extensions):
                    path += '.html' # default to html for SPAs
                    
                path = path.lstrip('/')
                
                # Create directory and save
                full_path = os.path.join(output_dir, parsed_initial.netloc, path)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                
                with open(full_path, 'w', encoding='utf-8') as f:
                    f.write(content)
                    
                files_downloaded.append(full_path)
                urls[full_path] = current_url
                
                # Extract links
                links = page.evaluate('''() => {
                    return Array.from(document.querySelectorAll('a[href]')).map(a => a.href);
                }''')
                follow(links, current_url, current_depth)
                            
            except Exception as e:
                logger.error(f"Error crawling {current_url}: {e}")
                errors.append(f"Error crawling {current_url}: {e}")
                
        browser.close()
        
    return CrawlResult(
        success=True,
        output_dir=output_dir,
        files_downloaded=files_downloaded,
        errors=errors,
        files_skipped=files_skipped,
        urls=urls,
    )
