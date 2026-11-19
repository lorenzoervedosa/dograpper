import pytest
import os
import json
import tempfile
from dograpper.lib.chunker import (
    Chunk, ChunkFile, chunk_by_size, write_chunks
)


def create_mock_files(base_dir, specs):
    """Cria arquivos de teste. specs = [(name, word_count), ...]"""
    paths = []
    for name, wc in specs:
        path = os.path.join(base_dir, name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            f.write(" ".join(["word"] * wc))
        paths.append(path)
    return paths


class TestJsonlFormat:

    def test_jsonl_creates_file(self):
        """Arquivo .jsonl é criado."""
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out")
            files = create_mock_files(d, [("a.txt", 10)])
            chunks = chunk_by_size(files, d, 100)
            write_chunks(chunks, d, out, "ck_", "jsonl", True, 1)
            assert os.path.exists(os.path.join(out, "ck_01.jsonl"))

    def test_jsonl_valid_json_per_line(self):
        """Cada linha é JSON válido."""
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out")
            files = create_mock_files(d, [("a.txt", 10), ("b.txt", 15)])
            chunks = chunk_by_size(files, d, 100)
            write_chunks(chunks, d, out, "ck_", "jsonl", True, 1)
            with open(os.path.join(out, "ck_01.jsonl")) as f:
                lines = [l for l in f.readlines() if l.strip()]
            assert len(lines) == 2
            for line in lines:
                data = json.loads(line)
                assert "id" in data
                assert "source" in data
                assert "words" in data
                assert "content" in data
                assert data["schema_version"] == "v1"

    def test_jsonl_word_count_accurate(self):
        """Campo words reflete contagem real."""
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out")
            files = create_mock_files(d, [("a.txt", 42)])
            chunks = chunk_by_size(files, d, 100)
            write_chunks(chunks, d, out, "ck_", "jsonl", True, 1)
            with open(os.path.join(out, "ck_01.jsonl")) as f:
                data = json.loads(f.readline())
            assert data["words"] == 42

    def test_jsonl_content_no_newlines(self):
        """Conteúdo JSON escapa newlines (válido em uma linha)."""
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out")
            path = os.path.join(d, "multi.txt")
            with open(path, 'w') as f:
                f.write("line one\n\nline two\n\nline three")
            chunks = chunk_by_size([path], d, 100)
            write_chunks(chunks, d, out, "ck_", "jsonl", True, 1)
            with open(os.path.join(out, "ck_01.jsonl")) as f:
                raw_line = f.readline()
            # Deve ser uma única linha válida
            assert "\n" not in raw_line.rstrip("\n")
            data = json.loads(raw_line)
            # Mas o content desserializado preserva newlines
            assert "\n" in data["content"]

    def test_jsonl_multiple_chunks(self):
        """Múltiplos chunks geram múltiplos arquivos .jsonl."""
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out")
            files = create_mock_files(d, [("a.txt", 50), ("b.txt", 50)])
            chunks = chunk_by_size(files, d, 60)
            write_chunks(chunks, d, out, "ck_", "jsonl", True, len(chunks))
            assert os.path.exists(os.path.join(out, "ck_01.jsonl"))
            assert os.path.exists(os.path.join(out, "ck_02.jsonl"))

    def test_jsonl_with_heading_map(self):
        """Com heading_map, breadcrumb aparece no JSON."""
        from dograpper.utils.heading_extractor import Heading
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out")
            path = os.path.join(d, "page.html")
            with open(path, 'w') as f:
                f.write("<h1>Title</h1><p>" + " ".join(["w"] * 20) + "</p>")
            chunks = chunk_by_size([path], d, 100)
            heading_map = {"page.html": [Heading(1, "Title", 0)]}
            write_chunks(chunks, d, out, "ck_", "jsonl", True, 1,
                         heading_map=heading_map)
            with open(os.path.join(out, "ck_01.jsonl")) as f:
                data = json.loads(f.readline())
            assert data["breadcrumb"] == ["Title"]

    def test_jsonl_api_records_replace_the_page_record(self):
        """With api_records, a page is written as its records, never read from disk (ADR-0009)."""
        from dograpper.utils.api_reference import ApiRecord
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "out")
            files = create_mock_files(d, [("api/Box.html", 3), ("guide.txt", 4)])
            os.remove(files[0])  # the writer must not read a split page
            chunk = Chunk(index=1, files=[ChunkFile("api/Box.html", 9), ChunkFile("guide.txt", 4)],
                          total_words=13)
            records = [
                ApiRecord(text="p.Box (class)\npublic class Box", symbol="p.Box", kind="container",
                          symbol_kind="class", breadcrumb=["p.Box"], generator="javadoc"),
                ApiRecord(text="p.Box#Box(int)\npublic Box(int n)", symbol="p.Box#Box(int)",
                          kind="member", symbol_kind="constructor", breadcrumb=["p.Box", "Box(int)"],
                          generator="javadoc", anchor="<init>(int)", container="p.Box"),
            ]
            write_chunks([chunk], d, out, "ck_", "jsonl", True, 1,
                         url_map={"api/Box.html": "https://x.test/api/Box.html"},
                         readiness_map={"ck_01": {"grade": "B"}},
                         annotate=lambda rel, text: text + " [-> ck_01]",
                         api_records={"api/Box.html": records})
            with open(os.path.join(out, "ck_01.jsonl")) as f:
                lines = [json.loads(l) for l in f if l.strip()]
            assert lines[0] == {
                "id": "01_api/Box.html", "source": "api/Box.html", "words": 5,
                "content": "p.Box (class)\npublic class Box [-> ck_01]", "schema_version": "v1",
                "breadcrumb": ["p.Box"], "url": "https://x.test/api/Box.html",
                "readiness_grade": "B", "symbol": "p.Box", "kind": "container",
                "symbol_kind": "class", "generator": "javadoc",
            }
            assert lines[1]["id"] == "01_api/Box.html#<init>(int)"
            assert lines[1]["url"] == "https://x.test/api/Box.html#%3Cinit%3E(int)"
            assert (lines[1]["kind"], lines[1]["container"]) == ("member", "p.Box")
            assert lines[1]["breadcrumb"] == ["p.Box", "Box(int)"]
            assert lines[2]["id"] == "01_guide.txt" and "symbol" not in lines[2]


