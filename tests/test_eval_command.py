"""Integration tests for the `dograpper eval` subcommand."""

import json
import os

from click.testing import CliRunner

from dograpper.cli import cli


def _write_pack(dir_path):
    os.makedirs(dir_path, exist_ok=True)
    records = [
        {"id": "01_install", "source": "install.html", "words": 9,
         "content": "Installation guide run pip install to set up the package quickly",
         "breadcrumb": ["Guide", "Installation"], "readiness_grade": "A"},
        {"id": "02_config", "source": "config.html", "words": 8,
         "content": "Configuration options control logging verbosity and output format",
         "breadcrumb": ["Guide", "Configuration"], "readiness_grade": "B"},
    ]
    with open(os.path.join(dir_path, "docs_chunk_01.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps(records[0]) + "\n")
    with open(os.path.join(dir_path, "docs_chunk_02.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps(records[1]) + "\n")


def test_eval_reports_hit_rate():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_pack("chunks")
        result = runner.invoke(cli, ["eval", "chunks", "-k", "5"])
        assert result.exit_code == 0, result.output
        assert "Hit-rate@5" in result.output
        assert "Golden Q&A:" in result.output


def test_eval_writes_json_report():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_pack("chunks")
        result = runner.invoke(cli, ["eval", "chunks", "-o", "report.json"])
        assert result.exit_code == 0, result.output
        with open("report.json", encoding="utf-8") as f:
            payload = json.load(f)
        assert payload["total_questions"] == 2
        assert 0.0 <= payload["hit_rate"] <= 1.0
        assert "per_grade" in payload


def test_eval_errors_without_jsonl():
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("empty", exist_ok=True)
        result = runner.invoke(cli, ["eval", "empty"])
        assert result.exit_code == 1
        assert "no JSONL chunks" in result.output


def test_eval_errors_without_breadcrumbs():
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("chunks", exist_ok=True)
        with open("chunks/docs_chunk_01.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": "01_a", "source": "a", "content": "no headings here",
                                "words": 3}) + "\n")
        result = runner.invoke(cli, ["eval", "chunks"])
        assert result.exit_code == 1
        assert "context-header" in result.output


def test_eval_is_in_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "eval" in result.output
