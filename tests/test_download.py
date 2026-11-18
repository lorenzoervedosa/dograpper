import os
import json
import tempfile
from unittest.mock import MagicMock, patch
import click
import pytest

from dograpper.lib.wget_mirror import run_wget_mirror
from dograpper.lib.spa_detector import is_spa
from dograpper.lib.manifest import Manifest, ManifestEntry, load_manifest, save_manifest, merge_manifests
from dograpper.lib.config_loader import load_config

def test_merge_manifests_basic():
    old = Manifest("http://localhost", "2020", {
        "A.md": ManifestEntry("a/b", 100, etag="e1"),
        "B.md": ManifestEntry("b/b", 200, etag="e2")
    })
    new = Manifest("http://localhost", "2021", {
        "B.md": ManifestEntry("b/b", 999), # changed size
        "C.md": ManifestEntry("c/c", 300)
    })
    
    merged = merge_manifests(old, new)
    
    assert "A.md" not in merged.files
    assert "B.md" in merged.files
    assert "C.md" in merged.files
    
    assert merged.files["B.md"].etag is None # Size changed, etag lost
    assert merged.files["B.md"].size_bytes == 999
    assert merged.last_run == "2021"

def test_merge_manifests_preserves_etag():
    old = Manifest("http://localhost", "2020", {
        "A.md": ManifestEntry("a/b", 100, etag="e1", last_modified="lm")
    })
    new = Manifest("http://localhost", "2021", {
        "A.md": ManifestEntry("a/b", 100) # same size
    })
    
    merged = merge_manifests(old, new)
    assert merged.files["A.md"].etag == "e1"
    assert merged.files["A.md"].last_modified == "lm"

def test_merge_manifests_none_old():
    new = Manifest("http://localhost", "2021", {"A.md": ManifestEntry("a/b", 100)})
    merged = merge_manifests(None, new)
    assert "A.md" in merged.files

def test_wget_mirror_command_build():
    with patch('subprocess.run') as mock_run:
        # Mock successful wget
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""
        
        run_wget_mirror('http://example.com', './out', depth=2, delay=1500, include_extensions="html,md")
        
        args = mock_run.call_args[0][0]
        assert os.path.basename(args[0]) == "wget"
        assert "--mirror" in args
        assert "--timestamping" not in args
        assert "--convert-links" in args
        assert "--level=2" in args
        assert "--wait=1.5" in args
        assert "--accept=html,md" in args
        assert "--directory-prefix=./out" in args
        assert "http://example.com" in args

def test_wget_incremental_flag():
    with patch('subprocess.run') as mock_run:
        mock_run.return_value.returncode = 0
        
        run_wget_mirror('http://example.com', './out', incremental=True)
        args = mock_run.call_args[0][0]

        assert os.path.basename(args[0]) == "wget"
        assert "--timestamping" in args
        assert "--mirror" not in args
        assert "--recursive" in args
        assert "--page-requisites" in args
        assert "--convert-links" in args

def test_wget_non_incremental():
    with patch('subprocess.run') as mock_run:
        mock_run.return_value.returncode = 0
        
        run_wget_mirror('http://example.com', './out', incremental=False)
        args = mock_run.call_args[0][0]
        
        assert "--mirror" in args
        assert "--timestamping" not in args

def test_wget_urls_uses_input_file_and_flags():
    from dograpper.lib.wget_mirror import BROWSER_UA, run_wget_urls
    with patch('subprocess.run') as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""

        with tempfile.TemporaryDirectory() as d:
            res = run_wget_urls(
                ["https://site.io/a", "https://site.io/b"],
                d,
                delay=500,
                include_extensions="html,md",
            )
            assert res.success

        # Last call must be the actual wget invocation (not the --version probe).
        # Find the call whose argv starts with wget (basename check tolerates full paths).
        wget_calls = [c for c in mock_run.call_args_list if c[0] and os.path.basename(c[0][0][0]) == "wget" and "-i" in c[0][0]]
        assert wget_calls, "no wget -i invocation captured"
        args = wget_calls[-1][0][0]

        # M-1: --no-parent required
        assert "--no-parent" in args

        # M-3: always --timestamping, never --no-clobber
        assert "--timestamping" in args
        assert "--no-clobber" not in args

        # UA + Accept-Language
        assert f"--user-agent={BROWSER_UA}" in args
        assert any(a.startswith("--header=Accept-Language:") for a in args)

        # -i URL-list
        assert "-i" in args
        i_idx = args.index("-i")
        url_list_path = args[i_idx + 1]
        assert url_list_path.endswith(".urls.txt")

        # delay + extensions
        assert "--wait=0.5" in args
        assert "--accept=html,md" in args


def test_wget_urls_empty_list_noops():
    from dograpper.lib.wget_mirror import run_wget_urls
    with patch('subprocess.run') as mock_run:
        mock_run.return_value.returncode = 0
        with tempfile.TemporaryDirectory() as d:
            res = run_wget_urls([], d)
        assert res.success
        assert res.files_downloaded == []
        # No wget call should have been made at all
        wget_calls = [c for c in mock_run.call_args_list if c[0] and os.path.basename(c[0][0][0]) == "wget"]
        assert not wget_calls


def test_wget_urls_partial_success_on_exit_8():
    from dograpper.lib.wget_mirror import run_wget_urls
    with patch('subprocess.run') as mock_run:
        def side_effect(*args, **kwargs):
            result = MagicMock()
            # first call is --version probe, subsequent are the real run
            if "--version" in args[0]:
                result.returncode = 0
            else:
                result.returncode = 8
            result.stdout = ""
            result.stderr = ""
            return result
        mock_run.side_effect = side_effect

        with tempfile.TemporaryDirectory() as d:
            res = run_wget_urls(["https://site.io/a"], d)
        assert res.success is True
        assert any("Server error" in e for e in res.errors)


