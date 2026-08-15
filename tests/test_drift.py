"""Tests for lib/readiness_diff.py and the `dograpper drift` subcommand."""

import json
import os

from click.testing import CliRunner

from dograpper.cli import cli
from dograpper.lib.readiness_diff import (
    compare_readiness,
    render_markdown,
    render_text,
)


def _readiness(chunks):
    """Build a minimal llm-readiness.json-shaped dict."""
    return {
        "summary": {"total_chunks": len(chunks)},
        "chunks": [
            {"chunk_id": cid, "score": score, "grade": grade}
            for cid, score, grade in chunks
        ],
    }


OLD = _readiness([
    ("docs_chunk_01", 9.0, "A"),
    ("docs_chunk_02", 7.0, "B"),
    ("docs_chunk_04", 6.0, "C"),
])

NEW = _readiness([
    ("docs_chunk_01", 9.0, "A"),
    ("docs_chunk_02", 8.5, "A"),
    ("docs_chunk_03", 8.0, "A"),
])


# ---------------------------------------------------------------------------
# compare_readiness
# ---------------------------------------------------------------------------

def test_compare_detects_added_modified_removed():
    report = compare_readiness(OLD, NEW)

    assert report.first_run is False
    assert [(c.chunk_id, c.score, c.grade) for c in report.added] == [
        ("docs_chunk_03", 8.0, "A"),
    ]
    assert [(c.chunk_id, c.score, c.grade) for c in report.removed] == [
        ("docs_chunk_04", 6.0, "C"),
    ]
    assert [
        (c.chunk_id, c.old_grade, c.new_grade, c.old_score, c.new_score)
        for c in report.modified
    ] == [
        ("docs_chunk_02", "B", "A", 7.0, 8.5),
    ]
    assert report.has_drift is True


def test_compare_avg_scores():
    report = compare_readiness(OLD, NEW)
    # (9.0 + 7.0 + 6.0) / 3 and (9.0 + 8.5 + 8.0) / 3, hand-computed
    assert report.old_avg_score == 7.33
    assert report.new_avg_score == 8.5


def test_compare_first_run_reports_everything_as_added():
    report = compare_readiness(None, NEW)

    assert report.first_run is True
    assert [c.chunk_id for c in report.added] == [
        "docs_chunk_01", "docs_chunk_02", "docs_chunk_03",
    ]
    assert report.modified == []
    assert report.removed == []
    assert report.old_avg_score is None
    assert report.new_avg_score == 8.5
    assert report.has_drift is True


def test_compare_identical_snapshots_no_drift():
    report = compare_readiness(OLD, OLD)

    assert report.added == []
    assert report.modified == []
    assert report.removed == []
    assert report.has_drift is False


def test_compare_output_sorted_by_chunk_id():
    old = _readiness([("docs_chunk_09", 5.0, "C")])
    new = _readiness([
        ("docs_chunk_07", 8.0, "A"),
        ("docs_chunk_02", 7.0, "B"),
        ("docs_chunk_05", 6.0, "C"),
    ])
    report = compare_readiness(old, new)
    assert [c.chunk_id for c in report.added] == [
        "docs_chunk_02", "docs_chunk_05", "docs_chunk_07",
    ]


def test_compare_score_only_change_is_modified():
    old = _readiness([("docs_chunk_01", 8.0, "A")])
    new = _readiness([("docs_chunk_01", 8.4, "A")])
    report = compare_readiness(old, new)
    assert len(report.modified) == 1
    assert report.modified[0].old_score == 8.0
    assert report.modified[0].new_score == 8.4


# ---------------------------------------------------------------------------
# render_markdown
# ---------------------------------------------------------------------------

MARKDOWN_WORKED_EXAMPLE = """\
<!-- dograpper-drift -->
## Context drift report

**Summary:** 1 added, 1 modified, 1 removed — avg score 7.33 → 8.50

### Added chunks (1)

- `docs_chunk_03` — score 8.00, grade A

### Modified chunks (1)

- `docs_chunk_02` — grade B → A, score 7.00 → 8.50 (+1.50)

### Removed chunks (1)

- `docs_chunk_04` — score 6.00, grade C"""


def test_render_markdown_worked_example():
    report = compare_readiness(OLD, NEW)
    assert render_markdown(report, None) == MARKDOWN_WORKED_EXAMPLE


def test_render_markdown_starts_with_marker():
    report = compare_readiness(OLD, NEW)
    output = render_markdown(report, None)
    assert output.splitlines()[0] == "<!-- dograpper-drift -->"


def test_render_markdown_first_run():
    report = compare_readiness(None, _readiness([("docs_chunk_01", 8.0, "A")]))
    expected = """\
<!-- dograpper-drift -->
## Context drift report

**First run** — no previous snapshot; every chunk is reported as added.

**Summary:** 1 added, 0 modified, 0 removed — avg score n/a → 8.00

### Added chunks (1)

- `docs_chunk_01` — score 8.00, grade A"""
    assert render_markdown(report, None) == expected


