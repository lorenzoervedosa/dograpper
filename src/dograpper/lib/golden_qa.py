"""Deterministic, offline golden Q&A generation from chunk structure.

No network, no external model — questions are templated over each chunk's
heading breadcrumb, and the expected answer is the chunk that owns that
heading. Same chunks (in the same order) always produce the same pairs.
"""

from dataclasses import dataclass
from typing import List

from .pack_reader import PackedChunk

_QUESTION_TEMPLATE = "What does the documentation say about {heading}?"


@dataclass
class GoldenPair:
    question: str
    expected_id: str
    heading: str


def generate_golden_qa(chunks: List[PackedChunk]) -> List[GoldenPair]:
    """One pair per chunk that has a non-empty deepest breadcrumb heading."""
    pairs: List[GoldenPair] = []
    for chunk in chunks:
        if not chunk.breadcrumb:
            continue
        heading = chunk.breadcrumb[-1].strip()
        if not heading:
            continue
        pairs.append(GoldenPair(
            question=_QUESTION_TEMPLATE.format(heading=heading),
            expected_id=chunk.id,
            heading=heading,
        ))
    return pairs