def test_wget_mirror_passes_browser_ua():
    from dograpper.lib.wget_mirror import BROWSER_UA
    with patch('subprocess.run') as mock_run:
        mock_run.return_value.returncode = 0

        run_wget_mirror('http://example.com', './out')
        args = mock_run.call_args[0][0]

        assert f"--user-agent={BROWSER_UA}" in args
        assert any(a.startswith("--header=Accept-Language:") for a in args)


def test_wget_mirror_ua_includes_chrome():
    from dograpper.lib.wget_mirror import BROWSER_UA
    assert "Chrome/" in BROWSER_UA
    assert "Mozilla/5.0" in BROWSER_UA


# --- --filter rules on wget --mirror (#96) ---

SEED = "https://pzwiki.net/w/index.php?title=Category:Lua_events"


def _wget_accepts(args, url):
    """wget's own decision for a child link (recur.c download_child): no-parent, then regexes."""
    import re
    from urllib.parse import urlsplit
    if "--no-parent" in args and not urlsplit(url).path.startswith("/w/"):
        return False
    regex = {a.split("=", 1)[0]: a.split("=", 1)[1] for a in args if a.startswith("--") and "-regex=" in a}
    if "--accept-regex" in regex and not re.search(regex["--accept-regex"], url):
        return False
    return not ("--reject-regex" in regex and re.search(regex["--reject-regex"], url))


@pytest.mark.parametrize("rules", [
    [],
    ["-*Special:*", "-*action=*"],
    ["+pzwiki.net/wiki/On*"],
    ["-*", "+pzwiki.net/wiki/On*"],
    ["-*", "+pzwiki.net/wiki/On*", "-*OnTick*"],
    ["+*", "-*/wiki/Category:*"],
    ["+pzwiki.net/wiki/*", "-*", "+*/wiki/OnLoad"],
    ["-*", "-*/w/*", "+*/wiki/On*"],
])
def test_wget_filter_args_decide_like_the_rules(rules):
    """The --accept-regex/--reject-regex wget gets accept exactly what the rules accept,
    and what no rule matches stays under --no-parent's scope (the start directory)."""
    from dograpper.lib.url_filter import UrlFilters
    from dograpper.lib.wget_mirror import url_filter_args
    filters = UrlFilters(rules)
    args = url_filter_args(filters, SEED)
    assert ("--no-parent" in args) is not any(r.startswith("+") for r in rules)
    for url in ["https://pzwiki.net/wiki/OnTick", "https://pzwiki.net/wiki/OnLoad",
                "https://pzwiki.net/wiki/Category:En", "https://pzwiki.net/wiki/Other",
                "https://pzwiki.net/w/index.php?title=Special:Random",
                "https://pzwiki.net/w/index.php?title=Category:Lua_events&action=edit",
                "https://pzwiki.net/w/load.php?modules=site"]:
        verdict = filters.decide(url)
        expected = url.startswith("https://pzwiki.net/w/") if verdict is None else verdict
        assert _wget_accepts(args, url) is expected, url


def test_wget_filter_args_refuse_a_plus_rule_after_a_minus_rule():
    import re
    from dograpper.lib.url_filter import UrlFilters
    from dograpper.lib.wget_mirror import url_filter_args
    with pytest.raises(ValueError, match=re.escape("'+*/wiki/On*' follows '-*Special:*'")):
        url_filter_args(UrlFilters(["-*Special:*", "+*/wiki/On*"]), SEED)


def test_wget_mirror_counts_only_urls_a_rule_refused(tmp_path):
    """wget's --rejected-log lists every regex refusal; only those a rule decided count."""
    from dograpper.lib.url_filter import UrlFilters
    rows = [
        ("REGEX", "https%3A//pzwiki.net/wiki/Category%3AEn"),       # refused by -*
        ("REGEX", "https%3A//pzwiki.net/wiki/Category%3AEn"),       # seen twice, counted once
        ("PARENT", "https%3A//pzwiki.net/wiki/Other"),              # not a filter decision
        ("REGEX", "https%3A//pzwiki.net/w/index.php?title=Special%3ARandom"),
    ]

    def fake_run(cmd, **kw):
        log = next((a.split("=", 1)[1] for a in cmd if a.startswith("--rejected-log=")), None)
        if log:  # not the --version probe
            with open(log, "w", encoding="utf-8") as f:
                f.write("REASON\tU_URL\tU_SCHEME\n")
                f.writelines(f"{reason}\t{url}\tSCHEME_HTTPS\n" for reason, url in rows)
        result = MagicMock()
        result.returncode, result.stdout, result.stderr = 0, "", ""
        return result

    filters = UrlFilters(["-*", "+pzwiki.net/wiki/On*"])
    with patch("subprocess.run", side_effect=fake_run):
        res = run_wget_mirror(SEED, str(tmp_path), filters=filters)
    assert res.success
    assert filters.excluded == {"https://pzwiki.net/wiki/Category:En",
                                "https://pzwiki.net/w/index.php?title=Special:Random"}
    assert not list(tmp_path.iterdir())  # the log is not left in the output


