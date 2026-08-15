"""Tests for the explain preview: section parsing, sidecars, CLI modes."""

import json
import os

from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.utils.chunk_inspector import (
    discover_chunks,
    parse_chunk_sections,
    load_sidecar,
    readiness_for,
    cross_refs_for,
)


V1_CHUNK = """<!-- dograpper-context-v1
{
  "source": "guide/intro.html",
  "url": "https://example.com/guide/intro.html",
  "word_count": 6,
  "context_breadcrumb": [
    "User Guide",
    "Introduction"
  ],
  "llm_readiness": {
    "score": 91.5,
    "grade": "A",
    "noise_ratio": 0.05
  },
  "schema_version": "v1"
}
-->

Welcome to the intro with [-> docs_chunk_01] pointer.

<!-- dograpper-context-v1
{
  "source": "guide/setup.html",
  "word_count": 4,
  "context_breadcrumb": [
    "User Guide",
    "Setup"
  ],
  "schema_version": "v1"
}
-->

Setup instructions go here."""


# ---------------------------------------------------------------------------
# parse_chunk_sections
# ---------------------------------------------------------------------------

def test_parse_sections_with_v1_headers():
    sections = parse_chunk_sections(V1_CHUNK)
    assert len(sections) == 2
    assert sections[0].source == "guide/intro.html"
    assert sections[0].breadcrumb == ["User Guide", "Introduction"]
    assert sections[0].header["llm_readiness"]["grade"] == "A"
    assert "Welcome to the intro" in sections[0].content
    assert sections[1].source == "guide/setup.html"
    assert sections[1].content == "Setup instructions go here."


def test_parse_sections_with_source_markers():
    text = ("<!-- SOURCE: a.html -->\n\nContent A\n\n"
            "<!-- SOURCE: b.html -->\n\nContent B")
    sections = parse_chunk_sections(text)
    assert len(sections) == 2
    assert sections[0].source == "a.html"
    assert sections[0].header is None
    assert sections[0].content == "Content A"
    assert sections[1].source == "b.html"


def test_parse_sections_txt_source_markers():
    text = "=== SOURCE: a.html ===\n\nPlain content"
    sections = parse_chunk_sections(text)
    assert len(sections) == 1
    assert sections[0].source == "a.html"
    assert sections[0].content == "Plain content"


def test_parse_sections_no_markers_single_section():
    sections = parse_chunk_sections("Just raw text.")
    assert len(sections) == 1
    assert sections[0].source == ""
    assert sections[0].content == "Just raw text."


def test_parse_sections_malformed_header_json_tolerated():
    text = "<!-- dograpper-context-v1\n{not json}\n-->\n\nBody text"
    sections = parse_chunk_sections(text)
    assert len(sections) == 1
    assert sections[0].header is None
    assert sections[0].content == "Body text"


# ---------------------------------------------------------------------------
# discover_chunks / sidecars
# ---------------------------------------------------------------------------

def test_discover_chunks_sorted_and_typed(tmp_path):
    (tmp_path / "docs_chunk_01.md").write_text("b", encoding="utf-8")
    (tmp_path / "docs_chunk_00.jsonl").write_text("{}", encoding="utf-8")
    (tmp_path / "other.md").write_text("x", encoding="utf-8")
    infos = discover_chunks(str(tmp_path))
    assert [(c.chunk_id, c.format) for c in infos] == [
        ("docs_chunk_00", "jsonl"), ("docs_chunk_01", "md")]


def test_load_sidecar_missing_and_invalid(tmp_path):
    assert load_sidecar(str(tmp_path), "llm-readiness.json") is None
    (tmp_path / "cross_refs.json").write_text("{broken", encoding="utf-8")
    assert load_sidecar(str(tmp_path), "cross_refs.json") is None


