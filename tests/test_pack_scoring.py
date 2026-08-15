"""Tests for the readiness scoring pass over a pack run's chunks."""

from dograpper.lib.chunker import Chunk, ChunkFile
from dograpper.lib.pack_scoring import score_chunks
from dograpper.utils.heading_extractor import Heading


def _chunk(index, *rel_paths):
    return Chunk(
        index=index,
        files=[ChunkFile(rp, 10) for rp in rel_paths],
        total_words=10 * len(rel_paths),
    )


def _page(tmp_path, name, body, boilerplate=""):
    (tmp_path / name).write_text(
        f"<html><body><nav>{boilerplate}</nav><main>{body}</main></body></html>",
        encoding="utf-8")
    return name


# ---------------------------------------------------------------------------
# Shape
# ---------------------------------------------------------------------------

def test_one_score_per_chunk_with_prefixed_padded_id(tmp_path):
    _page(tmp_path, "a.html", "<p>Alpha body text.</p>")
    _page(tmp_path, "b.html", "<p>Beta body text.</p>")

    result = score_chunks([_chunk(1, "a.html"), _chunk(2, "b.html")],
                          str(tmp_path), "docs_chunk_", no_extract=False)

    assert [s.chunk_id for s in result.scores] == ["docs_chunk_01", "docs_chunk_02"]


def test_report_pages_only_collected_when_asked(tmp_path):
    _page(tmp_path, "a.html", "<p>Alpha body text.</p>", boilerplate="Nav noise")
    chunks = [_chunk(1, "a.html")]

    without = score_chunks(chunks, str(tmp_path), "docs_chunk_", no_extract=False)
    assert without.report_pages == {}

    with_report = score_chunks(chunks, str(tmp_path), "docs_chunk_",
                               no_extract=False, with_report=True)
    pages = with_report.report_pages["docs_chunk_01"]
    assert [p.relative_path for p in pages] == ["a.html"]
    # Extraction dropped the nav, so the page carries measurable noise.
    assert pages[0].raw_words > pages[0].extracted_words
    assert pages[0].noise_ratio > 0


def test_header_map_shape_and_rounding(tmp_path):
    _page(tmp_path, "a.html", "<p>Alpha body text.</p>")

    result = score_chunks([_chunk(1, "a.html")], str(tmp_path), "docs_chunk_",
                          no_extract=False)
    entry = result.header_map()["docs_chunk_01"]

    assert set(entry) == {"score", "grade", "noise_ratio"}
    assert entry["grade"] in {"A", "B", "C"}
    assert round(entry["score"], 2) == entry["score"]
    assert round(entry["noise_ratio"], 3) == entry["noise_ratio"]


# ---------------------------------------------------------------------------
# Inputs that change the score
# ---------------------------------------------------------------------------

def test_no_extract_reports_no_noise(tmp_path):
    _page(tmp_path, "a.html", "<p>Alpha body text.</p>",
          boilerplate="Nav noise that extraction would strip")

    extracted = score_chunks([_chunk(1, "a.html")], str(tmp_path), "docs_chunk_",
                             no_extract=False)
    verbatim = score_chunks([_chunk(1, "a.html")], str(tmp_path), "docs_chunk_",
                            no_extract=True)

    assert extracted.scores[0].noise_ratio > 0
    assert verbatim.scores[0].noise_ratio == 0


def test_headings_raise_context_depth(tmp_path):
    _page(tmp_path, "a.html", "<h1>Guide</h1><h2>Setup</h2><p>Body text.</p>")
    chunks = [_chunk(1, "a.html")]

    flat = score_chunks(chunks, str(tmp_path), "docs_chunk_", no_extract=False)
    nested = score_chunks(
        chunks, str(tmp_path), "docs_chunk_", no_extract=False,
        heading_map={"a.html": [Heading(1, "Guide", 0), Heading(2, "Setup", 10)]})

    assert nested.scores[0].context_depth > flat.scores[0].context_depth


def test_text_override_drives_the_boundary_check(tmp_path):
    """Dedup rewrites the text that gets written, so it must drive the score."""
    _page(tmp_path, "a.html", "<p>A complete sentence ending properly.</p>")
    chunks = [_chunk(1, "a.html")]

    clean = score_chunks(chunks, str(tmp_path), "docs_chunk_", no_extract=False)
    truncated = score_chunks(
        chunks, str(tmp_path), "docs_chunk_", no_extract=False,
        text_overrides={"a.html": "Body text\n```python\nprint(1)"})

    assert clean.scores[0].boundary_integrity
    # The override left an unclosed code fence, which the clean text has not.
    assert not truncated.scores[0].boundary_integrity
    assert truncated.scores[0].word_count == 4


# ---------------------------------------------------------------------------
# Failure tolerance
# ---------------------------------------------------------------------------

def test_missing_source_file_is_skipped_not_fatal(tmp_path):
    _page(tmp_path, "a.html", "<p>Alpha body text.</p>")

    result = score_chunks([_chunk(1, "a.html", "vanished.html")], str(tmp_path),
                          "docs_chunk_", no_extract=False)

    assert len(result.scores) == 1
    assert result.scores[0].word_count > 0


def test_non_html_file_counts_as_its_own_extraction(tmp_path):
    (tmp_path / "notes.txt").write_text("plain text notes here", encoding="utf-8")

    result = score_chunks([_chunk(1, "notes.txt")], str(tmp_path), "docs_chunk_",
                          no_extract=False)

    assert result.scores[0].noise_ratio == 0