def test_render_markdown_no_drift():
    report = compare_readiness(OLD, OLD)
    expected = """\
<!-- dograpper-drift -->
## Context drift report

**Summary:** no drift — avg score 7.33 → 7.33"""
    assert render_markdown(report, None) == expected


def test_render_markdown_without_delta_omits_source_section():
    report = compare_readiness(OLD, NEW)
    assert "Source file drift" not in render_markdown(report, None)


def test_render_markdown_with_delta_manifest():
    report = compare_readiness(OLD, OLD)
    delta = {
        "added": ["docs/new.html"],
        "modified": ["docs/index.html", "docs/api.html"],
        "removed": [],
    }
    output = render_markdown(report, delta)
    expected_tail = """\
### Source file drift

**Added files (1)**

- `docs/new.html`

**Modified files (2)**

- `docs/api.html`
- `docs/index.html`"""
    assert output.endswith(expected_tail)
    assert "_No source drift recorded._" not in output


def test_render_markdown_delta_manifest_empty_lists():
    report = compare_readiness(OLD, OLD)
    delta = {"added": [], "modified": [], "removed": []}
    output = render_markdown(report, delta)
    assert output.endswith("### Source file drift\n\n_No source file changes._")


def test_render_markdown_negative_score_delta():
    report = compare_readiness(
        _readiness([("docs_chunk_01", 8.5, "A")]),
        _readiness([("docs_chunk_01", 7.0, "B")]),
    )
    output = render_markdown(report, None)
    assert "- `docs_chunk_01` — grade A → B, score 8.50 → 7.00 (-1.50)" in output


# ---------------------------------------------------------------------------
# render_text
# ---------------------------------------------------------------------------

TEXT_WORKED_EXAMPLE = """\
Context drift report
====================
Summary: 1 added, 1 modified, 1 removed | avg score 7.33 -> 8.50

Added chunks (1):
  docs_chunk_03  score 8.00  grade A

Modified chunks (1):
  docs_chunk_02  grade B -> A  score 7.00 -> 8.50 (+1.50)

Removed chunks (1):
  docs_chunk_04  score 6.00  grade C"""


def test_render_text_worked_example():
    report = compare_readiness(OLD, NEW)
    assert render_text(report, None) == TEXT_WORKED_EXAMPLE


def test_render_text_without_delta_omits_source_section():
    report = compare_readiness(OLD, NEW)
    assert "Source file drift" not in render_text(report, None)


def test_render_text_with_delta_manifest():
    report = compare_readiness(OLD, OLD)
    delta = {
        "added": ["docs/new.html"],
        "modified": [],
        "removed": ["docs/old.html"],
    }
    output = render_text(report, delta)
    expected_tail = """\
Source file drift:
  Added files (1):
    docs/new.html
  Removed files (1):
    docs/old.html"""
    assert output.endswith(expected_tail)
    assert output.startswith("Context drift report\n====================\n"
                             "Summary: no drift | avg score 7.33 -> 7.33")


def test_render_text_negative_score_delta():
    report = compare_readiness(
        _readiness([("docs_chunk_01", 8.5, "A")]),
        _readiness([("docs_chunk_01", 7.0, "B")]),
    )
    output = render_text(report, None)
    assert "  docs_chunk_01  grade A -> B  score 8.50 -> 7.00 (-1.50)" in output


# ---------------------------------------------------------------------------
# CLI: dograpper drift
# ---------------------------------------------------------------------------

def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)


def test_drift_cli_happy_path_markdown():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_json("old.json", OLD)
        _write_json("new.json", NEW)
        result = runner.invoke(cli, ["drift", "--new", "new.json", "--old", "old.json"])
        assert result.exit_code == 0, result.output
        assert result.output.startswith("<!-- dograpper-drift -->\n")
        assert "1 added, 1 modified, 1 removed" in result.output
        assert "grade B → A" in result.output


def test_drift_cli_text_format():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_json("old.json", OLD)
        _write_json("new.json", NEW)
        result = runner.invoke(cli, ["drift", "--new", "new.json",
                                     "--old", "old.json", "--format", "text"])
        assert result.exit_code == 0, result.output
        assert result.output.startswith("Context drift report\n")
        assert "grade B -> A" in result.output


def test_drift_cli_first_run_without_old():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_json("new.json", NEW)
        result = runner.invoke(cli, ["drift", "--new", "new.json"])
        assert result.exit_code == 0, result.output
        assert "First run" in result.output
        assert "3 added, 0 modified, 0 removed" in result.output


def test_drift_cli_new_file_missing_errors():
    runner = CliRunner()
    with runner.isolated_filesystem():
        result = runner.invoke(cli, ["drift", "--new", "absent.json"])
        assert result.exit_code == 1
        assert "absent.json" in result.output


