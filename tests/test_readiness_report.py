"""Tests for the readiness report (--report): removed-block diff,
HTML report generation and colorized terminal summary."""

import json
import os
import tempfile

from click.testing import CliRunner

from dograpper.commands.pack import pack
from dograpper.utils.readiness_report import (
    PageReadiness,
    find_removed_blocks,
    format_terminal_report,
    generate_html_report,
)
from dograpper.utils.scorer import BoundaryIssue, ChunkScore


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
            boundary_issues=[BoundaryIssue(kind="code_fence", line=12, snippet="```python")],
        )],
    }
    return scores, pages


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
        report = generate_html_report(scores, {})
        assert report.index("docs_chunk_01") < report.index("docs_chunk_03")

    def test_grade_css_classes(self):
        report = generate_html_report(*_sample_inputs())
        assert "grade-a" in report
        assert "grade-c" in report

    def test_noise_penalty_shows_removed_samples(self):
        report = generate_html_report(*_sample_inputs())
        assert "Cookie banner text" in report
        assert "Nav menu" in report

    def test_boundary_penalty_shows_per_page_issue_location(self):
        report = generate_html_report(*_sample_inputs())
        assert "```python" in report
        assert "line 12" in report
        # Attribution: issue names its source page and says the line is
        # relative to that page's extracted content, not the chunk file.
        issue_pos = report.index("code_fence")
        assert "docs/bad.html" in report[issue_pos - 200:issue_pos + 200]
        assert "extracted content" in report

    def test_broken_boundary_without_page_issues_shows_fallback(self):
        scores = [_score("docs_chunk_01", 0.40, "C", boundary=False, depth=0)]
        pages = {"docs_chunk_01": [PageReadiness(
            relative_path="docs/a.html",
            raw_words=100,
            extracted_words=100,
            noise_ratio=0.0,
        )]}
        report = generate_html_report(scores, pages)
        assert "not attributable" in report

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
    def test_one_row_per_chunk_worst_first(self):
        scores = [
            _score("docs_chunk_01", 0.90, "A", noise_ratio=0.05),
            _score("docs_chunk_02", 0.30, "C", noise_ratio=0.60, boundary=False, depth=0),
        ]
        rows = format_terminal_report(scores, "/tmp/out/readiness-report.html")
        chunk_rows = [(g, t) for g, t in rows if g is not None]
        assert len(chunk_rows) == 2
        assert chunk_rows[0][0] == "C"
        assert "docs_chunk_02" in chunk_rows[0][1]
        assert chunk_rows[1][0] == "A"
        assert "docs_chunk_01" in chunk_rows[1][1]

    def test_header_and_path_rows_have_no_grade(self):
        scores = [_score("docs_chunk_01", 0.90, "A")]
        rows = format_terminal_report(scores, "/tmp/out/readiness-report.html")
        assert (None, "Readiness report (worst first):") in rows
        assert rows[-1][0] is None
        assert "/tmp/out/readiness-report.html" in rows[-1][1]

    def test_rows_are_unstyled(self):
        # utils stays framework-free: styling is the caller's job
        scores = [
            _score("docs_chunk_01", 0.90, "A"),
            _score("docs_chunk_02", 0.30, "C", boundary=False, depth=0),
        ]
        rows = format_terminal_report(scores, "r.html")
        assert all("\x1b" not in text for _, text in rows)

    def test_dominant_penalty_noise(self):
        scores = [_score("docs_chunk_01", 0.50, "B", noise_ratio=0.9,
                         boundary=True, depth=2)]
        rows = format_terminal_report(scores, "r.html")
        assert any("noise" in t for g, t in rows if g is not None)

    def test_dominant_penalty_boundary(self):
        scores = [_score("docs_chunk_01", 0.60, "B", noise_ratio=0.1,
                         boundary=False, depth=2)]
        rows = format_terminal_report(scores, "r.html")
        assert any("boundary" in t for g, t in rows if g is not None)

    def test_dominant_penalty_context(self):
        scores = [_score("docs_chunk_01", 0.66, "B", noise_ratio=0.1,
                         boundary=True, depth=0)]
        rows = format_terminal_report(scores, "r.html")
        assert any("context" in t for g, t in rows if g is not None)


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

