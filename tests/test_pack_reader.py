"""Tests for loading packed JSONL chunks."""

import json
import os

from dograpper.lib.pack_reader import PackedChunk, load_chunks


def _write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def test_load_chunks_reads_fields(tmp_path):
    _write_jsonl(str(tmp_path / "docs_chunk_01.jsonl"), [
        {"id": "01_a.html", "source": "a.html", "words": 3,
         "content": "hello world text", "breadcrumb": ["Intro", "Setup"],
         "readiness_grade": "A", "schema_version": "v1"},
    ])
    chunks = load_chunks(str(tmp_path))
    assert len(chunks) == 1
    c = chunks[0]
    assert isinstance(c, PackedChunk)
    assert c.id == "01_a.html"
    assert c.source == "a.html"
    assert c.text == "hello world text"
    assert c.breadcrumb == ["Intro", "Setup"]
    assert c.grade == "A"
    assert c.words == 3


def test_load_chunks_missing_optional_fields(tmp_path):
    _write_jsonl(str(tmp_path / "docs_chunk_01.jsonl"), [
        {"id": "01_a", "source": "a", "content": "x y", "words": 2,
         "schema_version": "v1"},
    ])
    c = load_chunks(str(tmp_path))[0]
    assert c.breadcrumb == []
    assert c.grade == ""


def test_load_chunks_skips_blank_and_malformed_lines(tmp_path):
    path = str(tmp_path / "docs_chunk_01.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"id": "01_a", "source": "a", "content": "ok", "words": 1}\n')
        f.write("\n")
        f.write("{not valid json}\n")
    chunks = load_chunks(str(tmp_path))
    assert len(chunks) == 1
    assert chunks[0].id == "01_a"


def test_load_chunks_multiple_files_sorted(tmp_path):
    _write_jsonl(str(tmp_path / "docs_chunk_02.jsonl"),
                 [{"id": "02_b", "source": "b", "content": "b", "words": 1}])
    _write_jsonl(str(tmp_path / "docs_chunk_01.jsonl"),
                 [{"id": "01_a", "source": "a", "content": "a", "words": 1}])
    chunks = load_chunks(str(tmp_path))
    assert [c.id for c in chunks] == ["01_a", "02_b"]


def test_load_chunks_empty_dir_returns_empty(tmp_path):
    assert load_chunks(str(tmp_path)) == []
