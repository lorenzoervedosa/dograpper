"""Tests for deterministic offline golden Q&A generation."""

from dograpper.lib.pack_reader import PackedChunk
from dograpper.lib.golden_qa import GoldenPair, generate_golden_qa


def _chunk(cid, breadcrumb):
    return PackedChunk(id=cid, source=cid, text="body", breadcrumb=breadcrumb)


def test_generates_one_pair_per_chunk_with_breadcrumb():
    chunks = [_chunk("c1", ["Guide", "Installation"]),
              _chunk("c2", ["Guide", "Configuration"])]
    pairs = generate_golden_qa(chunks)
    assert len(pairs) == 2
    assert all(isinstance(p, GoldenPair) for p in pairs)


def test_pair_uses_deepest_heading_and_maps_to_chunk():
    pairs = generate_golden_qa([_chunk("c1", ["Guide", "Installation"])])
    p = pairs[0]
    assert p.expected_id == "c1"
    assert p.heading == "Installation"
    assert "Installation" in p.question


def test_skips_chunks_without_breadcrumb():
    chunks = [_chunk("c1", []), _chunk("c2", ["Only", "This"])]
    pairs = generate_golden_qa(chunks)
    assert [p.expected_id for p in pairs] == ["c2"]


def test_skips_blank_heading():
    pairs = generate_golden_qa([_chunk("c1", ["Guide", "   "])])
    assert pairs == []


def test_generation_is_deterministic():
    chunks = [_chunk("c1", ["A", "B"]), _chunk("c2", ["C", "D"])]
    assert generate_golden_qa(chunks) == generate_golden_qa(chunks)