def test_wget_mirror_removes_the_rejected_log_when_wget_cannot_run(tmp_path, monkeypatch):
    from dograpper.lib.url_filter import UrlFilters
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))

    def fake_run(cmd, **kw):
        if any(a.startswith("--rejected-log=") for a in cmd):  # the mirror run, not the --version probe
            raise OSError("exec failed")
        result = MagicMock()
        result.returncode, result.stdout, result.stderr = 0, "", ""
        return result

    with patch("subprocess.run", side_effect=fake_run):
        with pytest.raises(OSError):
            run_wget_mirror(SEED, str(tmp_path / "out"), filters=UrlFilters(["-*Special:*"]))
    assert not list(tmp_path.glob("*.rejected.tsv"))


def test_wget_mirror_without_rules_adds_no_rejected_log():
    from dograpper.lib.url_filter import UrlFilters
    with patch('subprocess.run') as mock_run:
        mock_run.return_value.returncode = 0
        run_wget_mirror('http://example.com', './out', filters=UrlFilters())
        args = mock_run.call_args[0][0]
    assert "--no-parent" in args
    assert not any(a.startswith(("--rejected-log", "--accept-regex", "--reject-regex")) for a in args)


# --- Pretty-URL handling (issue: --accept dropped extensionless URLs) ---

def test_content_filter_args_default_uses_reject_denylist():
    """Default text set must become a binary --reject denylist, not an
    --accept allowlist, so extensionless pretty URLs are not dropped."""
    from dograpper.lib.wget_mirror import _content_filter_args

    args = _content_filter_args("html,md,txt")

    assert not any(a.startswith("--accept=") for a in args), \
        "default text set must not emit an --accept allowlist (drops pretty URLs)"
    reject = [a for a in args if a.startswith("--reject=")]
    assert len(reject) == 1
    assert "png" in reject[0]
    assert "css" in reject[0]
    assert "js" in reject[0]


def test_content_filter_args_default_order_independent():
    """Reordered / dot-prefixed default set is still treated as the text default."""
    from dograpper.lib.wget_mirror import _content_filter_args

    args = _content_filter_args(".txt, .HTML ,md")
    assert any(a.startswith("--reject=") for a in args)
    assert not any(a.startswith("--accept=") for a in args)


def test_content_filter_args_custom_keeps_accept_allowlist():
    """An explicitly narrowed set keeps the strict --accept escape hatch."""
    from dograpper.lib.wget_mirror import _content_filter_args

    args = _content_filter_args("html,md")
    assert args == ["--accept=html,md"]


def test_content_filter_args_empty_is_noop():
    from dograpper.lib.wget_mirror import _content_filter_args
    assert _content_filter_args("") == []


def test_wget_mirror_default_extensions_reject_not_accept():
    """Regression: a default mirror must reject binaries (denylist) so that
    pretty URLs like .../README and .../01-Test_Name are followed."""
    with patch('subprocess.run') as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""

        run_wget_mirror('http://example.com', './out')  # default include_extensions
        args = mock_run.call_args[0][0]

        assert not any(a.startswith("--accept=") for a in args)
        assert any(a.startswith("--reject=") and "png" in a for a in args)


def test_wget_urls_default_extensions_reject_not_accept():
    from dograpper.lib.wget_mirror import run_wget_urls
    with patch('subprocess.run') as mock_run:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = ""

        with tempfile.TemporaryDirectory() as d:
            run_wget_urls(["https://site.io/a"], d)  # default include_extensions

        wget_calls = [
            c for c in mock_run.call_args_list
            if c[0] and os.path.basename(c[0][0][0]) == "wget" and "-i" in c[0][0]
        ]
        assert wget_calls
        args = wget_calls[-1][0][0]
        assert not any(a.startswith("--accept=") for a in args)
        assert any(a.startswith("--reject=") and "png" in a for a in args)


def test_spa_detector_empty_shells():
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create an empty shell HTML
        with open(os.path.join(temp_dir, 'index.html'), 'w') as f:
            f.write('<html><body><div id="root"></div></body></html>')
            
        assert is_spa(temp_dir) is True

def test_spa_detector_small_sample_any_shell_is_spa():
    """N<5 branch: with few pages, a single empty shell flips the verdict to SPA."""
    with tempfile.TemporaryDirectory() as temp_dir:
        with open(os.path.join(temp_dir, 'index.html'), 'w') as f:
            f.write('<html><body><div id="root"></div></body></html>')
        with open(os.path.join(temp_dir, 'page.html'), 'w') as f:
            f.write(f'<html><body><p>{"B" * 300}</p></body></html>')
        # 2 files, 1 empty shell, 1 real content. N<5 → any shell wins.
        assert is_spa(temp_dir) is True


def test_spa_detector_small_sample_all_real_is_not_spa():
    with tempfile.TemporaryDirectory() as temp_dir:
        for i in range(3):
            with open(os.path.join(temp_dir, f'page{i}.html'), 'w') as f:
                f.write(f'<html><body><p>{"X" * 300}</p></body></html>')
        assert is_spa(temp_dir) is False


def test_spa_detector_tolerates_invalid_utf8():
    """Scraped HTML with invalid UTF-8 must not crash is_spa."""
    with tempfile.TemporaryDirectory() as temp_dir:
        # Write raw bytes that include invalid UTF-8 sequences alongside valid content.
        path = os.path.join(temp_dir, 'bad.html')
        with open(path, 'wb') as f:
            f.write(b'<html><body><p>')
            f.write(b'\xff\xfe\x80\x81')
            f.write(b'' + (b'A' * 300) + b'</p></body></html>')
        # Must not raise; real text present → not SPA (small sample, 0 shells).
        assert is_spa(temp_dir) is False


def test_spa_detector_real_content():
    with tempfile.TemporaryDirectory() as temp_dir:
        # Create HTML with real content (> 200 chars to bypass minimum)
        with open(os.path.join(temp_dir, 'about.html'), 'w') as f:
            content = "A" * 250
            f.write(f'<html><body><p>{content}</p></body></html>')
            
        assert is_spa(temp_dir) is False

