"""Tests for boundary-aware chunking (structural block integrity)."""

import pytest
from dograpper.lib.chunker import _split_text_by_words, _group_into_blocks
from dograpper.utils.html_stripper import strip_html


class TestGroupIntoBlocks:
    """Testa agrupamento de parágrafos em blocos estruturais."""

    def test_code_block_not_split(self):
        """Bloco ``` com \\n\\n interno vira um único bloco."""
        paragraphs = [
            "Texto antes.",
            "```python\ndef foo():",
            '    return "bar"',
            "```",
            "Texto depois.",
        ]
        blocks = _group_into_blocks(paragraphs)
        # O bloco de código (parágrafos 1-3) deve ser agrupado
        code_block = '```python\ndef foo():\n\n    return "bar"\n\n```'
        assert any(code_block in b for b in blocks)
        assert blocks[0] == "Texto antes."
        assert blocks[-1] == "Texto depois."

    def test_self_closing_code_block(self):
        """``` que abre e fecha no mesmo parágrafo não agrupa com o próximo."""
        paragraphs = [
            "```python\nprint('hi')\n```",
            "Texto normal.",
        ]
        blocks = _group_into_blocks(paragraphs)
        assert len(blocks) == 2

    def test_unclosed_code_block(self):
        """``` sem fechamento agrupa até o fim."""
        paragraphs = ["```python\ndef foo():", "mais código", "fim"]
        blocks = _group_into_blocks(paragraphs)
        assert len(blocks) == 1

    def test_longer_fence_not_closed_by_inner_backticks(self):
        """A four-backtick fence only closes on four or more."""
        paragraphs = ["````md\n```\ncode", "more\n```", "tail\n````", "Texto."]
        blocks = _group_into_blocks(paragraphs)
        assert blocks == ["````md\n```\ncode\n\nmore\n```\n\ntail\n````", "Texto."]

    def test_pre_text_inside_fence_does_not_open_a_pre_block(self):
        """<pre> inside the code does not pull in the paragraphs after it."""
        paragraphs = ["```html\n<pre>\n```", "Texto.", "Mais texto."]
        assert _group_into_blocks(paragraphs) == paragraphs

    def test_list_grouped(self):
        """Itens de lista contíguos viram bloco único."""
        paragraphs = ["- item 1", "- item 2", "- item 3", "Texto normal."]
        blocks = _group_into_blocks(paragraphs)
        assert len(blocks) == 2
        assert "- item 1" in blocks[0]
        assert "- item 3" in blocks[0]

    def test_numbered_list_grouped(self):
        """Lista numerada agrupada."""
        paragraphs = ["1. primeiro", "2. segundo", "Texto."]
        blocks = _group_into_blocks(paragraphs)
        assert len(blocks) == 2

    def test_table_grouped(self):
        """Linhas de tabela markdown agrupadas."""
        paragraphs = [
            "| Col A | Col B |",
            "| --- | --- |",
            "| val1 | val2 |",
            "Texto depois.",
        ]
        blocks = _group_into_blocks(paragraphs)
        assert len(blocks) == 2
        assert blocks[0].count("|") >= 6

    def test_pre_block_grouped(self):
        """<pre> sem </pre> agrupa até encontrar </pre>."""
        paragraphs = ["<pre>código", "mais código", "fim</pre>", "Texto."]
        blocks = _group_into_blocks(paragraphs)
        assert len(blocks) == 2

    def test_regular_paragraphs_unchanged(self):
        """Parágrafos normais permanecem individuais."""
        paragraphs = ["Parágrafo 1.", "Parágrafo 2.", "Parágrafo 3."]
        blocks = _group_into_blocks(paragraphs)
        assert len(blocks) == 3

    def test_mixed_structures(self):
        """Texto com múltiplos tipos de blocos estruturais."""
        paragraphs = [
            "Intro.",
            "- item A",
            "- item B",
            "Middle text.",
            "```\ncode line",
            "more code\n```",
            "End.",
        ]
        blocks = _group_into_blocks(paragraphs)
        assert blocks[0] == "Intro."
        assert "- item A" in blocks[1]
        assert "- item B" in blocks[1]
        assert blocks[2] == "Middle text."
        assert "```" in blocks[3]
        assert blocks[4] == "End."

    def test_asterisk_list_grouped(self):
        """Lista com * como marcador."""
        paragraphs = ["* item 1", "* item 2", "Normal."]
        blocks = _group_into_blocks(paragraphs)
        assert len(blocks) == 2
        assert "* item 1" in blocks[0]

    def test_plus_list_grouped(self):
        """Lista com + como marcador."""
        paragraphs = ["+ item 1", "+ item 2", "Normal."]
        blocks = _group_into_blocks(paragraphs)
        assert len(blocks) == 2

    def test_empty_paragraphs(self):
        """Lista vazia retorna lista vazia."""
        blocks = _group_into_blocks([])
        assert blocks == []

    def test_single_paragraph(self):
        """Um único parágrafo retorna lista com um elemento."""
        blocks = _group_into_blocks(["Hello world."])
        assert blocks == ["Hello world."]

    def test_pre_self_closing(self):
        """<pre> com </pre> no mesmo parágrafo não agrupa."""
        paragraphs = ["<pre>code</pre>", "Next paragraph."]
        blocks = _group_into_blocks(paragraphs)
        assert len(blocks) == 2

    def test_table_must_start_with_pipe(self):
        """Parágrafo com | mas sem começar com | não é tratado como tabela."""
        paragraphs = ["This has a | pipe inside", "| real | table |"]
        blocks = _group_into_blocks(paragraphs)
        assert len(blocks) == 2


