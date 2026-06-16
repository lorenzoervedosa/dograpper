import os
import tempfile
import pytest
from click.testing import CliRunner

from dograpper.utils.word_counter import count_words, count_words_file
from dograpper.lib.ignore_parser import filter_files
from dograpper.lib.chunker import chunk_by_size, chunk_by_semantic, write_chunks, Chunk, ChunkFile
from dograpper.commands.pack import pack

# --- Word Counter ---

def test_count_words_basic():
    assert count_words("hello world foo") == 3

def test_count_words_empty():
    assert count_words("") == 0

def test_count_words_file():
    with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
        f.write("one two three four")
        filepath = f.name
    try:
        assert count_words_file(filepath) == 4
    finally:
        os.remove(filepath)

def test_count_words_file_html():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.html', delete=False) as f:
        f.write("<p>this is <b>four</b> words</p><script>console.log('not me');</script>")
        filepath = f.name
    try:
        assert count_words_file(filepath) == 4
    finally:
        os.remove(filepath)

def test_count_words_file_md():
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("# this is four words\n<p>one two</p>")
        filepath = f.name
    try:
        # Markdown keeps everything
        assert count_words_file(filepath) == 7
    finally:
        os.remove(filepath)

# --- HTML Stripper ---

from dograpper.utils.html_stripper import strip_html

def test_strip_html_basic():
    assert strip_html("<p>Hello <b>world</b></p>") == "Hello world"

def test_strip_html_script_style():
    test_input = "<script>var x=1;</script><style>.a{}</style><p>Text</p>"
    assert strip_html(test_input) == "Text"

def test_strip_html_entities():
    assert strip_html("&amp; &lt;b&gt;") == "& <b>"

# --- Ignore Parser ---

def test_ignore_parser_docsignore():
    with tempfile.TemporaryDirectory() as temp_dir:
        ignore_path = os.path.join(temp_dir, '.docsignore')
        with open(ignore_path, 'w') as f:
            f.write("*.png\n")
            
        files = [
            os.path.join(temp_dir, 'image.png'),
            os.path.join(temp_dir, 'doc.md')
        ]
        
        filtered = filter_files(files, ignore_path, [], temp_dir)
        assert len(filtered) == 1
        assert filtered[0].endswith("doc.md")

def test_ignore_parser_inline_patterns():
    with tempfile.TemporaryDirectory() as temp_dir:
        files = [
            os.path.join(temp_dir, 'temp', 'cache.log'),
            os.path.join(temp_dir, 'src', 'main.py')
        ]
        
        filtered = filter_files(files, None, ["*.log", "**/temp/**"], temp_dir)
        assert len(filtered) == 1
        assert filtered[0].endswith("main.py")

def test_ignore_parser_no_file():
    with tempfile.TemporaryDirectory() as temp_dir:
        files = [os.path.join(temp_dir, 'a.txt')]
        filtered = filter_files(files, os.path.join(temp_dir, '.nope'), ["*.log"], temp_dir)
        assert len(filtered) == 1


# --- Binary file skipping (issue: pack read images/binaries as text) ---

def test_is_binary_path():
    from dograpper.lib.ignore_parser import is_binary_path
    assert is_binary_path("a/b/image.PNG") is True
    assert is_binary_path("fonts/icons.woff2") is True
    assert is_binary_path("doc/page.html") is False
    assert is_binary_path("notes.md") is False
    assert is_binary_path("README") is False  # extensionless pretty URL


def test_filter_files_skips_binary_by_default():
    with tempfile.TemporaryDirectory() as temp_dir:
        files = [
            os.path.join(temp_dir, 'image.png'),
            os.path.join(temp_dir, 'photo.JPG'),
            os.path.join(temp_dir, 'anim.gif'),
            os.path.join(temp_dir, 'page.html'),
            os.path.join(temp_dir, 'notes.md'),
        ]
        filtered = filter_files(files, None, [], temp_dir)
        rels = sorted(os.path.basename(p) for p in filtered)
        assert rels == ['notes.md', 'page.html']


def test_filter_files_skip_binary_can_be_disabled():
    with tempfile.TemporaryDirectory() as temp_dir:
        files = [
            os.path.join(temp_dir, 'image.png'),
            os.path.join(temp_dir, 'page.html'),
        ]
        filtered = filter_files(files, None, [], temp_dir, skip_binary=False)
        assert len(filtered) == 2