def _make_html_tree(input_dir):
    os.makedirs(input_dir)
    with open(os.path.join(input_dir, "page.html"), "w", encoding="utf-8") as f:
        f.write(
            "<html><body>"
            "<nav><a href='#'>Home</a> <a href='#'>About</a></nav>"
            "<main><h1>Guide Title</h1><p>"
            + "Real content words here. " * 100
            + "</p></main>"
            "<footer>Copyright footer boilerplate</footer>"
            "</body></html>"
        )


class TestReportCLI:
    def test_report_writes_html_and_implies_score(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = os.path.join(tmp, "docs")
            output_dir = os.path.join(tmp, "chunks")
            _make_html_tree(input_dir)

            result = runner.invoke(pack, [
                input_dir, "-o", output_dir, "--report",
            ], catch_exceptions=False)

            assert result.exit_code == 0
            report_path = os.path.join(output_dir, "readiness-report.html")
            assert os.path.exists(report_path)
            # --report implies --score (with an explicit note)
            assert os.path.exists(os.path.join(output_dir, "llm-readiness.json"))
            assert "--score" in result.output
            # Terminal summary with report path
            assert "Readiness report (worst first):" in result.output
            assert report_path in result.output

            with open(report_path, encoding="utf-8") as f:
                report_html = f.read()
            assert "page.html" in report_html
            assert "Guide Title" in report_html

    def test_report_with_dry_run_errors(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = os.path.join(tmp, "docs")
            _make_html_tree(input_dir)

            result = runner.invoke(pack, [
                input_dir, "-o", os.path.join(tmp, "chunks"),
                "--report", "--dry-run",
            ])

            assert result.exit_code == 1
            assert "--report requires a real pack run" in result.output

    def test_without_report_no_html_written(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = os.path.join(tmp, "docs")
            output_dir = os.path.join(tmp, "chunks")
            _make_html_tree(input_dir)

            result = runner.invoke(pack, [
                input_dir, "-o", output_dir, "--score",
            ], catch_exceptions=False)

            assert result.exit_code == 0
            assert not os.path.exists(os.path.join(output_dir, "readiness-report.html"))
            assert "Readiness report (worst first):" not in result.output

    def test_report_survives_extraction_failure(self):
        """Regression: a page whose extraction raises (e.g. a valueless
        attribute like <div class>) must not abort the whole pack run."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            input_dir = os.path.join(tmp, "docs")
            output_dir = os.path.join(tmp, "chunks")
            _make_html_tree(input_dir)
            with open(os.path.join(input_dir, "malformed.html"), "w", encoding="utf-8") as f:
                f.write("<html><body><div class><p>content with broken attribute</p>"
                        "</div></body></html>")

            result = runner.invoke(pack, [
                input_dir, "-o", output_dir, "--report",
            ], catch_exceptions=False)

            assert result.exit_code == 0
            assert os.path.exists(os.path.join(output_dir, "readiness-report.html"))

    def test_report_from_config_file(self):
        runner = CliRunner()
        with runner.isolated_filesystem():
            _make_html_tree("docs")
            with open(".dograpper.json", "w", encoding="utf-8") as f:
                json.dump({"pack": {"report": True}}, f)

            result = runner.invoke(pack, [
                "docs", "-o", "chunks",
            ], catch_exceptions=False)

            assert result.exit_code == 0
            assert os.path.exists(os.path.join("chunks", "readiness-report.html"))

    def test_no_report_flag_overrides_config_for_dry_run(self):
        """Config {"pack": {"report": true}} must not trap --dry-run:
        an explicit --no-report wins over the config file."""
        runner = CliRunner()
        with runner.isolated_filesystem():
            _make_html_tree("docs")
            with open(".dograpper.json", "w", encoding="utf-8") as f:
                json.dump({"pack": {"report": True}}, f)

            result = runner.invoke(pack, [
                "docs", "-o", "chunks", "--no-report", "--dry-run",
            ], catch_exceptions=False)

            assert result.exit_code == 0
            assert not os.path.exists(os.path.join("chunks", "readiness-report.html"))
