"""A delta pack must never leave partial artifacts behind (issue #39).

`--delta` is a change gate: the corpus state recorded by the last pack
decides *whether* the run happens, not *which* files it packs. Everything a
delta run writes is therefore as complete as a full pack's output.
See ADR-0008.
"""

import json
import os
import time

from click.testing import CliRunner

from dograpper.commands.pack import PACK_STATE_FILENAME, pack
from dograpper.lib.manifest import build_manifest, load_manifest, save_manifest


def _write(input_dir, files):
    os.makedirs(input_dir, exist_ok=True)
    for rel, body in files.items():
        path = os.path.join(input_dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(body)


def _page(title, body):
    return f"<html><body><main><h1>{title}</h1><p>{body}</p></main></body></html>"


def _corpus(tmp_path):
    input_dir = str(tmp_path / "docs")
    _write(input_dir, {
        "a.html": _page("Alpha", "alpha one two three four five"),
        "b.html": _page("Beta", "beta one two three four five"),
        "c.html": _page("Gamma", "gamma one two three four five"),
    })
    return input_dir


def _seed_state(input_dir, output_dir):
    """Record the corpus as already packed, the way a real run would."""
    os.makedirs(output_dir, exist_ok=True)
    save_manifest(build_manifest(base_url="", output_dir=input_dir),
                  os.path.join(output_dir, PACK_STATE_FILENAME))


def _touch(input_dir, rel, body):
    time.sleep(0.05)  # mtime resolution
    with open(os.path.join(input_dir, rel), 'w', encoding='utf-8') as f:
        f.write(body)


def _run(args):
    return CliRunner().invoke(pack, args, catch_exceptions=False)


# ---------------------------------------------------------------------------
# The reported corruption
# ---------------------------------------------------------------------------

def test_delta_keeps_the_readiness_snapshot_complete(tmp_path):
    """The bug: a delta run overwrote the full snapshot with a single chunk."""
    input_dir = _corpus(tmp_path)
    output_dir = str(tmp_path / "chunks")

    full = _run([input_dir, '-o', output_dir, '--score',
                 '--max-words-per-chunk', '10'])
    assert full.exit_code == 0

    snapshot_path = os.path.join(output_dir, "llm-readiness.json")
    before = json.load(open(snapshot_path, encoding="utf-8"))
    assert before["summary"]["total_chunks"] == 3

    _seed_state(input_dir, output_dir)
    _touch(input_dir, "b.html", _page("Beta", "beta rewritten six seven eight nine"))

    delta = _run([input_dir, '-o', output_dir, '--score',
                  '--max-words-per-chunk', '10', '--delta'])
    assert delta.exit_code == 0

    after = json.load(open(snapshot_path, encoding="utf-8"))
    assert after["summary"]["total_chunks"] == 3
    assert [c["chunk_id"] for c in after["chunks"]] == \
           [c["chunk_id"] for c in before["chunks"]]


def test_delta_does_not_clobber_untouched_chunks(tmp_path):
    """Renumbering from 01 used to overwrite chunks with unrelated content."""
    input_dir = _corpus(tmp_path)
    output_dir = str(tmp_path / "chunks")

    _run([input_dir, '-o', output_dir, '--max-words-per-chunk', '10'])
    chunk_files = sorted(f for f in os.listdir(output_dir)
                         if f.startswith("docs_chunk_"))
    assert len(chunk_files) == 3

    _seed_state(input_dir, output_dir)
    _touch(input_dir, "c.html", _page("Gamma", "gamma rewritten six seven eight"))

    _run([input_dir, '-o', output_dir, '--max-words-per-chunk', '10', '--delta'])

    assert sorted(f for f in os.listdir(output_dir)
                  if f.startswith("docs_chunk_")) == chunk_files
    # Alpha was never touched and must still be somewhere in the pack.
    packed = "".join(
        open(os.path.join(output_dir, f), encoding="utf-8").read()
        for f in chunk_files)
    assert "alpha one two three" in packed
    assert "gamma rewritten" in packed


def test_delta_run_processes_every_file_not_just_the_changed_ones(tmp_path):
    """The contract change: a delta run that fires is a full pack."""
    input_dir = _corpus(tmp_path)
    output_dir = str(tmp_path / "chunks")

    _seed_state(input_dir, output_dir)
    _touch(input_dir, "b.html", _page("Beta", "beta rewritten six seven eight"))

    result = _run([input_dir, '-o', output_dir, '--delta'])

    assert result.exit_code == 0
    assert "Files processed: 3" in result.output
    assert "1 modified" in result.output


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------

def test_unchanged_corpus_writes_no_chunks(tmp_path):
    input_dir = _corpus(tmp_path)
    output_dir = str(tmp_path / "chunks")

    _seed_state(input_dir, output_dir)

    result = _run([input_dir, '-o', output_dir, '--delta'])

    assert result.exit_code == 0
    assert "no files changed" in result.output.lower()
    assert [f for f in os.listdir(output_dir) if f != PACK_STATE_FILENAME] == []


def test_ignored_files_do_not_trigger_a_repack(tmp_path):
    """Churn outside the packed set must not fire the gate."""
    input_dir = _corpus(tmp_path)
    output_dir = str(tmp_path / "chunks")

    _write(input_dir, {"noise.log": "first"})
    _seed_state(input_dir, output_dir)

    _touch(input_dir, "noise.log", "second, longer content")

    result = _run([input_dir, '-o', output_dir, '--ignore', '*.log', '--delta'])

    assert result.exit_code == 0
    assert "no files changed" in result.output.lower()


def test_removed_file_fires_the_gate(tmp_path):
    input_dir = _corpus(tmp_path)
    output_dir = str(tmp_path / "chunks")

    _seed_state(input_dir, output_dir)
    os.remove(os.path.join(input_dir, "c.html"))

    result = _run([input_dir, '-o', output_dir, '--delta'])

    assert result.exit_code == 0
    assert "Files processed: 2" in result.output
    assert "1 removed" in result.output


# ---------------------------------------------------------------------------
# Where the delta state lives
# ---------------------------------------------------------------------------

def test_delta_records_state_so_the_next_run_sees_no_change(tmp_path):
    """Pack-only flows: without this, every --delta run reprocessed everything."""
    input_dir = _corpus(tmp_path)
    output_dir = str(tmp_path / "chunks")

    first = _run([input_dir, '-o', output_dir, '--delta'])
    assert first.exit_code == 0
    assert os.path.exists(os.path.join(output_dir, PACK_STATE_FILENAME))

    second = _run([input_dir, '-o', output_dir, '--delta'])
    assert "no files changed" in second.output.lower()


def test_pack_without_delta_records_no_state(tmp_path):
    input_dir = _corpus(tmp_path)
    output_dir = str(tmp_path / "chunks")

    result = _run([input_dir, '-o', output_dir])

    assert result.exit_code == 0
    assert not os.path.exists(os.path.join(output_dir, PACK_STATE_FILENAME))


def test_dry_run_records_no_state(tmp_path):
    """Nothing was packed, so nothing may be marked as packed."""
    input_dir = _corpus(tmp_path)
    output_dir = str(tmp_path / "chunks")

    result = _run([input_dir, '-o', output_dir, '--delta', '--dry-run'])

    assert result.exit_code == 0
    assert not os.path.exists(os.path.join(output_dir, PACK_STATE_FILENAME))


def test_delta_never_rewrites_the_download_manifest(tmp_path):
    """`download` owns that file; pack must not degrade its URLs."""
    input_dir = str(tmp_path / "docs")
    _write(input_dir, {"site.com/a.html": _page("Alpha", "alpha one two three")})
    output_dir = str(tmp_path / "chunks")
    manifest_path = str(tmp_path / "manifest.json")

    save_manifest(build_manifest(base_url="https://site.com/", output_dir=input_dir),
                  manifest_path)
    before = open(manifest_path, encoding="utf-8").read()

    result = _run([input_dir, '-o', output_dir,
                   '--delta', '--manifest', manifest_path])

    assert result.exit_code == 0
    assert open(manifest_path, encoding="utf-8").read() == before
    saved = load_manifest(manifest_path)
    assert saved.base_url == "https://site.com/"
    assert saved.files["a.html"].url == "https://site.com/a.html"


def test_freshly_downloaded_corpus_still_packs(tmp_path):
    """The sync flow: download rewrites its manifest right before pack runs.

    That manifest always describes the current tree, so it can never say what
    changed since the last pack — the gate must not read it, or sync would
    stop producing chunks.
    """
    input_dir = str(tmp_path / "docs")
    _write(input_dir, {
        "site.com/a.html": _page("Alpha", "alpha one two three"),
        "site.com/b.html": _page("Beta", "beta one two three"),
    })
    output_dir = str(tmp_path / "chunks")
    manifest_path = str(tmp_path / "manifest.json")

    save_manifest(build_manifest(base_url="https://site.com/", output_dir=input_dir),
                  manifest_path)

    result = _run([input_dir, '-o', output_dir,
                   '--delta', '--manifest', manifest_path])

    assert result.exit_code == 0
    assert "Files processed: 2" in result.output
    assert os.path.exists(os.path.join(output_dir, "docs_chunk_01.md"))


def test_sync_packs_on_the_first_run_and_no_ops_on_the_second(tmp_path, monkeypatch):
    """`sync` always invokes pack with --delta, so the gate must not misfire.

    Download rewrites its manifest after mirroring; if the gate read that
    file it would report "nothing changed" on the very run that has to pack,
    and sync would never produce chunks.
    """
    from unittest.mock import patch

    from dograpper.cli import cli

    docs = str(tmp_path / "docs")
    chunks = str(tmp_path / "chunks")
    monkeypatch.chdir(tmp_path)  # sync's default --manifest is cwd-relative

    def _fake_download(url, output, depth, headless, delay, include_extensions,
                       manifest):
        site = os.path.join(output, "site.com")
        os.makedirs(site, exist_ok=True)
        for name in ("a.html", "b.html"):
            path = os.path.join(site, name)
            if not os.path.exists(path):
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(_page(name, f"body for {name}"))
        save_manifest(build_manifest(url, output), manifest)

    runner = CliRunner()
    with patch("dograpper.commands.download.download.callback",
               side_effect=_fake_download):
        first = runner.invoke(cli, ["sync", "https://site.com/", "-o", docs,
                                    "--chunks-dir", chunks],
                              catch_exceptions=False)
        assert first.exit_code == 0
        assert os.path.exists(os.path.join(chunks, "docs_chunk_01.md"))

        second = runner.invoke(cli, ["sync", "https://site.com/", "-o", docs,
                                     "--chunks-dir", chunks],
                               catch_exceptions=False)
        assert second.exit_code == 0
        assert "no files changed" in second.output.lower()
        # The no-op must not remove what the first run produced.
        assert os.path.exists(os.path.join(chunks, "docs_chunk_01.md"))