def test_manifest_roundtrip():
    with tempfile.TemporaryDirectory() as temp_dir:
        manifest_path = os.path.join(temp_dir, 'manifest.json')
        original = Manifest(
            base_url="http://example.com",
            last_run="2025-01-01T00:00:00Z",
            files={
                "index.html": ManifestEntry(url="http://example.com/", size_bytes=100)
            }
        )
        save_manifest(original, manifest_path)
        loaded = load_manifest(manifest_path)
        
        assert loaded is not None
        assert loaded.base_url == original.base_url
        assert loaded.last_run == original.last_run
        assert "index.html" in loaded.files
        assert loaded.files["index.html"].size_bytes == 100

def test_manifest_missing_file():
    loaded = load_manifest("/path/that/does/not/exist.json")
    assert loaded is None

def test_config_loader_precedence():
    with tempfile.TemporaryDirectory() as temp_dir:
        config_path = os.path.join(temp_dir, 'config.json')
        with open(config_path, 'w') as f:
            json.dump({
                "download": {
                    "depth": 5,
                    "delay": 200
                }
            }, f)
            
        cli_params = {
            "depth": 2, # explicit CLI flag
            "delay": 0, # implicit default
            "output": "./out"
        }
        
        class FakeSource:
            def __init__(self, name):
                self.name = name

        class FakeContext:
            def __init__(self):
                self.params = cli_params
            
            def get_parameter_source(self, param_name):
                if param_name == "depth":
                    return FakeSource("COMMANDLINE")
                return FakeSource("DEFAULT")

        fake_ctx = FakeContext()
        merged = load_config(config_path, 'download', cli_params, fake_ctx)
        
        assert merged["depth"] == 2 # CLI explicit beat JSON
        assert merged["delay"] == 200 # JSON beat default
        assert merged["output"] == "./out" # default preserved if not in JSON

def test_playwright_skips_cached():
    import sys
    from unittest.mock import MagicMock
    
    mock_playwright = MagicMock()
    mock_sync_api = MagicMock()
    mock_sync = mock_sync_api.sync_playwright
    mock_p = mock_sync.return_value.__enter__.return_value
    mock_page = mock_p.chromium.launch.return_value.new_context.return_value.new_page.return_value
    
    sys.modules['playwright'] = mock_playwright
    sys.modules['playwright.sync_api'] = mock_sync_api
    
    try:
        # Manifest mapping http://target.com to index.html
        m = Manifest("http://target.com", "", {
            "index.html": ManifestEntry("http://target.com", 100)
        })
        
        with tempfile.TemporaryDirectory() as d:
            # File exists on disk
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write("content")
                
            from dograpper.lib.playwright_crawl import run_playwright_crawl
            res = run_playwright_crawl("http://target.com", d, manifest_data=m)
            
            # Assert goto was not called
            mock_page.goto.assert_not_called()
            assert res.files_skipped == 1
    finally:
        del sys.modules['playwright']
        del sys.modules['playwright.sync_api']

def test_playwright_follows_the_links_of_a_cached_page():
    """A page skipped as cached still leads to the pages it links to; otherwise
    an incremental crawl would stop at its first cached page."""
    import sys
    mock_sync_api = MagicMock()
    mock_p = mock_sync_api.sync_playwright.return_value.__enter__.return_value
    mock_page = mock_p.chromium.launch.return_value.new_context.return_value.new_page.return_value
    mock_page.content.return_value = "<html><body>next</body></html>"
    mock_page.evaluate.return_value = []
    sys.modules['playwright'] = MagicMock()
    sys.modules['playwright.sync_api'] = mock_sync_api
    try:
        m = Manifest("http://target.com", "", {
            "index.html": ManifestEntry("http://target.com", 100)})
        with tempfile.TemporaryDirectory() as d:
            with open(os.path.join(d, "index.html"), "w") as f:
                f.write('<html><body><a href="/next#top">n</a>'
                        '<a href="http://other.com/x">o</a></body></html>')
            from dograpper.lib.playwright_crawl import run_playwright_crawl
            res = run_playwright_crawl("http://target.com", d, manifest_data=m)
            assert [c.args[0] for c in mock_page.goto.call_args_list] == ["http://target.com/next"]
            assert res.files_skipped == 1
    finally:
        del sys.modules['playwright']
        del sys.modules['playwright.sync_api']


def test_playwright_bounded_hydration_uses_selector_wait():
    """Verify bounded-hydration ordering: goto → wait_for_selector('a[href]') → 500ms grace."""
    import sys
    from unittest.mock import MagicMock

    mock_playwright = MagicMock()
    mock_sync_api = MagicMock()
    mock_sync = mock_sync_api.sync_playwright
    mock_p = mock_sync.return_value.__enter__.return_value
    mock_page = mock_p.chromium.launch.return_value.new_context.return_value.new_page.return_value
    mock_page.content.return_value = "<html><body>hi</body></html>"
    mock_page.evaluate.return_value = []

    sys.modules['playwright'] = mock_playwright
    sys.modules['playwright.sync_api'] = mock_sync_api

    try:
        with tempfile.TemporaryDirectory() as d:
            from dograpper.lib.playwright_crawl import run_playwright_crawl
            run_playwright_crawl("http://target.com", d)

            mock_page.goto.assert_called_with(
                "http://target.com", wait_until="domcontentloaded", timeout=10_000
            )
            mock_page.wait_for_selector.assert_called_with("a[href]", timeout=5_000)
            mock_page.wait_for_timeout.assert_called_with(500)
    finally:
        del sys.modules['playwright']
        del sys.modules['playwright.sync_api']


