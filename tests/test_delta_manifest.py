import os
import json
import tempfile
import time

from click.testing import CliRunner

from dograpper.lib.manifest import (
    Manifest, ManifestEntry, ManifestDiff,
    diff_manifests, build_manifest, save_manifest, load_manifest,
)
from dograpper.commands.pack import PACK_STATE_FILENAME, pack


def _seed_pack_state(input_dir, output_dir):
    """Record the corpus as already packed, the way a real delta run would."""
    os.makedirs(output_dir, exist_ok=True)
    save_manifest(build_manifest(base_url="", output_dir=input_dir),
                  os.path.join(output_dir, PACK_STATE_FILENAME))


# --- Unit tests for diff_manifests ---

def test_diff_old_none_all_added():
    """old=None → all files in new are 'added'."""
    new = Manifest("http://x", "2024", {
        "a.html": ManifestEntry("http://x/a", 100, mtime=1.0),
        "b.html": ManifestEntry("http://x/b", 200, mtime=2.0),
    })
    diff = diff_manifests(None, new)
    assert sorted(diff.added) == ["a.html", "b.html"]
    assert diff.modified == []
    assert diff.removed == []


def test_diff_file_added():
    """File present in new but not old → added."""
    old = Manifest("http://x", "2024", {
        "a.html": ManifestEntry("http://x/a", 100, mtime=1.0),
    })
    new = Manifest("http://x", "2024", {
        "a.html": ManifestEntry("http://x/a", 100, mtime=1.0),
        "b.html": ManifestEntry("http://x/b", 200, mtime=2.0),
    })
    diff = diff_manifests(old, new)
    assert diff.added == ["b.html"]
    assert diff.modified == []
    assert diff.removed == []


def test_diff_size_changed():
    """File present in both, size different → modified."""
    old = Manifest("http://x", "2024", {
        "a.html": ManifestEntry("http://x/a", 100, mtime=1.0),
    })
    new = Manifest("http://x", "2024", {
        "a.html": ManifestEntry("http://x/a", 999, mtime=1.0),
    })
    diff = diff_manifests(old, new)
    assert diff.added == []
    assert diff.modified == ["a.html"]
    assert diff.removed == []


def test_diff_mtime_changed():
    """File present in both, size equal, mtime different → modified."""
    old = Manifest("http://x", "2024", {
        "a.html": ManifestEntry("http://x/a", 100, mtime=1.0),
    })
    new = Manifest("http://x", "2024", {
        "a.html": ManifestEntry("http://x/a", 100, mtime=9.0),
    })
    diff = diff_manifests(old, new)
    assert diff.added == []
    assert diff.modified == ["a.html"]
    assert diff.removed == []


def test_diff_unchanged():
    """File present in both, size and mtime equal → not in any list."""
    old = Manifest("http://x", "2024", {
        "a.html": ManifestEntry("http://x/a", 100, mtime=1.0),
    })
    new = Manifest("http://x", "2024", {
        "a.html": ManifestEntry("http://x/a", 100, mtime=1.0),
    })
    diff = diff_manifests(old, new)
    assert diff.added == []
    assert diff.modified == []
    assert diff.removed == []


def test_diff_file_removed():
    """File present in old but not new → removed."""
    old = Manifest("http://x", "2024", {
        "a.html": ManifestEntry("http://x/a", 100, mtime=1.0),
        "b.html": ManifestEntry("http://x/b", 200, mtime=2.0),
    })
    new = Manifest("http://x", "2024", {
        "a.html": ManifestEntry("http://x/a", 100, mtime=1.0),
    })
    diff = diff_manifests(old, new)
    assert diff.added == []
    assert diff.modified == []
    assert diff.removed == ["b.html"]


def test_diff_both_empty():
    """Both manifests empty → diff empty."""
    old = Manifest("http://x", "2024", {})
    new = Manifest("http://x", "2024", {})
    diff = diff_manifests(old, new)
    assert diff.added == []
    assert diff.modified == []
    assert diff.removed == []


def test_diff_mtime_changed_same_hash_not_modified():
    """Size equal, mtime differs, content hash equal → not modified (#56).

    A touch, a cp without -p, or a fresh git clone changes mtime without
    changing bytes. The hash is the source of truth once mtime disagrees.
    """
    old = Manifest("http://x", "2024", {
        "a.html": ManifestEntry("http://x/a", 100, mtime=1.0, content_hash="abc123"),
    })
    new = Manifest("http://x", "2024", {
        "a.html": ManifestEntry("http://x/a", 100, mtime=9.0, content_hash="abc123"),
    })
    diff = diff_manifests(old, new)
    assert diff.added == []
    assert diff.modified == []
    assert diff.removed == []