def test_filter_files_binary_skip_composes_with_patterns():
    with tempfile.TemporaryDirectory() as temp_dir:
        files = [
            os.path.join(temp_dir, 'image.png'),   # dropped: binary
            os.path.join(temp_dir, '404.html'),    # dropped: pattern
            os.path.join(temp_dir, 'page.html'),   # kept
        ]
        filtered = filter_files(files, None, ['404.html'], temp_dir)
        assert [os.path.basename(p) for p in filtered] == ['page.html']


def test_pack_cli_excludes_binary_files():
    """Regression: a PNG in the input dir must not be read as text and
    counted as thousands of words."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as d:
        with open(os.path.join(d, 'page.html'), 'w') as f:
            f.write('<html><body><p>' + 'word ' * 50 + '</p></body></html>')
        # A binary blob that, read as text, would yield a huge bogus word count.
        with open(os.path.join(d, 'image.png'), 'wb') as f:
            f.write(b'\x89PNG\r\n\x1a\n' + b'\xff\x00 \x10' * 5000)

        out = os.path.join(d, 'out')
        result = runner.invoke(pack, [d, '-o', out])

        assert result.exit_code == 0, result.output
        assert "Files excluded:  1" in result.output
        # The png bytes must not leak into any chunk.
        chunk_blob = ""
        for fn in os.listdir(out):
            with open(os.path.join(out, fn), 'r', encoding='utf-8', errors='replace') as cf:
                chunk_blob += cf.read()
        assert "PNG" not in chunk_blob


# --- Chunker Engine ---

def create_mock_files(base_dir, file_specs):
    paths = []
    for rel_path, word_count in file_specs:
        full = os.path.join(base_dir, rel_path)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        with open(full, 'w') as f:
            f.write("Word " * word_count)
        paths.append(full)
    return paths

def test_chunk_by_size_basic():
    with tempfile.TemporaryDirectory() as d:
        files = create_mock_files(d, [("a.md", 100), ("b.md", 100), ("c.md", 100)])
        chunks = chunk_by_size(files, d, 250)
        assert len(chunks) == 2
        assert len(chunks[0].files) == 2  # a, b = 200
        assert len(chunks[1].files) == 1  # c = 100

def test_chunk_by_size_oversized_file():
    with tempfile.TemporaryDirectory() as d:
        files = create_mock_files(d, [("a.md", 1000)])
        chunks = chunk_by_size(files, d, 500)
        assert len(chunks) == 1
        assert chunks[0].total_words == 1000

def test_chunk_by_semantic_grouping():
    with tempfile.TemporaryDirectory() as d:
        files = create_mock_files(d, [
            ("mod_a/f1.md", 100),
            ("mod_a/f2.md", 100),
            ("mod_b/f1.md", 100)
        ])
        chunks = chunk_by_semantic(files, d, 250)
        assert len(chunks) == 2
        # mod_a has 200 words, fits in one chunk. mod_b in next.
        assert len(chunks[0].files) == 2
        assert "mod_a" in chunks[0].files[0].relative_path
        
# --- Write Chunks ---

def test_write_chunks_with_index():
    with tempfile.TemporaryDirectory() as d:
        out_dir = os.path.join(d, 'out')
        files = create_mock_files(d, [("a.md", 5)])
        chunks = chunk_by_size(files, d, 10)
        
        write_chunks(chunks, d, out_dir, "ck_", "md", True, 1)
        
        with open(os.path.join(out_dir, "ck_01.md"), 'r') as f:
            content = f.read()
            assert "# Chunk 01" in content
            assert "Files in this chunk" in content
            assert "<!-- SOURCE: a.md -->" in content

def test_write_chunks_without_index():
     with tempfile.TemporaryDirectory() as d:
        out_dir = os.path.join(d, 'out')
        files = create_mock_files(d, [("a.md", 5)])
        chunks = chunk_by_size(files, d, 10)
        
        write_chunks(chunks, d, out_dir, "ck_", "md", False, 1)
        
        with open(os.path.join(out_dir, "ck_01.md"), 'r') as f:
            content = f.read()
            assert "# Chunk" not in content
            assert "<!-- SOURCE: a.md -->" in content

def test_write_chunks_strips_html():
    with tempfile.TemporaryDirectory() as d:
        out_dir = os.path.join(d, 'out')
        files = create_mock_files(d, [("a.html", 5)])
        
        # Override file content to be real HTML
        with open(os.path.join(d, "a.html"), 'w') as f:
            f.write("<p>word anword</p>")
            
        chunks = chunk_by_size(files, d, 10)
        write_chunks(chunks, d, out_dir, "ck_", "md", False, 1)
        
        with open(os.path.join(out_dir, "ck_01.md"), 'r') as f:
            content = f.read()
            assert "<!-- SOURCE: a.html -->" in content
            assert "word anword" in content
            assert "<p>" not in content

def test_xml_format_deprecated():
    """--format xml raises deprecation error."""
    with tempfile.TemporaryDirectory() as d:
        out_dir = os.path.join(d, 'out')
        files = create_mock_files(d, [("a.md", 5)])
        chunks = chunk_by_size(files, d, 20)
        with pytest.raises(ValueError, match="deprecated"):
            write_chunks(chunks, d, out_dir, "ck_", "xml", True, 1)

# --- CLI Integration ---

def test_pack_empty_dir():
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as d:
        result = runner.invoke(pack, [d, '-o', os.path.join(d, 'out')])
        assert result.exit_code != 0
        assert "No files found" in result.output

def test_pack_all_excluded():
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as d:
        # Create one file but exclude it immediately
        with open(os.path.join(d, "file.txt"), "w") as f:
            f.write("stuff")
            
        result = runner.invoke(pack, [d, '-o', os.path.join(d, 'out'), '--ignore', '*.txt'])
        assert result.exit_code != 0
        assert "All files were excluded" in result.output

def test_chunk_by_semantic_oversized_group():
    with tempfile.TemporaryDirectory() as d:
        files = create_mock_files(d, [
            ("mod_val/f1.md", 200),
            ("mod_val/f2.md", 200)
        ])
        # Max words 250 means mod_val total (400) > 250, so it subdivides
        chunks = chunk_by_semantic(files, d, 250)
        assert len(chunks) == 2
        assert len(chunks[0].files) == 1
        assert chunks[0].files[0].word_count == 200
        assert chunks[1].files[0].word_count == 200

def test_chunk_by_size_single_file_exceeds(caplog):
    with tempfile.TemporaryDirectory() as d:
        files = create_mock_files(d, [("massive.md", 1000)])
        chunks = chunk_by_size(files, d, 50)
        assert len(chunks) == 1
        # The caplog will capture the logger.warning emitted from chunk_by_size
        assert "exceeding max-words-per-chunk limit" in caplog.text

def test_pack_max_chunks_warning():
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as d:
        files = create_mock_files(d, [
            ("a.md", 100),
            ("b.md", 100)
        ])
        result = runner.invoke(pack, [d, '-o', os.path.join(d, 'out'), '--max-words-per-chunk', '50', '--max-chunks', '1'])
        assert result.exit_code == 0
        assert "Chunk count exceeds max-chunks limit" in result.output

def test_pack_integration_full():
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as d:
        # Create input dir
        input_dir = os.path.join(d, 'input')
        os.makedirs(input_dir)
        create_mock_files(input_dir, [
            ("module/one.md", 50),
            ("module/two.md", 50)
        ])
        
        output_dir = os.path.join(d, 'out')
        
        # Test full command
        result = runner.invoke(pack, [input_dir, '-o', output_dir, '--strategy', 'semantic'])
        assert result.exit_code == 0
        
        # Verify output exists
        outfile = os.path.join(output_dir, 'docs_chunk_01.md')
        assert os.path.exists(outfile)
        
        with open(outfile, 'r') as f:
            content = f.read()
            assert "# Chunk 01" in content
            assert "module/one.md" in content
            assert "module/two.md" in content

def test_config_invalid_json():
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as d:
        config_path = os.path.join(d, '.dograpper.json')
        with open(config_path, 'w') as f:
            f.write('{"pack": {"format": "xml"') # Missing closing brace
            
        # Point the config file logic to the temp directory. 
        # But wait, pack CLI defaults to checking ~/.dograpper.json and ./.dograpper.json if no config flag is implemented.
        # Actually in load_config it is a direct method, we can just test `load_config` directly.
        from dograpper.lib.config_loader import load_config
        import click
        from pytest import raises
        
        ctx = click.Context(click.Command('pack'))
        with raises(click.ClickException) as exc:
            load_config(config_path, "pack", {}, ctx)
            
        assert "line" in str(exc.value)
        assert "column" in str(exc.value)
