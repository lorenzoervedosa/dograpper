import os
import json
import tempfile

import pytest
from click.testing import CliRunner

from dograpper.utils.scorer import (
    calculate_noise_ratio,
    check_boundary_integrity,
    calculate_context_depth,
    calculate_grade,
    find_boundary_issues,
    penalty_breakdown,
    score_chunk,
)
from dograpper.commands.pack import pack


class TestNoiseRatio:
    def test_no_noise(self):
        assert calculate_noise_ratio(1000, 1000) == 0.0

    def test_half_noise(self):
        assert calculate_noise_ratio(1000, 500) == 0.5

    def test_all_noise(self):
        assert calculate_noise_ratio(1000, 0) == 1.0

    def test_zero_raw(self):
        assert calculate_noise_ratio(0, 0) == 0.0

    def test_extracted_greater_than_raw(self):
        assert calculate_noise_ratio(100, 150) == 0.0


class TestBoundaryIntegrity:
    def test_balanced_fences(self):
        assert check_boundary_integrity("```python\ncode\n```") is True

    def test_unbalanced_fences(self):
        assert check_boundary_integrity("```python\ncode\nmore") is False

    def test_balanced_pre(self):
        assert check_boundary_integrity("<pre>code</pre>") is True

    def test_unbalanced_pre(self):
        assert check_boundary_integrity("<pre>code without close") is False

    def test_no_blocks(self):
        assert check_boundary_integrity("Just regular text.") is True

    def test_multiple_fences(self):
        text = "```\nblock1\n```\n\n```\nblock2\n```"
        assert check_boundary_integrity(text) is True


class TestFindBoundaryIssues:
    def test_balanced_text_no_issues(self):
        text = "```python\ncode\n```\n\n<pre>snippet</pre>\n\nRegular text."
        assert find_boundary_issues(text) == []

    def test_plain_text_no_issues(self):
        assert find_boundary_issues("Just regular text.") == []

    def test_odd_fences_reports_last_fence(self):
        text = "intro\n```python\ncode\n```\nmore\n```js\ntail"
        issues = find_boundary_issues(text)
        assert len(issues) == 1
        assert issues[0].kind == "code_fence"
        assert issues[0].line == 6
        assert issues[0].snippet == "```js"

    def test_unclosed_pre_reports_first_unmatched_opener(self):
        text = '<pre>a</pre>\nmiddle\n<pre class="x">b'
        issues = find_boundary_issues(text)
        assert len(issues) == 1
        assert issues[0].kind == "pre_tag"
        assert issues[0].line == 3
        assert issues[0].snippet == '<pre class="x">b'

    def test_surplus_pre_closer_reports_first_surplus(self):
        text = "</pre>\n<pre>a</pre>"
        issues = find_boundary_issues(text)
        assert len(issues) == 1
        assert issues[0].kind == "pre_tag"
        assert issues[0].line == 1
        assert issues[0].snippet == "</pre>"

    def test_fence_and_pre_issues_together(self):
        text = "```\ncode\n\n<pre>never closed"
        issues = find_boundary_issues(text)
        kinds = [i.kind for i in issues]
        assert kinds == ["code_fence", "pre_tag"]


class TestContextDepth:
    def test_no_headings(self):
        assert calculate_context_depth(0, 0) == 0

    def test_h1_only(self):
        assert calculate_context_depth(5, 1) == 1

    def test_deep_hierarchy(self):
        assert calculate_context_depth(10, 3) == 3


class TestGrade:
    def test_grade_a(self):
        score, grade = calculate_grade(0.05, True, 3)
        assert grade == "A"
        assert score >= 0.8

    def test_grade_b(self):
        score, grade = calculate_grade(0.4, True, 1)
        assert grade == "B"

    def test_grade_c(self):
        score, grade = calculate_grade(0.9, False, 0)
        assert grade == "C"
        assert score < 0.5


class TestPenaltyBreakdown:
    def test_labels_and_values(self):
        penalties = penalty_breakdown(0.5, True, 1)
        assert [label for label, _ in penalties] == ["noise", "boundary", "context"]
        values = dict(penalties)
        assert values["noise"] == pytest.approx(0.2)
        assert values["boundary"] == 0.0
        assert values["context"] == pytest.approx(0.15)

    def test_broken_boundary_penalty(self):
        values = dict(penalty_breakdown(0.0, False, 2))
        assert values["noise"] == 0.0
        assert values["boundary"] == pytest.approx(0.3)
        assert values["context"] == 0.0

    def test_no_headings_penalty(self):
        values = dict(penalty_breakdown(1.0, True, 0))
        assert values["noise"] == pytest.approx(0.4)
        assert values["context"] == pytest.approx(0.3)

    def test_complements_calculate_grade(self):
        # The breakdown and the composite score must share one weighting:
        # score == 1 - sum(penalties), pinned with independent literals.
        score, _ = calculate_grade(0.5, True, 1)
        assert score == pytest.approx(0.65)
        assert sum(v for _, v in penalty_breakdown(0.5, True, 1)) == pytest.approx(0.35)