class TestBoundaryAwareSplit:
    """Testa que _split_text_by_words respeita blocos estruturais."""

    def test_code_block_preserved_across_limit(self):
        """Bloco de código não é cortado mesmo que ultrapasse max_words."""
        filler = " ".join(["word"] * 50)
        code = "```python\n" + " ".join(["code"] * 30) + "\n```"
        text = f"{filler}\n\n{code}\n\nTexto final."
        # max_words=60: filler tem 50, code tem 30 → total 80
        # Sem boundary-aware cortaria no meio do code
        chunks = _split_text_by_words(text, 60)
        # Code block deve estar inteiro em um dos chunks
        code_found = any(
            "```python" in c[0] and "```" in c[0].split("```python", 1)[1]
            for c in chunks
        )
        assert code_found, "Bloco de código foi cortado!"

    def test_pre_with_blank_lines_not_split(self):
        """A <pre> with blank lines stays whole in one sub-chunk."""
        code = "\n\n".join("    " + " ".join([f"w{i}"] * 20) for i in range(3))
        text = strip_html(f"<p>Intro.</p><pre>{code}</pre><p>End.</p>")
        chunks = _split_text_by_words(text, 25)
        assert any(f"```\n{code}\n```" in c for c, _ in chunks)

    def test_list_preserved_across_limit(self):
        """Lista contígua não é cortada."""
        filler = " ".join(["word"] * 50)
        list_text = "\n\n".join(
            [f"- item {i} " + " ".join(["desc"] * 5) for i in range(6)]
        )
        text = f"{filler}\n\n{list_text}\n\nFim."
        chunks = _split_text_by_words(text, 60)
        # Todos os items devem estar no mesmo chunk
        for chunk_text, _ in chunks:
            if "- item 0" in chunk_text:
                assert "- item 5" in chunk_text, "Lista foi cortada!"
                break

    def test_oversized_block_not_split(self):
        """Bloco que sozinho excede max_words permanece inteiro."""
        code = "```\n" + " ".join(["x"] * 200) + "\n```"
        text = f"Intro.\n\n{code}\n\nFim."
        chunks = _split_text_by_words(text, 50)
        code_found = any("```" in c[0] and c[0].count("```") >= 2 for c in chunks)
        assert code_found

    def test_char_offsets_correct(self):
        """char_offset continua correto com blocos agrupados."""
        text = "Parágrafo um.\n\n```\ncode\n```\n\nParágrafo três."
        chunks = _split_text_by_words(text, 1000)
        assert len(chunks) == 1
        assert chunks[0][1] == 0

    def test_no_regression_normal_text(self):
        """Texto sem blocos estruturais funciona como antes."""
        text = "\n\n".join(
            [f"Parágrafo {i}. " + " ".join(["w"] * 10) for i in range(10)]
        )
        chunks = _split_text_by_words(text, 30)
        # Deve ter múltiplos chunks, nenhum vazio
        assert len(chunks) > 1
        assert all(c[0].strip() for c in chunks)

    def test_char_offsets_with_split(self):
        """char_offsets são corretos quando ocorre split."""
        p1 = " ".join(["word"] * 20)
        p2 = " ".join(["other"] * 20)
        p3 = " ".join(["final"] * 20)
        text = f"{p1}\n\n{p2}\n\n{p3}"
        chunks = _split_text_by_words(text, 25)
        # Each chunk's offset should point to its start in original text
        for chunk_text, offset in chunks:
            assert text[offset:offset + 10] == chunk_text[:10]

    def test_table_preserved(self):
        """Tabela markdown não é cortada."""
        filler = " ".join(["word"] * 50)
        table = "| A | B |\n\n| --- | --- |\n\n| 1 | 2 |\n\n| 3 | 4 |"
        text = f"{filler}\n\n{table}\n\nEnd."
        chunks = _split_text_by_words(text, 55)
        # Table rows should be in the same chunk
        for chunk_text, _ in chunks:
            if "| A | B |" in chunk_text:
                assert "| 3 | 4 |" in chunk_text, "Tabela foi cortada!"
                break

    def test_empty_text(self):
        """Texto vazio retorna resultado padrão."""
        result = _split_text_by_words("", 100)
        assert result == [("", 0)]

    def test_zero_max_words(self):
        """max_words=0 retorna texto inteiro."""
        result = _split_text_by_words("Hello world", 0)
        assert result == [("Hello world", 0)]
