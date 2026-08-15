"""Tests for the sidecar artifacts a pack run writes next to the chunks."""

import json
import os

from dograpper.lib.chunker import Chunk, ChunkFile
from dograpper.lib.pack_artifacts import (
    count_chunk_tokens,
    readiness_snapshot,
    write_cross_refs,
    write_delta_manifest,
    write_readiness_json,
)
from dograpper.utils.scorer import ChunkScore


def _chunk(index, *rel_paths):
    return Chunk(
        index=index,
        files=[ChunkFile(rp, 10) for rp in rel_paths],
        total_words=10 * len(rel_paths),
    )


def _score(chunk_id, grade="A", score=90.0):
    return ChunkScore(
        chunk_id=chunk_id,
        word_count=100,
        noise_ratio=0.1234,
        boundary_integrity=True,
        context_depth=3,
        score=score,
        grade=grade,
    )


class _Diff:
    def __init__(self, added=None, modified=None, removed=None):
        self.added = added or []
        self.modified = modified or []
        self.removed = removed or []


# ---------------------------------------------------------------------------
# Cross-references
# ---------------------------------------------------------------------------

def test_write_cross_refs_indexes_links_and_annotates_chunks(tmp_path):
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / "a.html").write_text('<a href="b.html">See B</a>', encoding="utf-8")
    (src / "b.html").write_text("<p>B body</p>", encoding="utf-8")

    chunks = [_chunk(1, "a.html"), _chunk(2, "b.html")]
    (out / "docs_chunk_01.md").write_text("See B\n", encoding="utf-8")
    (out / "docs_chunk_02.md").write_text("B body\n", encoding="utf-8")

    stats = write_cross_refs(
        chunks, [str(src / "a.html"), str(src / "b.html")],
        str(src), str(out), "docs_chunk_", "md")

    index = json.loads((out / "cross_refs.json").read_text(encoding="utf-8"))
    assert "docs_chunk_01" in index
    assert stats.total == 1
    assert stats.unresolved == 0
    # The link points at the other chunk, so the source chunk gets a pointer.
    assert "docs_chunk_02" in (out / "docs_chunk_01.md").read_text(encoding="utf-8")


def test_write_cross_refs_counts_unresolved_targets(tmp_path):
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / "a.html").write_text('<a href="gone.html">Missing</a>', encoding="utf-8")

    chunks = [_chunk(1, "a.html")]
    (out / "docs_chunk_01.md").write_text("Missing\n", encoding="utf-8")

    stats = write_cross_refs(chunks, [str(src / "a.html")], str(src), str(out),
                             "docs_chunk_", "md")

    assert stats.unresolved == 1
    assert stats.total == 0


def test_write_cross_refs_skips_unreadable_sources(tmp_path):
    """A path that no longer exists must not abort the whole sidecar."""
    src = tmp_path / "src"
    out = tmp_path / "out"
    src.mkdir()
    out.mkdir()
    (src / "a.html").write_text("<p>Body</p>", encoding="utf-8")

    stats = write_cross_refs(
        [_chunk(1, "a.html")],
        [str(src / "a.html"), str(src / "vanished.html")],
        str(src), str(out), "docs_chunk_", "md")

    assert stats.total == 0
    assert (out / "cross_refs.json").exists()


# ---------------------------------------------------------------------------
# Delta manifest
# ---------------------------------------------------------------------------

def test_write_delta_manifest_records_diff_and_chunk_membership(tmp_path):
    diff = _Diff(added=["new.html"], modified=["changed.html"], removed=["old.html"])
    chunks = [_chunk(1, "new.html", "changed.html")]

    path = write_delta_manifest(diff, chunks, str(tmp_path), "docs_chunk_",
                                "2026-08-15T00:00:00+00:00")

    data = json.loads(open(path, encoding="utf-8").read())
    assert data["timestamp"] == "2026-08-15T00:00:00+00:00"
    assert data["added"] == ["new.html"]
    assert data["modified"] == ["changed.html"]
    assert data["removed"] == ["old.html"]
    assert data["chunks_generated"] == [
        {"chunk": "docs_chunk_01", "files": ["new.html", "changed.html"]}
    ]
    assert os.path.basename(path) == "delta_manifest.json"


# ---------------------------------------------------------------------------
# Readiness snapshot
# ---------------------------------------------------------------------------

def test_readiness_snapshot_summarizes_grades_and_average():
    snapshot = readiness_snapshot([
        _score("docs_chunk_01", grade="A", score=90.0),
        _score("docs_chunk_02", grade="C", score=50.0),
    ])

    assert snapshot["summary"]["total_chunks"] == 2
    assert snapshot["summary"]["avg_score"] == 70.0
    assert snapshot["summary"]["grades"] == {"A": 1, "B": 0, "C": 1}
    assert [c["chunk_id"] for c in snapshot["chunks"]] == [
        "docs_chunk_01", "docs_chunk_02"]
    # noise_ratio is rounded to three places in the snapshot.
    assert snapshot["chunks"][0]["noise_ratio"] == 0.123


def test_readiness_snapshot_handles_no_chunks():
    snapshot = readiness_snapshot([])
    assert snapshot["summary"]["total_chunks"] == 0
    assert snapshot["summary"]["avg_score"] == 0
    assert snapshot["chunks"] == []


def test_write_readiness_json_round_trips(tmp_path):
    path = write_readiness_json([_score("docs_chunk_01")], str(tmp_path))
    data = json.loads(open(path, encoding="utf-8").read())
    assert data == readiness_snapshot([_score("docs_chunk_01")])


# ---------------------------------------------------------------------------
# Token counting
# ---------------------------------------------------------------------------

def test_count_chunk_tokens_reads_the_written_files(tmp_path):
    (tmp_path / "docs_chunk_01.md").write_text("alpha beta gamma", encoding="utf-8")
    (tmp_path / "docs_chunk_02.md").write_text("delta", encoding="utf-8")

    counts = count_chunk_tokens([_chunk(1, "a"), _chunk(2, "b")], str(tmp_path),
                                "docs_chunk_", "md", "cl100k")

    assert len(counts) == 2
    assert counts[0].words == 3
    assert counts[1].words == 1


def test_count_chunk_tokens_skips_missing_chunk_files(tmp_path):
    (tmp_path / "docs_chunk_01.md").write_text("alpha", encoding="utf-8")

    counts = count_chunk_tokens([_chunk(1, "a"), _chunk(2, "b")], str(tmp_path),
                                "docs_chunk_", "md", "cl100k")

    assert len(counts) == 1