class TestScoreChunk:
    def test_full_scoring(self):
        cs = score_chunk(
            chunk_id="docs_chunk_01",
            text="```python\ncode\n```\nSome text here.",
            raw_words=100,
            extracted_words=80,
            headings_count=3,
            max_heading_level=2,
        )
        assert cs.chunk_id == "docs_chunk_01"
        assert cs.noise_ratio == pytest.approx(0.2)
        assert cs.boundary_integrity is True
        assert cs.context_depth == 2
        assert cs.grade in ("A", "B", "C")
        assert 0.0 <= cs.score <= 1.0

    def test_non_html_no_noise(self):
        cs = score_chunk(
            chunk_id="docs_chunk_02",
            text="plain text",
            raw_words=100,
            extracted_words=100,
            headings_count=0,
            max_heading_level=0,
        )
        assert cs.noise_ratio == 0.0

    def test_broken_boundary(self):
        cs = score_chunk(
            chunk_id="docs_chunk_03",
            text="```python\ncode without closing",
            raw_words=50,
            extracted_words=50,
            headings_count=0,
            max_heading_level=0,
        )
        assert cs.boundary_integrity is False


def _make_test_dir(tmpdir, files_dict):
    for rel, content in files_dict.items():
        fpath = os.path.join(tmpdir, rel)
        os.makedirs(os.path.dirname(fpath), exist_ok=True)
        with open(fpath, 'w', encoding='utf-8') as f:
            f.write(content)


class TestScoreCLI:
    def test_score_generates_json(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = os.path.join(tmpdir, "docs")
            output_dir = os.path.join(tmpdir, "chunks")
            _make_test_dir(input_dir, {
                "a.txt": " ".join(["word"] * 100),
                "b.txt": " ".join(["text"] * 100),
            })
            result = runner.invoke(pack, [
                input_dir, '-o', output_dir, '--score',
            ], catch_exceptions=False)
            assert result.exit_code == 0
            readiness_path = os.path.join(output_dir, "llm-readiness.json")
            assert os.path.exists(readiness_path)
            data = json.load(open(readiness_path))
            assert data["summary"]["total_chunks"] > 0
            assert 0 <= data["summary"]["avg_score"] <= 1
            for c in data["chunks"]:
                assert c["grade"] in ("A", "B", "C")
                assert 0 <= c["score"] <= 1

    def test_score_summary_output(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = os.path.join(tmpdir, "docs")
            output_dir = os.path.join(tmpdir, "chunks")
            _make_test_dir(input_dir, {"a.txt": "hello world"})
            result = runner.invoke(pack, [
                input_dir, '-o', output_dir, '--score',
            ], catch_exceptions=False)
            assert result.exit_code == 0
            assert "LLM Readiness:" in result.output

    def test_no_score_no_json(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = os.path.join(tmpdir, "docs")
            output_dir = os.path.join(tmpdir, "chunks")
            _make_test_dir(input_dir, {"a.txt": "hello world"})
            result = runner.invoke(pack, [
                input_dir, '-o', output_dir,
            ], catch_exceptions=False)
            assert result.exit_code == 0
            assert not os.path.exists(os.path.join(output_dir, "llm-readiness.json"))

    def test_dry_run_with_score(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = os.path.join(tmpdir, "docs")
            output_dir = os.path.join(tmpdir, "chunks")
            _make_test_dir(input_dir, {
                "page.html": "<html><body><h1>Title</h1><main><p>Content here words.</p></main></body></html>",
            })
            result = runner.invoke(pack, [
                input_dir, '-o', output_dir, '--dry-run', '--score',
            ], catch_exceptions=False)
            assert result.exit_code == 0
            assert "Readiness" in result.output
            assert "Grade" in result.output

    def test_score_with_context_header(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = os.path.join(tmpdir, "docs")
            output_dir = os.path.join(tmpdir, "chunks")
            _make_test_dir(input_dir, {
                "page.html": "<html><body><h1>Title</h1><h2>Section</h2><p>Content words here.</p></body></html>",
            })
            result = runner.invoke(pack, [
                input_dir, '-o', output_dir, '--score', '--context-header',
            ], catch_exceptions=False)
            assert result.exit_code == 0
            readiness_path = os.path.join(output_dir, "llm-readiness.json")
            data = json.load(open(readiness_path))
            # With headings, context_depth should be > 0
            assert any(c["context_depth"] > 0 for c in data["chunks"])