def test_playwright_hydration_ignores_selector_timeout():
    """wait_for_selector timeout must not abort the crawl — page.content still collected."""
    import sys
    from unittest.mock import MagicMock

    mock_playwright = MagicMock()
    mock_sync_api = MagicMock()
    mock_sync = mock_sync_api.sync_playwright
    mock_p = mock_sync.return_value.__enter__.return_value
    mock_page = mock_p.chromium.launch.return_value.new_context.return_value.new_page.return_value
    mock_page.content.return_value = "<html><body>content</body></html>"
    mock_page.evaluate.return_value = []
    mock_page.wait_for_selector.side_effect = Exception("Timeout 5000ms")

    sys.modules['playwright'] = mock_playwright
    sys.modules['playwright.sync_api'] = mock_sync_api

    try:
        with tempfile.TemporaryDirectory() as d:
            from dograpper.lib.playwright_crawl import run_playwright_crawl
            res = run_playwright_crawl("http://target.com", d)
            assert res.success is True
            assert mock_page.content.called
    finally:
        del sys.modules['playwright']
        del sys.modules['playwright.sync_api']


def test_playwright_crawl_consumes_seed_urls():
    import sys
    from unittest.mock import MagicMock

    mock_playwright = MagicMock()
    mock_sync_api = MagicMock()
    mock_sync = mock_sync_api.sync_playwright
    mock_p = mock_sync.return_value.__enter__.return_value
    mock_page = mock_p.chromium.launch.return_value.new_context.return_value.new_page.return_value
    mock_page.content.return_value = "<html></html>"
    mock_page.evaluate.return_value = []

    sys.modules['playwright'] = mock_playwright
    sys.modules['playwright.sync_api'] = mock_sync_api

    try:
        with tempfile.TemporaryDirectory() as d:
            from dograpper.lib.playwright_crawl import run_playwright_crawl
            run_playwright_crawl(
                "http://target.com",
                d,
                seed_urls=["http://target.com/api", "http://target.com/guide"],
            )
            visited_urls = [c[0][0] for c in mock_page.goto.call_args_list]
            assert "http://target.com" in visited_urls
            assert "http://target.com/api" in visited_urls
            assert "http://target.com/guide" in visited_urls
    finally:
        del sys.modules['playwright']
        del sys.modules['playwright.sync_api']


def test_playwright_crawl_skips_links_the_filters_refuse():
    import sys
    from unittest.mock import MagicMock
    from dograpper.lib.url_filter import UrlFilters

    mock_sync_api = MagicMock()
    mock_p = mock_sync_api.sync_playwright.return_value.__enter__.return_value
    mock_page = mock_p.chromium.launch.return_value.new_context.return_value.new_page.return_value
    mock_page.content.return_value = "<html></html>"
    mock_page.evaluate.side_effect = [
        ["http://target.com/wiki/OnTick", "http://target.com/wiki/Category:En#top"],
        ["http://target.com/wiki/Deeper"],  # beyond --depth: not a filter decision
    ]

    sys.modules['playwright'] = MagicMock()
    sys.modules['playwright.sync_api'] = mock_sync_api
    try:
        with tempfile.TemporaryDirectory() as d:
            from dograpper.lib.playwright_crawl import run_playwright_crawl
            filters = UrlFilters(["-*", "+*/wiki/On*"])
            run_playwright_crawl("http://target.com/w/start", d, depth=1, filters=filters)
            visited_urls = [c[0][0] for c in mock_page.goto.call_args_list]
            assert visited_urls == ["http://target.com/w/start", "http://target.com/wiki/OnTick"]
            assert filters.excluded == {"http://target.com/wiki/Category:En"}
    finally:
        del sys.modules['playwright']
        del sys.modules['playwright.sync_api']


def test_playwright_redownloads_missing():
    import sys
    from unittest.mock import MagicMock
    
    mock_playwright = MagicMock()
    mock_sync_api = MagicMock()
    mock_sync = mock_sync_api.sync_playwright
    mock_p = mock_sync.return_value.__enter__.return_value
    mock_page = mock_p.chromium.launch.return_value.new_context.return_value.new_page.return_value
    mock_page.content.return_value = "<html><body>content</body></html>"
    mock_page.evaluate.return_value = []
    
    sys.modules['playwright'] = mock_playwright
    sys.modules['playwright.sync_api'] = mock_sync_api
    
    try:
        m = Manifest("http://target.com", "", {
            "index.html": ManifestEntry("http://target.com", 100)
        })
        
        with tempfile.TemporaryDirectory() as d:
            # DO NOT create index.html
            from dograpper.lib.playwright_crawl import run_playwright_crawl
            res = run_playwright_crawl("http://target.com", d, manifest_data=m)
            
            # Assert goto WAS called because file is missing (bounded hydration)
            mock_page.goto.assert_called_with(
                "http://target.com", wait_until="domcontentloaded", timeout=10_000
            )
            assert res.files_skipped == 0
    finally:
        del sys.modules['playwright']
        del sys.modules['playwright.sync_api']

