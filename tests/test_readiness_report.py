"""Tests for the readiness report (--report): removed-block diff,
HTML report generation and colorized terminal summary."""

import re

from dograpper.utils.readiness_report import (
    PageReadiness,
    find_removed_blocks,
    format_terminal_report,
    generate_html_report,
)
from dograpper.utils.scorer import BoundaryIssue, ChunkScore


def _strip_ansi(text):
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def _score(chunk_id, score, grade, noise_ratio=0.1, boundary=True, depth=2, words=100):
    return ChunkScore(
        chunk_id=chunk_id,
        word_count=words,
        noise_ratio=noise_ratio,
        boundary_integrity=boundary,
        context_depth=depth,
        score=score,
        grade=grade,
    )


# ---------------------------------------------------------------------------
# Unit tests: find_removed_blocks
# ---------------------------------------------------------------------------

class TestFindRemovedBlocks:
    def test_removed_blocks_in_document_order(self):
        raw = "Nav menu\n\nReal content here\n\nFooter text"
        extracted = "Real content here"
        assert find_removed_blocks(raw, extracted) == ["Nav menu", "Footer text"]

    def test_no_difference_returns_empty(self):
        text = "Same content\n\nOther block"
        assert find_removed_blocks(text, text) == []

    def test_caps_at_max_samples(self):
        raw = "\n\n".join(f"boiler {i}" for i in range(10)) + "\n\nkeep"
        extracted = "keep"
        removed = find_removed_blocks(raw, extracted, max_samples=5)
        assert removed == ["boiler 0", "boiler 1", "boiler 2", "boiler 3", "boiler 4"]

    def test_truncates_long_blocks(self):
        raw = "x" * 500 + "\n\nkeep"
        extracted = "keep"
        removed = find_removed_blocks(raw, extracted, max_chars=200)
        assert len(removed) == 1
        assert len(removed[0]) == 200

    def test_empty_blocks_ignored(self):
        raw = "content\n\n\n\n  \n\nnoise"
        extracted = "content"
        assert find_removed_blocks(raw, extracted) == ["noise"]


# ---------------------------------------------------------------------------
# Unit tests: generate_html_report
# ---------------------------------------------------------------------------

def _sample_inputs():
    scores = [
        _score("docs_chunk_01", 0.90, "A", noise_ratio=0.05, depth=2),
        _score("docs_chunk_02", 0.30, "C", noise_ratio=0.60, boundary=False, depth=0),
    ]
    pages = {
        "docs_chunk_01": [PageReadiness(
            relative_path="docs/good.html",
            raw_words=1000,
            extracted_words=950,
            noise_ratio=0.05,
            headings_count=3,
            max_heading_level=2,
            first_headings=["Introduction"],
            removed_samples=["Nav menu"],
        )],
        "docs_chunk_02": [PageReadiness(
            relative_path="docs/bad.html",
            raw_words=2000,
            extracted_words=800,
            noise_ratio=0.6,
            removed_samples=["Cookie banner text", "<script>alert('x')</script>"],
        )],
    }
    issues = {
        "docs_chunk_01": [],
        "docs_chunk_02": [BoundaryIssue(kind="code_fence", line=12, snippet="```python")],
    }
    return scores, pages, issues


class TestGenerateHtmlReport:
    def test_full_html_document(self):
        report = generate_html_report(*_sample_inputs())
        assert report.startswith("<!DOCTYPE html>")
        assert "<style>" in report

    def test_summary_header(self):
        report = generate_html_report(*_sample_inputs())
        assert "0.60" in report          # avg of 0.90 and 0.30
        assert "2" in report             # total chunks

    def test_contains_per_page_before_after(self):
        report = generate_html_report(*_sample_inputs())
        assert "docs/good.html" in report
        assert "docs/bad.html" in report
        assert "1,000" in report
        assert "950" in report
        assert "2,000" in report
        assert "800" in report

    def test_worst_first_ordering(self):
        report = generate_html_report(*_sample_inputs())
        assert report.index("docs_chunk_02") < report.index("docs_chunk_01")

    def test_tie_break_by_chunk_id(self):
        scores = [
            _score("docs_chunk_03", 0.50, "B"),
            _score("docs_chunk_01", 0.50, "B"),
        ]
        report = generate_html_report(scores, {}, {})
        assert report.index("docs_chunk_01") < report.index("docs_chunk_03")

    def test_grade_css_classes(self):
        report = generate_html_report(*_sample_inputs())
        assert "grade-a" in report
        assert "grade-c" in report

    def test_noise_penalty_shows_removed_samples(self):
        report = generate_html_report(*_sample_inputs())
        assert "Cookie banner text" in report
        assert "Nav menu" in report

    def test_boundary_penalty_shows_issue_location(self):
        report = generate_html_report(*_sample_inputs())
        assert "```python" in report
        assert "12" in report

    def test_context_penalty_shows_headings_or_absence(self):
        report = generate_html_report(*_sample_inputs())
        assert "Introduction" in report
        assert "No headings found" in report

    def test_escapes_malicious_content(self):
        report = generate_html_report(*_sample_inputs())
        assert "<script>" not in report
        assert "&lt;script&gt;" in report

    def test_deterministic(self):
        first = generate_html_report(*_sample_inputs())
        second = generate_html_report(*_sample_inputs())
        assert first == second


# ---------------------------------------------------------------------------
# Unit tests: format_terminal_report
# ---------------------------------------------------------------------------

class TestFormatTerminalReport:
    def test_one_line_per_chunk_worst_first(self):
        scores = [
            _score("docs_chunk_01", 0.90, "A", noise_ratio=0.05),
            _score("docs_chunk_02", 0.30, "C", noise_ratio=0.60, boundary=False, depth=0),
        ]
        out = _strip_ansi(format_terminal_report(scores, "/tmp/out/readiness-report.html"))
        chunk_lines = [l for l in out.split("\n") if "docs_chunk_" in l]
        assert len(chunk_lines) == 2
        assert "docs_chunk_02" in chunk_lines[0]
        assert "docs_chunk_01" in chunk_lines[1]

    def test_contains_grade_letters(self):
        scores = [
            _score("docs_chunk_01", 0.90, "A"),
            _score("docs_chunk_02", 0.30, "C", boundary=False, depth=0),
        ]
        out = _strip_ansi(format_terminal_report(scores, "report.html"))
        assert " A " in out or "[A]" in out
        assert " C " in out or "[C]" in out

    def test_contains_report_path(self):
        scores = [_score("docs_chunk_01", 0.90, "A")]
        out = _strip_ansi(format_terminal_report(scores, "/tmp/out/readiness-report.html"))
        assert "/tmp/out/readiness-report.html" in out

    def test_dominant_penalty_noise(self):
        scores = [_score("docs_chunk_01", 0.50, "B", noise_ratio=0.9,
                         boundary=True, depth=2)]
        out = _strip_ansi(format_terminal_report(scores, "r.html"))
        assert "noise" in out

    def test_dominant_penalty_boundary(self):
        scores = [_score("docs_chunk_01", 0.60, "B", noise_ratio=0.1,
                         boundary=False, depth=2)]
        out = _strip_ansi(format_terminal_report(scores, "r.html"))
        assert "boundary" in out

    def test_dominant_penalty_context(self):
        scores = [_score("docs_chunk_01", 0.66, "B", noise_ratio=0.1,
                         boundary=True, depth=0)]
        out = _strip_ansi(format_terminal_report(scores, "r.html"))
        assert "context" in out