class TestJsonlCLI:

    def test_cli_jsonl_format(self):
        """CLI --format jsonl gera arquivos .jsonl."""
        from click.testing import CliRunner
        from dograpper.commands.pack import pack

        runner = CliRunner()
        with tempfile.TemporaryDirectory() as d:
            input_dir = os.path.join(d, "input")
            os.makedirs(input_dir)
            with open(os.path.join(input_dir, "a.txt"), 'w') as f:
                f.write(" ".join(["word"] * 100))
            output_dir = os.path.join(d, "output")
            result = runner.invoke(pack, [
                input_dir, "-o", output_dir, "--format", "jsonl",
            ], catch_exceptions=False)
            assert result.exit_code == 0
            jsonl_files = [f for f in os.listdir(output_dir) if f.endswith('.jsonl')]
            assert len(jsonl_files) >= 1

    def test_cli_xml_rejected(self):
        """CLI --format xml is not a choice (exit 2)."""
        from click.testing import CliRunner
        from dograpper.commands.pack import pack

        runner = CliRunner()
        with tempfile.TemporaryDirectory() as d:
            input_dir = os.path.join(d, "input")
            os.makedirs(input_dir)
            with open(os.path.join(input_dir, "test.txt"), 'w') as f:
                f.write("hello world")
            result = runner.invoke(pack, [
                input_dir, "-o", os.path.join(d, "output"),
                "--format", "xml",
            ])
            assert result.exit_code == 2