def test_playwright_reports_the_url_of_each_saved_page():
    """The saved name drops the query; the URL recorded is the one requested,
    never where a redirect led (#94)."""
    import sys

    final = {"http://target.com/w/index.php?title=A": "http://target.com/w/index.php?title=A",
             "http://target.com/old": "http://target.com/new"}
    mock_sync_api = MagicMock()
    mock_p = mock_sync_api.sync_playwright.return_value.__enter__.return_value
    mock_page = mock_p.chromium.launch.return_value.new_context.return_value.new_page.return_value
    mock_page.content.return_value = "<html><body>content</body></html>"
    mock_page.evaluate.return_value = []

    def goto(url, **kwargs):
        mock_page.url = final[url]
    mock_page.goto.side_effect = goto

    sys.modules['playwright'] = MagicMock()
    sys.modules['playwright.sync_api'] = mock_sync_api
    try:
        with tempfile.TemporaryDirectory() as d:
            from dograpper.lib.playwright_crawl import run_playwright_crawl
            res = run_playwright_crawl("http://target.com/w/index.php?title=A", d,
                                       seed_urls=["http://target.com/old"])
            assert res.urls == {
                os.path.join(d, "target.com", "w/index.php.html"):
                    "http://target.com/w/index.php?title=A",
                os.path.join(d, "target.com", "old.html"): "http://target.com/old",
            }
    finally:
        del sys.modules['playwright']
        del sys.modules['playwright.sync_api']


from click.testing import CliRunner
from dograpper.commands.download import download
from dograpper.cli import cli

def test_download_wget_success():
    runner = CliRunner()
    with patch('subprocess.run') as mock_run:
        mock_run.return_value.returncode = 0
        
        with tempfile.TemporaryDirectory() as d:
            from dograpper.lib.wget_mirror import WgetResult
            paths = [os.path.join(d, f"p{i}.html") for i in range(3)]
            with patch('dograpper.commands.download.run_wget_mirror') as mock_wget:
                mock_wget.return_value = WgetResult(True, d, paths, [], 0)

                # Mock is_spa
                with patch('dograpper.commands.download.is_spa') as mock_is_spa:
                    mock_is_spa.return_value = False

                    for p in paths:
                        with open(p, "w") as f:
                            f.write("content")

                    manifest_path = os.path.join(d, ".dograpper-manifest.json")
                    res = runner.invoke(download, ['http://example.com', '-o', d, '--manifest', manifest_path])
                    assert res.exit_code == 0
                    assert "Download complete" in res.output
                    assert "Files downloaded: 3" in res.output
                    assert mock_wget.called

def test_download_spa_fallback(caplog):
    import logging
    caplog.set_level(logging.INFO)
    runner = CliRunner()
    
    with tempfile.TemporaryDirectory() as d:
        from dograpper.lib.wget_mirror import WgetResult
        from dograpper.lib.playwright_crawl import CrawlResult
        with patch('dograpper.commands.download.run_wget_mirror') as mock_wget:
            mock_wget.return_value = WgetResult(True, d, [], [], 0)
            
            with patch('dograpper.commands.download.is_spa') as mock_is_spa:
                mock_is_spa.return_value = True
                
                with patch('dograpper.commands.download.run_playwright_crawl') as mock_pw:
                    mock_pw.return_value = CrawlResult(True, d, [os.path.join(d, "index.html")], [], 0)
                    
                    with open(os.path.join(d, "index.html"), "w") as f:
                        f.write("content fallback")
                        
                    res = runner.invoke(download, ['http://example.com', '-o', d])
                    assert res.exit_code == 0
                    assert "SPA detected, falling back to playwright" in caplog.text
                    mock_pw.assert_called()

def test_download_headless_skips_wget():
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as d:
        from dograpper.lib.playwright_crawl import CrawlResult
        
        with patch('dograpper.commands.download.run_wget_mirror') as mock_wget:
            with patch('dograpper.commands.download.run_playwright_crawl') as mock_pw:
                mock_pw.return_value = CrawlResult(True, d, [os.path.join(d, "index.html")], [], 0)
                
                with open(os.path.join(d, "index.html"), "w") as f:
                    f.write("content")
                    
                res = runner.invoke(download, ['http://example.com', '-o', d, '--headless'])
                assert res.exit_code == 0
                mock_wget.assert_not_called()
                mock_pw.assert_called()

def test_download_incremental_second_run():
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as d:
        manifest_path = os.path.join(d, ".dograpper-manifest.json")

        from dograpper.lib.wget_mirror import WgetResult
        paths = [os.path.join(d, f"p{i}.html") for i in range(3)]
        with patch('dograpper.commands.download.run_wget_mirror') as mock_wget:
            mock_wget.return_value = WgetResult(True, d, paths, [], 0)
            with patch('dograpper.commands.download.is_spa') as mock_is_spa:
                mock_is_spa.return_value = False

                for p in paths:
                    with open(p, "w") as f:
                        f.write("1")

                # First run
                runner.invoke(download, ['http://example.com', '-o', d, '--manifest', manifest_path])
                args1 = mock_wget.call_args[1]
                assert args1.get('incremental', False) is False

                # Second run
                runner.invoke(download, ['http://example.com', '-o', d, '--manifest', manifest_path])
                args2 = mock_wget.call_args[1]
                assert args2.get('incremental', False) is True

def test_download_wget_not_installed():
    runner = CliRunner()
    from dograpper.lib.wget_mirror import run_wget_mirror
    with patch('subprocess.run') as mock_run:
        mock_run.side_effect = FileNotFoundError()
        
        with tempfile.TemporaryDirectory() as d:
            res = runner.invoke(download, ['http://example.com', '-o', d])
            assert res.exit_code != 0
            assert "wget is required" in res.output


# --- failed URLs on wget exit 8 (issue #97) ---

WGET_STDERR_FIXTURE = os.path.join(
    os.path.dirname(__file__), "fixtures", "wget_exit8_stderr.txt")


def _wget_stderr():
    with open(WGET_STDERR_FIXTURE, encoding="utf-8") as f:
        return f.read()