def test_diff_mtime_changed_different_hash_modified():
    """Size equal, mtime differs, content hash differs → modified."""
    old = Manifest("http://x", "2024", {
        "a.html": ManifestEntry("http://x/a", 100, mtime=1.0, content_hash="abc123"),
    })
    new = Manifest("http://x", "2024", {
        "a.html": ManifestEntry("http://x/a", 100, mtime=9.0, content_hash="def456"),
    })
    diff = diff_manifests(old, new)
    assert diff.added == []
    assert diff.modified == ["a.html"]
    assert diff.removed == []


def test_diff_old_entry_missing_hash_falls_back_to_mtime():
    """Backward compat: entries from a manifest written before the hash field
    existed have content_hash=None. Without a hash to compare, fall back to
    the old size+mtime heuristic instead of crashing or assuming unchanged.
    """
    old = Manifest("http://x", "2024", {
        "a.html": ManifestEntry("http://x/a", 100, mtime=1.0),
    })
    new = Manifest("http://x", "2024", {
        "a.html": ManifestEntry("http://x/a", 100, mtime=9.0, content_hash="abc123"),
    })
    diff = diff_manifests(old, new)
    assert diff.modified == ["a.html"]


def test_diff_old_entry_missing_hash_same_mtime_not_modified():
    """Backward compat: no hash on the old entry, but mtime is unchanged, so
    the fast path applies and no hashing is needed to decide.
    """
    old = Manifest("http://x", "2024", {
        "a.html": ManifestEntry("http://x/a", 100, mtime=1.0),
    })
    new = Manifest("http://x", "2024", {
        "a.html": ManifestEntry("http://x/a", 100, mtime=1.0, content_hash="abc123"),
    })
    diff = diff_manifests(old, new)
    assert diff.modified == []


# --- Integration tests for --delta via CLI ---

def _make_test_dir(tmpdir, files_dict):
    """Create files in tmpdir from a {relative_path: content} dict."""
    for rel, content in files_dict.items():
        fpath = os.path.join(tmpdir, rel)
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(content)