def test_drift_cli_new_file_unparseable_errors():
    runner = CliRunner()
    with runner.isolated_filesystem():
        with open("broken.json", "w", encoding="utf-8") as f:
            f.write("{not json")
        result = runner.invoke(cli, ["drift", "--new", "broken.json"])
        assert result.exit_code == 1
        assert "broken.json" in result.output


def test_drift_cli_old_given_but_missing_errors():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_json("new.json", NEW)
        result = runner.invoke(cli, ["drift", "--new", "new.json",
                                     "--old", "absent.json"])
        assert result.exit_code == 1
        assert "absent.json" in result.output


def test_drift_cli_delta_manifest_missing_is_tolerated():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_json("old.json", OLD)
        _write_json("new.json", NEW)
        result = runner.invoke(cli, ["drift", "--new", "new.json", "--old", "old.json",
                                     "--delta-manifest", "absent.json"])
        assert result.exit_code == 0, result.output
        # Missing manifest degrades to "no delta": the section is omitted.
        assert "Source file drift" not in result.output


def test_drift_cli_delta_manifest_present_lists_files():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_json("old.json", OLD)
        _write_json("new.json", NEW)
        _write_json("delta.json", {"added": ["docs/new.html"],
                                   "modified": [], "removed": []})
        result = runner.invoke(cli, ["drift", "--new", "new.json", "--old", "old.json",
                                     "--delta-manifest", "delta.json"])
        assert result.exit_code == 0, result.output
        assert "docs/new.html" in result.output


def test_drift_cli_fail_on_drift_exits_1_when_drift():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_json("old.json", OLD)
        _write_json("new.json", NEW)
        result = runner.invoke(cli, ["drift", "--new", "new.json",
                                     "--old", "old.json", "--fail-on-drift"])
        assert result.exit_code == 1
        # The report is still written before failing
        assert "<!-- dograpper-drift -->" in result.output


def test_drift_cli_fail_on_drift_exits_0_when_no_drift():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_json("old.json", OLD)
        _write_json("new.json", OLD)
        result = runner.invoke(cli, ["drift", "--new", "new.json",
                                     "--old", "old.json", "--fail-on-drift"])
        assert result.exit_code == 0, result.output


def test_drift_cli_fail_on_drift_first_run_counts_as_drift():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_json("new.json", NEW)
        result = runner.invoke(cli, ["drift", "--new", "new.json", "--fail-on-drift"])
        assert result.exit_code == 1


def test_drift_cli_output_writes_file_only():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_json("old.json", OLD)
        _write_json("new.json", NEW)
        result = runner.invoke(cli, ["drift", "--new", "new.json", "--old", "old.json",
                                     "--output", "report.md"])
        assert result.exit_code == 0, result.output
        assert result.output == ""
        assert os.path.exists("report.md")
        with open("report.md", encoding="utf-8") as f:
            content = f.read()
        assert content.startswith("<!-- dograpper-drift -->\n")


def test_drift_is_in_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "drift" in result.output


# ---------------------------------------------------------------------------
# CLI: malformed inputs must error loudly (exit 1), never traceback
# ---------------------------------------------------------------------------

def _invoke_with_new(payload):
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_json("new.json", payload)
        return runner.invoke(cli, ["drift", "--new", "new.json"])


def test_drift_cli_chunk_entry_missing_chunk_id_errors():
    result = _invoke_with_new({"chunks": [{"score": 8.0, "grade": "A"}]})
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "Traceback" not in result.output


def test_drift_cli_chunk_entry_missing_score_errors():
    result = _invoke_with_new({"chunks": [{"chunk_id": "docs_chunk_01", "grade": "A"}]})
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "Traceback" not in result.output


def test_drift_cli_chunk_entry_missing_grade_errors():
    result = _invoke_with_new({"chunks": [{"chunk_id": "docs_chunk_01", "score": 8.0}]})
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "Traceback" not in result.output


def test_drift_cli_chunk_entry_non_numeric_score_errors():
    result = _invoke_with_new(
        {"chunks": [{"chunk_id": "docs_chunk_01", "score": "high", "grade": "A"}]})
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "Traceback" not in result.output


def test_drift_cli_chunk_entry_not_a_dict_errors():
    result = _invoke_with_new({"chunks": ["docs_chunk_01"]})
    assert result.exit_code == 1
    assert "Error:" in result.output
    assert "Traceback" not in result.output


def test_drift_cli_malformed_old_snapshot_errors():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_json("new.json", NEW)
        _write_json("old.json", {"chunks": [{"chunk_id": "x"}]})
        result = runner.invoke(cli, ["drift", "--new", "new.json", "--old", "old.json"])
        assert result.exit_code == 1
        assert "old.json" in result.output
        assert "Traceback" not in result.output


def test_drift_cli_delta_manifest_not_a_dict_errors():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_json("new.json", NEW)
        _write_json("delta.json", ["docs/new.html"])
        result = runner.invoke(cli, ["drift", "--new", "new.json",
                                     "--delta-manifest", "delta.json"])
        assert result.exit_code == 1
        assert "delta.json" in result.output
        assert "Traceback" not in result.output
