import os
import tempfile

from click.testing import CliRunner

from dograpper.lib.chunker import Chunk, ChunkFile, balance_chunks, generate_import_guide
from dograpper.commands.pack import pack


class TestBalanceChunks:
    """Tests for chunk redistribution used by --bundle."""

    def test_respects_target_chunks(self):
        """Never generates more than target_chunks."""
        files = [ChunkFile(f"file_{i}.html", 1000) for i in range(100)]
        chunks = [Chunk(index=1, files=files, total_words=100000)]
        result = balance_chunks(chunks, target_chunks=10, max_words=500000)
        assert len(result) <= 10

    def test_balances_words_evenly(self):
        """Chunks should have similar sizes (deviation < 30% of average)."""
        files = [ChunkFile(f"file_{i}.html", 500 + i * 10) for i in range(50)]
        total = sum(f.word_count for f in files)
        chunks = [Chunk(index=1, files=files, total_words=total)]
        result = balance_chunks(chunks, target_chunks=5, max_words=500000)
        words = [c.total_words for c in result]
        avg = sum(words) / len(words)
        for w in words:
            assert abs(w - avg) / avg < 0.30, f"Chunk with {w} words, avg {avg}"

    def test_oversized_file_alone(self):
        """A file that alone exceeds target_words gets its own chunk."""
        files = [
            ChunkFile("small.html", 100),
            ChunkFile("huge.html", 50000),
            ChunkFile("small2.html", 100),
        ]
        chunks = [Chunk(index=1, files=files, total_words=50200)]
        result = balance_chunks(chunks, target_chunks=3, max_words=500000)
        huge_chunk = [c for c in result if any(f.relative_path == "huge.html" for f in c.files)]
        assert len(huge_chunk) == 1
        assert len(huge_chunk[0].files) == 1

    def test_fewer_files_than_target(self):
        """Fewer files than target_chunks -> each file is a chunk."""
        files = [ChunkFile(f"f{i}.html", 1000) for i in range(3)]
        chunks = [Chunk(index=1, files=files, total_words=3000)]
        result = balance_chunks(chunks, target_chunks=50, max_words=500000)
        assert len(result) == 3

    def test_reindex_sequential(self):
        """Chunks re-indexed from 1 to N."""
        files = [ChunkFile(f"f{i}.html", 1000) for i in range(10)]
        chunks = [Chunk(index=1, files=files, total_words=10000)]
        result = balance_chunks(chunks, target_chunks=3, max_words=500000)
        for i, c in enumerate(result):
            assert c.index == i + 1

    def test_max_words_respected(self):
        """No chunk exceeds max_words (except single-file chunks)."""
        files = [ChunkFile(f"f{i}.html", 3000) for i in range(20)]
        chunks = [Chunk(index=1, files=files, total_words=60000)]
        result = balance_chunks(chunks, target_chunks=50, max_words=5000)
        for c in result:
            if len(c.files) > 1:
                assert c.total_words <= 5000

    def test_empty_input(self):
        """Empty chunks list returns empty."""
        result = balance_chunks([], target_chunks=10, max_words=500000)
        assert result == []

    def test_preserves_file_order(self):
        """Files stay in their original order after balancing."""
        files = [ChunkFile(f"f{i}.html", 1000) for i in range(10)]
        chunks = [Chunk(index=1, files=files, total_words=10000)]
        result = balance_chunks(chunks, target_chunks=3, max_words=500000)
        flat_result = [cf.relative_path for c in result for cf in c.files]
        assert flat_result == [f"f{i}.html" for i in range(10)]

    def test_multiple_input_chunks_flattened(self):
        """Files from multiple input chunks are merged and redistributed."""
        c1 = Chunk(index=1, files=[ChunkFile("a.html", 2000)], total_words=2000)
        c2 = Chunk(index=2, files=[ChunkFile("b.html", 2000)], total_words=2000)
        c3 = Chunk(index=3, files=[ChunkFile("c.html", 2000)], total_words=2000)
        result = balance_chunks([c1, c2, c3], target_chunks=2, max_words=500000)
        assert len(result) <= 2
        total_files = sum(len(c.files) for c in result)
        assert total_files == 3