def test_delta_first_pack_all_added():
    """First pack with --delta and no prior manifest: treats all as added."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = os.path.join(tmpdir, "docs")
        output_dir = os.path.join(tmpdir, "chunks")
        manifest_path = os.path.join(tmpdir, "manifest.json")

        _make_test_dir(input_dir, {
            "a.txt": "hello world one two three",
            "b.txt": "foo bar baz qux quux",
        })

        result = runner.invoke(pack, [
            input_dir, '-o', output_dir,
            '--delta', '--manifest', manifest_path,
        ], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Delta:" in result.output
        assert "2 added" in result.output

        # delta_manifest.json should exist
        delta_path = os.path.join(output_dir, "delta_manifest.json")
        assert os.path.exists(delta_path)
        data = json.load(open(delta_path))
        assert len(data["added"]) == 2
        assert data["modified"] == []
        assert data["removed"] == []


def test_delta_modified_file_only():
    """Modifying one file fires the gate; the run that follows is a full pack.

    Until ADR-0008 this packed only the changed file, which renumbered the
    chunks from 01 and overwrote the artifacts of everything else (#39).
    """
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = os.path.join(tmpdir, "docs")
        output_dir = os.path.join(tmpdir, "chunks")
        manifest_path = os.path.join(tmpdir, "manifest.json")

        _make_test_dir(input_dir, {
            "a.txt": "hello world one two three",
            "b.txt": "foo bar baz qux quux",
        })

        # Record the corpus as already packed
        _seed_pack_state(input_dir, output_dir)

        # Wait a moment and modify one file so mtime changes
        time.sleep(0.05)
        with open(os.path.join(input_dir, "b.txt"), 'w') as f:
            f.write("modified content here now different")

        result = runner.invoke(pack, [
            input_dir, '-o', output_dir, '--delta',
        ], catch_exceptions=False)

        assert result.exit_code == 0
        assert "1 modified" in result.output
        assert "Files processed: 2" in result.output

        delta_path = os.path.join(output_dir, "delta_manifest.json")
        data = json.load(open(delta_path))
        assert "b.txt" in data["modified"]
        # Both files are in the pack, not just the modified one.
        packed = [f for cg in data["chunks_generated"] for f in cg["files"]]
        assert sorted(packed) == ["a.txt", "b.txt"]


def test_delta_touch_no_content_change_not_modified():
    """touch changes mtime but not content → delta gate stays closed (#56).

    Reproduces the issue's repro: byte-identical file, changed mtime only,
    must not be reported as modified nor trigger a full repack.
    """
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = os.path.join(tmpdir, "docs")
        output_dir = os.path.join(tmpdir, "chunks")

        _make_test_dir(input_dir, {
            "a.txt": "hello world one two three",
            "b.txt": "foo bar baz qux quux",
        })

        # Record the corpus as already packed
        _seed_pack_state(input_dir, output_dir)

        # touch b.txt: mtime changes, content stays byte-identical
        time.sleep(0.05)
        os.utime(os.path.join(input_dir, "b.txt"), None)

        result = runner.invoke(pack, [
            input_dir, '-o', output_dir, '--delta',
        ], catch_exceptions=False)

        assert result.exit_code == 0
        assert "no files changed" in result.output.lower()
        assert [f for f in os.listdir(output_dir) if f != PACK_STATE_FILENAME] == []


def test_delta_no_changes():
    """Pack --delta with no changes prints message and exits cleanly."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = os.path.join(tmpdir, "docs")
        output_dir = os.path.join(tmpdir, "chunks")
        manifest_path = os.path.join(tmpdir, "manifest.json")

        _make_test_dir(input_dir, {
            "a.txt": "hello world one two three",
        })

        # Record a state matching the current corpus
        _seed_pack_state(input_dir, output_dir)

        result = runner.invoke(pack, [
            input_dir, '-o', output_dir, '--delta',
        ], catch_exceptions=False)

        assert result.exit_code == 0
        assert "no files changed" in result.output.lower()
        # No chunks should be written
        assert [f for f in os.listdir(output_dir) if f != PACK_STATE_FILENAME] == []


def test_delta_manifest_json_fields():
    """delta_manifest.json has all required fields."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = os.path.join(tmpdir, "docs")
        output_dir = os.path.join(tmpdir, "chunks")
        manifest_path = os.path.join(tmpdir, "manifest.json")

        _make_test_dir(input_dir, {
            "a.txt": "hello world",
        })

        result = runner.invoke(pack, [
            input_dir, '-o', output_dir, '--delta',
            '--manifest', manifest_path,
        ], catch_exceptions=False)

        assert result.exit_code == 0
        delta_path = os.path.join(output_dir, "delta_manifest.json")
        assert os.path.exists(delta_path)

        data = json.load(open(delta_path))
        assert "timestamp" in data
        assert "added" in data
        assert "modified" in data
        assert "removed" in data
        assert "chunks_generated" in data
        assert isinstance(data["chunks_generated"], list)
        for cg in data["chunks_generated"]:
            assert "chunk" in cg
            assert "files" in cg


def test_pack_without_delta_ignores_manifest():
    """Pack without --delta processes all files (regression test)."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        input_dir = os.path.join(tmpdir, "docs")
        output_dir = os.path.join(tmpdir, "chunks")

        _make_test_dir(input_dir, {
            "a.txt": "hello world one two three",
            "b.txt": "foo bar baz qux quux",
        })

        result = runner.invoke(pack, [
            input_dir, '-o', output_dir,
        ], catch_exceptions=False)

        assert result.exit_code == 0
        assert "Files processed: 2" in result.output
        # No delta_manifest.json
        assert not os.path.exists(os.path.join(output_dir, "delta_manifest.json"))


def test_build_manifest_populates_mtime():
    """build_manifest should populate mtime for each entry."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = os.path.join(tmpdir, "test.txt")
        with open(fpath, 'w') as f:
            f.write("content")

        manifest = build_manifest(base_url="", output_dir=tmpdir)
        entry = list(manifest.files.values())[0]
        assert entry.mtime is not None
        assert isinstance(entry.mtime, float)
        assert entry.mtime > 0


def test_build_manifest_populates_content_hash():
    """build_manifest should populate an md5 content hash for each entry."""
    import hashlib

    with tempfile.TemporaryDirectory() as tmpdir:
        fpath = os.path.join(tmpdir, "test.txt")
        with open(fpath, 'wb') as f:
            f.write(b"content")

        manifest = build_manifest(base_url="", output_dir=tmpdir)
        entry = list(manifest.files.values())[0]
        assert entry.content_hash == hashlib.md5(b"content").hexdigest()


# --- build_manifest URL rebuild (#94) ---
#
# Fixtures reproduce wget 1.21.4 --mirror --adjust-extension layouts: the
# saved path is <host>[:port]/<decoded path>, a query string stays in the
# file name after "?", and ".html" is appended to HTML without that suffix.

SPHINX_SEED = "https://pz-wiki-modding.github.io/PZ-API-Docs/"
QUERY_SEED = ("https://pzwiki.net/w/index.php"
              "?title=Category:Current_Lua_events&pagefrom=OnLoadSoundBanks")


def _urls(base_url, tmp_path, rel_paths):
    _make_test_dir(str(tmp_path), {rel: "<p>x</p>" for rel in rel_paths})
    manifest = build_manifest(base_url, str(tmp_path))
    return {e.local_path: e.url for e in manifest.files.values()}


def test_build_manifest_url_does_not_repeat_the_seed_path(tmp_path):
    urls = _urls(SPHINX_SEED, tmp_path, [
        "pz-wiki-modding.github.io/PZ-API-Docs/index.html",
        "pz-wiki-modding.github.io/PZ-API-Docs/api/zombie.html",
    ])
    assert urls == {
        "pz-wiki-modding.github.io/PZ-API-Docs/index.html":
            "https://pz-wiki-modding.github.io/PZ-API-Docs/index.html",
        "pz-wiki-modding.github.io/PZ-API-Docs/api/zombie.html":
            "https://pz-wiki-modding.github.io/PZ-API-Docs/api/zombie.html",
    }


def test_build_manifest_url_is_not_appended_to_a_page_seed(tmp_path):
    urls = _urls(QUERY_SEED, tmp_path, ["pzwiki.net/robots.txt"])
    assert urls == {"pzwiki.net/robots.txt": "https://pzwiki.net/robots.txt"}


def test_build_manifest_omits_url_for_a_query_in_the_saved_name(tmp_path):
    """wget decodes the query (``%26`` and ``&`` both save as ``&``) and may or
    may not have appended ``.html``, so no URL is better than a guessed one."""
    urls = _urls(QUERY_SEED, tmp_path, [
        "pzwiki.net/w/index.php?title=Category:Current_Lua_events"
        "&pagefrom=OnLoadSoundBanks.html",
        "pzwiki.net/w/q?x=a&b.html",
    ])
    assert set(urls.values()) == {None}


def test_build_manifest_url_keeps_port_and_escapes_decoded_path(tmp_path):
    """The scheme comes from the seed. wget saves ``a%20b.html`` decoded, the
    Playwright layer saves the path still escaped: both give the same URL."""
    urls = _urls("http://127.0.0.1:8765/docs/", tmp_path,
                 ["127.0.0.1:8765/docs/a b.html", "127.0.0.1:8765/docs/c%20d.html",
                  "127.0.0.1:8765/wiki/Category:En.txt"])
    assert urls == {
        "127.0.0.1:8765/docs/a b.html": "http://127.0.0.1:8765/docs/a%20b.html",
        "127.0.0.1:8765/docs/c%20d.html": "http://127.0.0.1:8765/docs/c%20d.html",
        "127.0.0.1:8765/wiki/Category:En.txt":
            "http://127.0.0.1:8765/wiki/Category:En.txt",
    }


def test_build_manifest_omits_url_without_scheme_or_host_dir(tmp_path):
    assert _urls("", tmp_path / "a", ["site.com/a.html"]) == {"site.com/a.html": None}
    assert _urls(SPHINX_SEED, tmp_path / "b", ["loose.html"]) == {"loose.html": None}


def test_context_header_uses_rebuilt_urls_and_skips_missing_ones(tmp_path):
    """pack step 7c: correct URLs reach the chunks; a missing one is left out."""
    input_dir = str(tmp_path / "mirror")
    _make_test_dir(input_dir, {
        "pz-wiki-modding.github.io/PZ-API-Docs/index.html":
            "<html><body><h1>API</h1><p>alpha beta gamma</p></body></html>",
        "pz-wiki-modding.github.io/PZ-API-Docs/q?x=1.html":
            "<html><body><h1>Query</h1><p>delta epsilon zeta</p></body></html>",
    })
    manifest_path = str(tmp_path / "manifest.json")
    save_manifest(build_manifest(SPHINX_SEED, input_dir), manifest_path)
    output_dir = str(tmp_path / "chunks")

    result = CliRunner().invoke(pack, [
        input_dir, '-o', output_dir, '--format', 'jsonl', '--context-header',
        '--manifest', manifest_path,
    ], catch_exceptions=False)

    assert result.exit_code == 0
    records = {}
    for name in os.listdir(output_dir):
        if name.endswith(".jsonl"):
            with open(os.path.join(output_dir, name), encoding="utf-8") as f:
                for line in f:
                    rec = json.loads(line)
                    records[rec["source"]] = rec
    assert records["pz-wiki-modding.github.io/PZ-API-Docs/index.html"]["url"] == \
        "https://pz-wiki-modding.github.io/PZ-API-Docs/index.html"
    assert "url" not in records["pz-wiki-modding.github.io/PZ-API-Docs/q?x=1.html"]