def test_parse_failed_urls_extracts_url_and_status_skipping_robots():
    from dograpper.lib.wget_mirror import parse_wget_log
    failed, _ = parse_wget_log(_wget_stderr())
    assert [(f.url, f.status) for f in failed] == [
        ("http://127.0.0.1:8765/missing.html", 404),
        ("http://127.0.0.1:8765/gone2.html", 404),
    ]


def test_parse_failed_urls_ignores_success_only_output():
    from dograpper.lib.wget_mirror import parse_wget_log
    assert parse_wget_log("--2026-11-17 22:05:03--  http://h/ok\n200 OK\n")[0] == []


def _run_exit_8(fn, first_arg):
    def side_effect(*args, **kwargs):
        result = MagicMock()
        result.returncode = 0 if "--version" in args[0] else 8
        result.stdout = ""
        result.stderr = _wget_stderr()
        return result
    with patch('subprocess.run', side_effect=side_effect), \
            tempfile.TemporaryDirectory() as d:
        return fn(first_arg, d)


def test_both_wget_paths_record_failures_on_exit_8():
    from dograpper.lib.wget_mirror import run_wget_mirror, run_wget_urls
    for fn, arg in ((run_wget_mirror, "http://127.0.0.1:8765/"),
                    (run_wget_urls, ["http://127.0.0.1:8765/"])):
        res = _run_exit_8(fn, arg)
        assert res.success is True
        assert [f.status for f in res.failed] == [404, 404]


# --- URL of each saved file, from wget's log (issue #94) ---
#
# Real wget 1.21.4 stderr (LANGUAGE=C, C.UTF-8 locale) against a local server:
# --mirror on a first run, and a second `-i` run where a 304 keeps notes.txt.

def _fixture(name):
    with open(os.path.join(os.path.dirname(__file__), "fixtures", name), encoding="utf-8") as f:
        return f.read()


H = "http://127.0.0.1:8766"
O = "out/127.0.0.1:8766"


def test_parse_wget_log_pairs_each_saved_file_with_the_url_fetched():
    from dograpper.lib.wget_mirror import parse_wget_log
    failed, saved = parse_wget_log(_fixture("wget_mirror_stderr.txt"))
    assert saved == {
        f"{O}/index.html": f"{H}/",
        f"{O}/wiki/Category:En.html": f"{H}/wiki/Category:En",  # .html added by -E
        f"{O}/w/index.php?title=Category:Lua&pagefrom=On&Off.html":
            f"{H}/w/index.php?title=Category:Lua&pagefrom=On%26Off",
        f"{O}/old.html": f"{H}/old",  # the URL requested, not the redirect target
        f"{O}/a b.html": f"{H}/a%20b.html",
        f"{O}/notes.txt": f"{H}/notes.txt",
        f"{O}/dir/index.html": f"{H}/dir/",
        f"{O}/caf\u00e9.html": f"{H}/caf%C3%A9",
        f"{O}/it's.html": f"{H}/it's",
    }
    assert [(f.url, f.status) for f in failed] == [(f"{H}/missing.html", 404)]


def test_parse_wget_log_keeps_files_wget_found_up_to_date():
    from dograpper.lib.wget_mirror import parse_wget_log
    _, saved = parse_wget_log(_fixture("wget_urls_stderr.txt"))
    assert saved == {
        f"{O}/wiki/Category:En.html": f"{H}/wiki/Category:En",
        f"{O}/w/index.php?title=Category:Lua&pagefrom=On&Off.html":
            f"{H}/w/index.php?title=Category:Lua&pagefrom=On%26Off",
        f"{O}/old.html": f"{H}/old",
        f"{O}/notes.txt": f"{H}/notes.txt",  # "not modified on server"
    }


def test_parse_wget_log_undoes_quoting_escapes():
    """Lines from wget 1.21.4: a non-UTF-8 locale quotes with ' and escapes
    bytes as \\ooo; a UTF-8 one escapes only \\ and the closing quote."""
    from dograpper.lib.wget_mirror import parse_wget_log
    log = "\n".join([
        f"--2026-11-17 22:46:04--  {H}/caf%C3%A9",
        "Saving to: 'out3/127.0.0.1:8766/caf\\303\\251.html'",
        f"--2026-11-17 22:46:04--  {H}/it's",
        "Saving to: 'out3/127.0.0.1:8766/it\\'s.html'",
        f"--2026-11-17 22:50:43--  {H}/a%5Cb",
        "Saving to: \u2018out4/127.0.0.1:8766/a\\\\b.html\u2019",
        f"--2026-11-17 22:50:43--  {H}/x%E2%80%99y",
        "Saving to: \u2018out4/127.0.0.1:8766/x\\\u2019y.html\u2019",
        f"--2026-11-17 22:53:07--  {H}/notes.txt",
        "Server file no newer than local file \u2018out/127.0.0.1:8766/notes.txt\u2019"
        " -- not retrieving.",
    ])
    assert parse_wget_log(log)[1] == {
        "out3/127.0.0.1:8766/caf\u00e9.html": f"{H}/caf%C3%A9",
        "out3/127.0.0.1:8766/it's.html": f"{H}/it's",
        "out4/127.0.0.1:8766/a\\b.html": f"{H}/a%5Cb",
        "out4/127.0.0.1:8766/x\u2019y.html": f"{H}/x%E2%80%99y",
        "out/127.0.0.1:8766/notes.txt": f"{H}/notes.txt",
    }