def test_readiness_and_cross_refs_lookup():
    readiness = {"chunks": [{"chunk_id": "docs_chunk_00", "grade": "B"}]}
    assert readiness_for(readiness, "docs_chunk_00")["grade"] == "B"
    assert readiness_for(readiness, "docs_chunk_99") is None
    assert readiness_for(None, "docs_chunk_00") is None

    cross = {"docs_chunk_00": {"references_to": ["docs_chunk_01"]}}
    assert cross_refs_for(cross, "docs_chunk_00")["references_to"] == ["docs_chunk_01"]
    assert cross_refs_for(cross, "docs_chunk_99") is None
    assert cross_refs_for(None, "docs_chunk_00") is None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _write_pack_fixture(fmt="md"):
    """Create a minimal chunks dir in the CWD. Returns the dir name."""
    os.makedirs("chunks", exist_ok=True)
    if fmt == "md":
        with open("chunks/docs_chunk_00.md", "w", encoding="utf-8") as f:
            f.write(V1_CHUNK)
    else:
        records = [
            {"id": "00_guide/intro.html", "source": "guide/intro.html",
             "words": 6, "content": "Welcome to the intro page content.",
             "breadcrumb": ["User Guide", "Introduction"],
             "readiness_grade": "A", "schema_version": "v1"},
        ]
        with open("chunks/docs_chunk_00.jsonl", "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
    with open("chunks/llm-readiness.json", "w", encoding="utf-8") as f:
        json.dump({"summary": {}, "chunks": [
            {"chunk_id": "docs_chunk_00", "word_count": 10,
             "noise_ratio": 0.05, "boundary_integrity": True,
             "context_depth": 2, "score": 91.5, "grade": "A"}]}, f)
    with open("chunks/cross_refs.json", "w", encoding="utf-8") as f:
        json.dump({"docs_chunk_00": {
            "references_to": ["docs_chunk_01"],
            "referenced_by": [],
            "links": [{"source_file": "guide/intro.html",
                       "target_chunk": "docs_chunk_01"}]}}, f)
    return "chunks"


def test_explain_list_mode():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_pack_fixture("md")
        result = runner.invoke(cli, ["explain", "chunks"])
        assert result.exit_code == 0, result.output
        assert "docs_chunk_00.md" in result.output
        assert "grade A" in result.output


def test_explain_chunk_md_shows_headers_and_sidecars():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_pack_fixture("md")
        result = runner.invoke(cli, ["explain", "chunks", "docs_chunk_00"])
        assert result.exit_code == 0, result.output
        assert "guide/intro.html" in result.output
        assert "User Guide > Introduction" in result.output
        assert "grade A" in result.output
        assert "references_to: docs_chunk_01" in result.output
        # cross-ref pointer annotations are visible in the content preview
        assert "[-> docs_chunk_01]" in result.output


def test_explain_chunk_bare_index_accepted():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_pack_fixture("md")
        result = runner.invoke(cli, ["explain", "chunks", "00"])
        assert result.exit_code == 0, result.output
        assert "docs_chunk_00.md" in result.output


def test_explain_chunk_jsonl_records():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_pack_fixture("jsonl")
        result = runner.invoke(cli, ["explain", "chunks", "docs_chunk_00"])
        assert result.exit_code == 0, result.output
        assert "00_guide/intro.html" in result.output
        assert "User Guide > Introduction" in result.output
        assert "Grade: A" in result.output


def test_explain_unknown_chunk_errors():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_pack_fixture("md")
        result = runner.invoke(cli, ["explain", "chunks", "docs_chunk_42"])
        assert result.exit_code == 1
        assert "not found" in result.output
        assert "docs_chunk_00" in result.output  # lists what exists


def test_explain_empty_dir_errors():
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("empty", exist_ok=True)
        result = runner.invoke(cli, ["explain", "empty"])
        assert result.exit_code == 1
        assert "no chunk files" in result.output


def test_explain_truncates_long_content_by_default():
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("chunks", exist_ok=True)
        long_text = " ".join(f"word{i}" for i in range(200))
        with open("chunks/docs_chunk_00.md", "w", encoding="utf-8") as f:
            f.write(long_text)
        result = runner.invoke(cli, ["explain", "chunks", "docs_chunk_00"])
        assert result.exit_code == 0
        assert "[…]" in result.output
        assert "word199" not in result.output

        result_full = runner.invoke(
            cli, ["explain", "chunks", "docs_chunk_00", "--full"])
        assert result_full.exit_code == 0
        assert "word199" in result_full.output
        assert "[…]" not in result_full.output


def test_explain_writes_nothing_to_disk():
    runner = CliRunner()
    with runner.isolated_filesystem():
        chunks_dir = _write_pack_fixture("md")
        before = {f: os.path.getmtime(os.path.join(chunks_dir, f))
                  for f in os.listdir(chunks_dir)}
        result = runner.invoke(cli, ["explain", "chunks", "docs_chunk_00"])
        assert result.exit_code == 0
        after = {f: os.path.getmtime(os.path.join(chunks_dir, f))
                 for f in os.listdir(chunks_dir)}
        assert before == after


# ---------------------------------------------------------------------------
# Integration — pack then explain
# ---------------------------------------------------------------------------

def test_pack_then_explain_roundtrip():
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("docs/guide", exist_ok=True)
        with open("docs/guide/intro.html", "w", encoding="utf-8") as f:
            f.write("<html><body><main><h1>Guide</h1><h2>Intro</h2>"
                    "<p>Real documentation body with enough words to matter.</p>"
                    "</main></body></html>")
        result = runner.invoke(cli, [
            "pack", "docs", "-o", "chunks", "--context-header", "--score"])
        assert result.exit_code == 0, result.output

        # pack numbers chunks starting at 01
        result = runner.invoke(cli, ["explain", "chunks", "docs_chunk_01"])
        assert result.exit_code == 0, result.output
        assert "guide/intro.html" in result.output
        assert "Guide" in result.output
