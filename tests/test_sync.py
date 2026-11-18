"""Regression tests for `dograpper sync` flag pass-through."""

from unittest.mock import patch

from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.commands.download import download as download_cmd
from dograpper.commands.pack import pack as pack_cmd


def _capture_calls():
    """Build stub callbacks for download and pack that record their kwargs."""
    captured = {"download": None, "pack": None}

    def _dl(**kwargs):
        captured["download"] = kwargs

    def _pk(**kwargs):
        captured["pack"] = kwargs

    return captured, _dl, _pk


def _run_sync(args):
    captured, dl_stub, pk_stub = _capture_calls()
    with patch.object(download_cmd, 'callback', dl_stub), \
         patch.object(pack_cmd, 'callback', pk_stub):
        result = CliRunner().invoke(cli, ['sync'] + args)
    return result, captured


def test_sync_accepts_pack_flags_without_error():
    """Sync must accept all pack-related flags promised by the README.

    Regression: users reported `--context-header` raising 'No such option'
    because sync was a thin wrapper that only forwarded a subset of pack flags.
    """
    result, captured = _run_sync([
        'https://example.com',
        '-o', './out',
        '--context-header',
        '--score',
        '--cross-refs',
        '--format', 'md',
        '--bundle', 'notebooklm',
    ])
    assert result.exit_code == 0, f"sync rejected flags: {result.output}"
    pk = captured["pack"]
    assert pk is not None
    assert pk["context_header"] is True
    assert pk["score"] is True
    assert pk["cross_refs"] is True
    assert pk["bundle"] == "notebooklm"
    assert pk["delta"] is True


def test_sync_forwards_download_flags():
    """Sync must forward download-specific flags (--headless, --depth, --delay)."""
    result, captured = _run_sync([
        'https://spa.example.com',
        '-o', './out',
        '--headless',
        '--depth', '2',
        '--delay', '500',
    ])
    assert result.exit_code == 0, f"sync rejected download flags: {result.output}"
    dl = captured["download"]
    assert dl is not None
    assert dl["headless"] is True
    assert dl["depth"] == 2
    assert dl["delay"] == 500


def test_sync_forwards_pack_flags():
    """Sync must forward pack-specific flags (dedup, show-tokens, strategy)."""
    result, captured = _run_sync([
        'https://example.com',
        '-o', './out',
        '--strategy', 'semantic',
        '--dedup', 'both',
        '--show-tokens',
        '--max-chunks', '30',
    ])
    assert result.exit_code == 0, f"sync rejected pack flags: {result.output}"
    pk = captured["pack"]
    assert pk is not None
    assert pk["strategy"] == "semantic"
    assert pk["dedup"] == "both"
    assert pk["show_tokens"] is True
    assert pk["max_chunks"] == 30


def test_sync_forwards_downloader_and_httrack_flags():
    result, captured = _run_sync([
        'https://example.com', '-o', './out',
        '--downloader', 'httrack', '--user-agent', 'bot/1', '--no-robots',
        '--connections', '6', '--max-conn-rate', '2.5',
        '--max-bandwidth', '5000', '--timeout', '30', '--retries', '1',
        '--max-links', '10', '--max-retry-after', '5',
        '--disable-security-limits',
    ])
    assert result.exit_code == 0, result.output
    dl = captured["download"]
    assert dl["downloader"] == "httrack"
    assert dl["user_agent"] == "bot/1"
    assert dl["no_robots"] is True
    assert dl["connections"] == 6
    assert dl["max_conn_rate"] == 2.5
    assert dl["max_bandwidth"] == 5000
    assert dl["timeout"] == 30
    assert dl["retries"] == 1
    assert dl["max_links"] == 10
    assert dl["max_retry_after"] == 5
    assert dl["disable_security_limits"] is True


def test_sync_forwards_filter_rules():
    result, captured = _run_sync(['https://example.com', '-o', './out',
                                  '--filter', '-*', '--filter', '+*/wiki/On*'])
    assert result.exit_code == 0, result.output
    assert captured["download"]["filter"] == ('-*', '+*/wiki/On*')


def test_sync_downloader_defaults_match_download():
    result, captured = _run_sync(['https://example.com', '-o', './out'])
    assert result.exit_code == 0, result.output
    dl = captured["download"]
    names = {'downloader', 'user_agent', 'no_robots', 'connections',
             'max_conn_rate', 'max_bandwidth', 'timeout', 'retries',
             'max_links', 'max_retry_after', 'disable_security_limits'}
    for p in download_cmd.params:
        if p.name in names:
            assert dl[p.name] == p.default, p.name


def test_sync_download_and_pack_share_the_manifest_in_output(tmp_path, monkeypatch):
    """#95: download writes the manifest into -o and pack reads it from there,
    whatever the CWD; --context-header URLs come from it."""
    import json
    import os
    from dograpper.lib.wget_mirror import WgetResult

    (tmp_path / "cwd").mkdir()
    monkeypatch.chdir(tmp_path / "cwd")
    docs = tmp_path / "docs"
    page = docs / "h.example" / "wiki" / "A.html"
    page.parent.mkdir(parents=True)
    page.write_text("<html><body><h1>A</h1><p>alpha beta gamma</p></body></html>")
    (docs / "h.example" / "b.html").write_text("<html><body><h1>B</h1><p>delta</p></body></html>")
    files = [str(page), str(docs / "h.example" / "b.html")]
    with patch('dograpper.commands.download.run_wget_mirror',
               return_value=WgetResult(True, str(docs), files, [], 0, [],
                                       {str(page): "https://h.example/wiki/A"})), \
            patch('dograpper.commands.download._discover_urls', return_value=([], "none")), \
            patch('dograpper.commands.download.is_spa', return_value=False):
        result = CliRunner().invoke(cli, ['sync', 'https://h.example/', '-o', str(docs),
                                          '--chunks-dir', str(tmp_path / "chunks"),
                                          '--format', 'jsonl', '--context-header'])
    assert result.exit_code == 0, result.output
    assert os.listdir(tmp_path / "cwd") == []
    assert (docs / ".dograpper-manifest.json").is_file()
    records = {}
    for chunk in (tmp_path / "chunks").glob("*.jsonl"):
        for line in chunk.read_text().splitlines():
            rec = json.loads(line)
            records[rec["source"]] = rec
    assert records["h.example/wiki/A.html"]["url"] == "https://h.example/wiki/A"
    assert "url" not in records["h.example/b.html"]