def test_both_wget_paths_report_saved_urls():
    from dograpper.lib.wget_mirror import parse_wget_log, run_wget_mirror, run_wget_urls
    stderr = _fixture("wget_mirror_stderr.txt")

    def side_effect(*args, **kwargs):
        result = MagicMock()
        result.returncode = 0
        result.stdout = ""
        result.stderr = stderr
        return result
    for fn, arg in ((run_wget_mirror, H + "/"), (run_wget_urls, [H + "/"])):
        with patch('subprocess.run', side_effect=side_effect), \
                tempfile.TemporaryDirectory() as d:
            assert fn(arg, d).urls == parse_wget_log(stderr)[1]


def test_redirect_to_a_signed_url_never_reaches_the_manifest_or_the_pack(tmp_path):
    """A server can redirect to a URL carrying a secret (a presigned S3 link);
    only the URL dograpper requested is recorded, so none reaches a pack. A
    requested URL whose query carries a credential is not recorded either."""
    from dograpper.commands.pack import pack
    out = tmp_path / "m"
    page, index = out / "h.example" / "doc.html", out / "h.example" / "index.html"
    page.parent.mkdir(parents=True)
    page.write_text("<html><body><h1>Doc</h1><p>alpha beta gamma</p></body></html>")
    index.write_text("<html><body><h1>Home</h1><p>delta epsilon zeta</p></body></html>")
    signed = "https://bucket.s3.example/doc?X-Amz-Signature=secret&token=secret"
    stderr = "\n".join([
        "--2026-11-17 22:52:54--  https://h.example/",
        "HTTP request sent, awaiting response... 200 OK",
        f"Saving to: \u2018{index}\u2019",
        "--2026-11-17 22:52:54--  https://h.example/doc?title=Doc&token=typed",
        "HTTP request sent, awaiting response... 302 Found",
        f"Location: {signed} [following]",
        f"--2026-11-17 22:52:54--  {signed}",
        "HTTP request sent, awaiting response... 200 OK",
        f"Saving to: \u2018{page}\u2019",
    ])

    def wget(*args, **kwargs):
        return MagicMock(returncode=0, stdout="", stderr=stderr)
    manifest = tmp_path / "manifest.json"
    with patch('subprocess.run', side_effect=wget), \
            patch('dograpper.commands.download._discover_urls', return_value=([], "none")), \
            patch('dograpper.commands.download.is_spa', return_value=False):
        res = CliRunner().invoke(download, ['https://h.example/', '-o', str(out),
                                            '--manifest', str(manifest)])
    assert res.exit_code == 0, res.output
    assert "secret" not in manifest.read_text() and "typed" not in manifest.read_text()
    files = load_manifest(str(manifest)).files
    assert files["doc.html"].url is None
    assert files["index.html"].url == "https://h.example/"

    chunks = tmp_path / "chunks"
    res = CliRunner().invoke(pack, [str(out), '-o', str(chunks), '--format', 'jsonl',
                                    '--context-header', '--manifest', str(manifest)])
    assert res.exit_code == 0, res.output
    records = [json.loads(line) for f in chunks.glob("*.jsonl")
               for line in f.read_text().splitlines()]
    assert {r["source"]: r.get("url") for r in records} == {
        "h.example/index.html": "https://h.example/", "h.example/doc.html": None}
    assert not [f for f in chunks.iterdir()
                if "secret" in f.read_text() or "typed" in f.read_text()]


def test_format_failures_caps_at_five_unless_verbose():
    from dograpper.lib.wget_mirror import WgetFailure, format_failures
    failed = [WgetFailure(f"http://h/p{i}", 404) for i in range(8)]
    lines = format_failures(failed, verbose=False)
    assert lines[0] == "Failed: 8 URLs (first 5 shown)"
    assert sum("http://h/p" in l for l in lines) == 5
    assert "http://h/p5" not in "\n".join(lines)
    full = format_failures(failed, verbose=True)
    assert full[0] == "Failed: 8 URLs"
    assert sum("http://h/p" in l for l in full) == 8
    assert format_failures([], verbose=False) == []


def test_format_failures_redacts_userinfo():
    from dograpper.lib.wget_mirror import WgetFailure, format_failures
    lines = format_failures([WgetFailure("http://u:secret@h/p", 500)], verbose=False)
    assert "secret" not in "\n".join(lines)


def test_format_failures_masks_credential_like_params():
    from dograpper.lib.wget_mirror import WgetFailure, format_failures
    lines = format_failures([WgetFailure("http://h/p?title=T&apiKey=k1", 403)], verbose=False)
    assert lines[1] == "  http://h/p?title=T&apiKey=REDACTED: 403"


def test_download_prints_failed_urls_summary():
    from dograpper.lib.wget_mirror import WgetFailure, WgetResult
    failed = [WgetFailure(f"http://x.io/p{i}", 404) for i in range(7)]
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as d, \
            patch('dograpper.commands.download.run_wget_mirror') as mock_wget, \
            patch('dograpper.commands.download._discover_urls', return_value=([], None)), \
            patch('dograpper.commands.download.is_spa', return_value=False):
        paths = [os.path.join(d, f"{n}.html") for n in "ab"]
        for p in paths:
            open(p, "w").write("c")
        mock_wget.return_value = WgetResult(True, d, paths, [], 0, failed)
        manifest_path = os.path.join(d, ".m.json")
        res = runner.invoke(download, ['http://x.io', '-o', d, '--manifest', manifest_path])
        assert res.exit_code == 0
        assert "Failed: 7 URLs (first 5 shown)" in res.output
        assert "http://x.io/p4: 404" in res.output
        assert "http://x.io/p5" not in res.output
        res = runner.invoke(cli, ['--verbose', 'download', 'http://x.io', '-o', d, '--manifest', manifest_path])
        assert res.exit_code == 0
        assert "Failed: 7 URLs" in res.output and "first 5" not in res.output
        assert "http://x.io/p6: 404" in res.output