class TestGenerateImportGuide:
    """Tests for IMPORT_GUIDE.md generation."""

    def test_guide_created(self, tmp_path):
        """File is created in output_dir."""
        chunks = [
            Chunk(index=1, files=[ChunkFile("api.html", 5000)], total_words=5000),
            Chunk(index=2, files=[ChunkFile("guide.html", 3000)], total_words=3000),
        ]
        path = generate_import_guide(chunks, str(tmp_path), "notebooklm", 8000)
        assert os.path.exists(path)
        assert path.endswith("IMPORT_GUIDE.md")

    def test_guide_contains_all_chunks(self, tmp_path):
        """Guide lists all chunks."""
        chunks = [
            Chunk(index=i, files=[ChunkFile(f"f{i}.html", 1000)], total_words=1000)
            for i in range(1, 6)
        ]
        path = generate_import_guide(chunks, str(tmp_path), "notebooklm", 5000)
        content = open(path).read()
        for i in range(1, 6):
            assert f"docs_chunk_{i:02d}.md" in content

    def test_guide_shows_word_counts(self, tmp_path):
        """Guide shows word counts."""
        chunks = [Chunk(index=1, files=[ChunkFile("a.html", 4820)], total_words=4820)]
        path = generate_import_guide(chunks, str(tmp_path), "notebooklm", 4820)
        content = open(path).read()
        assert "4,820" in content or "4820" in content

    def test_notebooklm_has_audio_tips(self, tmp_path):
        """NotebookLM preset includes Audio Overview tips."""
        chunks = [Chunk(index=1, files=[ChunkFile("a.html", 1000)], total_words=1000)]
        path = generate_import_guide(chunks, str(tmp_path), "notebooklm", 1000)
        content = open(path).read()
        assert "Audio Overview" in content

    def test_rag_standard_no_audio_tips(self, tmp_path):
        """rag-standard preset does not include Audio Overview tips."""
        chunks = [Chunk(index=1, files=[ChunkFile("a.html", 1000)], total_words=1000)]
        path = generate_import_guide(chunks, str(tmp_path), "rag-standard", 1000)
        content = open(path).read()
        assert "Audio Overview" not in content

    def test_guide_uses_heading_map(self, tmp_path):
        """Guide derives section from heading_map when available."""
        from dograpper.utils.heading_extractor import Heading
        chunks = [Chunk(index=1, files=[ChunkFile("api.html", 1000)], total_words=1000)]
        hmap = {"api.html": [Heading(level=1, text="API Reference", char_offset=0)]}
        path = generate_import_guide(chunks, str(tmp_path), "notebooklm", 1000, heading_map=hmap)
        content = open(path).read()
        assert "API Reference" in content

    def test_guide_uses_directory_fallback(self, tmp_path):
        """Guide falls back to directory name when no heading_map."""
        chunks = [Chunk(index=1, files=[ChunkFile("docs/api/index.html", 1000)], total_words=1000)]
        path = generate_import_guide(chunks, str(tmp_path), "notebooklm", 1000)
        content = open(path).read()
        assert "api" in content


class TestBundleCLI:
    """Integration tests for --bundle via CLI."""

    def _make_test_dir(self, tmpdir, files_dict):
        for rel, content in files_dict.items():
            fpath = os.path.join(tmpdir, rel)
            os.makedirs(os.path.dirname(fpath), exist_ok=True)
            with open(fpath, 'w', encoding='utf-8') as f:
                f.write(content)

    def test_bundle_notebooklm_creates_guide(self):
        """--bundle notebooklm generates IMPORT_GUIDE.md."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = os.path.join(tmpdir, "docs")
            output_dir = os.path.join(tmpdir, "chunks")
            self._make_test_dir(input_dir, {
                "a.txt": " ".join(["word"] * 500),
                "b.txt": " ".join(["text"] * 500),
            })
            result = runner.invoke(pack, [
                input_dir, '-o', output_dir, '--bundle', 'notebooklm',
            ], catch_exceptions=False)
            assert result.exit_code == 0
            assert os.path.exists(os.path.join(output_dir, "IMPORT_GUIDE.md"))
            assert "Import guide:" in result.output

    def test_bundle_notebooklm_max_50_chunks(self):
        """--bundle notebooklm enforces ≤50 chunks via balancing."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = os.path.join(tmpdir, "docs")
            output_dir = os.path.join(tmpdir, "chunks")
            # Create 100 small files; at --max-words-per-chunk=100 this produces
            # 100 chunks normally. Bundle balances them into ≤50 using a higher
            # effective max_words (500000 for notebooklm).
            files = {}
            for i in range(100):
                files[f"file_{i:03d}.txt"] = " ".join(["word"] * 100)
            self._make_test_dir(input_dir, files)
            result = runner.invoke(pack, [
                input_dir, '-o', output_dir,
                '--max-words-per-chunk', '500000',
                '--max-chunks', '100',
                '--bundle', 'notebooklm',
            ], catch_exceptions=False)
            assert result.exit_code == 0
            import glob
            chunk_files = glob.glob(os.path.join(output_dir, "docs_chunk_*.md"))
            assert len(chunk_files) <= 50

    def test_without_bundle_no_guide(self):
        """Without --bundle, no IMPORT_GUIDE.md is generated."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = os.path.join(tmpdir, "docs")
            output_dir = os.path.join(tmpdir, "chunks")
            self._make_test_dir(input_dir, {"a.txt": "hello world"})
            result = runner.invoke(pack, [
                input_dir, '-o', output_dir,
            ], catch_exceptions=False)
            assert result.exit_code == 0
            assert not os.path.exists(os.path.join(output_dir, "IMPORT_GUIDE.md"))

    def test_bundle_rag_standard_creates_guide(self):
        """--bundle rag-standard generates guide without audio tips."""
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_dir = os.path.join(tmpdir, "docs")
            output_dir = os.path.join(tmpdir, "chunks")
            self._make_test_dir(input_dir, {"a.txt": " ".join(["word"] * 100)})
            result = runner.invoke(pack, [
                input_dir, '-o', output_dir, '--bundle', 'rag-standard',
            ], catch_exceptions=False)
            assert result.exit_code == 0
            guide_path = os.path.join(output_dir, "IMPORT_GUIDE.md")
            assert os.path.exists(guide_path)
            content = open(guide_path).read()
            assert "Audio Overview" not in content


class TestImportGuideNames:
    """IMPORT_GUIDE.md lists the files the run wrote (#143)."""

    @staticmethod
    def _pack(tmp_path, *extra):
        src = tmp_path / "in"
        src.mkdir()
        (src / "a.md").write_text("alpha " * 20)
        out = tmp_path / "out"
        result = CliRunner().invoke(pack, [str(src), "-o", str(out), "--bundle", "notebooklm", *extra])
        assert result.exit_code == 0, result.output
        return out

    def test_default_run_keeps_the_default_names(self, tmp_path):
        out = self._pack(tmp_path)
        assert "| 1 | docs_chunk_01.md |" in (out / "IMPORT_GUIDE.md").read_text()

    def test_custom_prefix_and_format(self, tmp_path):
        for fmt in ("jsonl", "txt"):
            sub = tmp_path / fmt
            sub.mkdir()
            out = self._pack(sub, "--format", fmt, "--prefix", "foo_")
            guide = (out / "IMPORT_GUIDE.md").read_text()
            written = sorted(p.name for p in out.glob(f"foo_*.{fmt}"))
            assert written == [f"foo_01.{fmt}"]
            assert f"| 1 | foo_01.{fmt} |" in guide
            assert "docs_chunk_" not in guide

    def test_rag_standard_guide_uses_run_names(self, tmp_path):
        chunks = [Chunk(index=1, files=[ChunkFile("a.html", 10)], total_words=10)]
        path = generate_import_guide(chunks, str(tmp_path), "rag-standard", 10, prefix="p_", fmt="jsonl")
        assert "| 1 | p_01.jsonl |" in open(path).read()
