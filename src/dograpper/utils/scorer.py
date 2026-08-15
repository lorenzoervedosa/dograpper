"""LLM Readiness scoring for chunks."""

import re
from dataclasses import dataclass
from typing import List


@dataclass
class ChunkScore:
    chunk_id: str
    word_count: int
    noise_ratio: float
    boundary_integrity: bool
    context_depth: int
    score: float
    grade: str


@dataclass
class BoundaryIssue:
    """A broken structural block located in the text."""
    kind: str      # "code_fence" or "pre_tag"
    line: int      # 1-based line number
    snippet: str   # the offending line


def calculate_noise_ratio(raw_words: int, extracted_words: int) -> float:
    """Proportion of words removed by extraction (boilerplate).

    Returns 0.0 if raw_words is 0 or extracted >= raw (no noise).
    """
    if raw_words <= 0:
        return 0.0
    noise = 1.0 - (extracted_words / raw_words)
    return max(0.0, min(1.0, noise))


def _line_at(text: str, pos: int) -> tuple:
    """Return (1-based line number, full line content) for a char position."""
    line_number = text.count('\n', 0, pos) + 1
    start = text.rfind('\n', 0, pos) + 1
    end = text.find('\n', pos)
    if end == -1:
        end = len(text)
    return line_number, text[start:end]


def find_boundary_issues(text: str) -> List[BoundaryIssue]:
    """Locate broken structural blocks in the text.

    Detects:
    - Unbalanced ``` fences (odd count) -> one issue at the last fence
    - Unbalanced <pre>...</pre> tags -> one issue at the first unmatched
      opener (or first surplus closer when closers exceed openers)
    """
    issues = []

    fences = list(re.finditer(r'```', text))
    if len(fences) % 2 != 0:
        line, snippet = _line_at(text, fences[-1].start())
        issues.append(BoundaryIssue(kind="code_fence", line=line, snippet=snippet))

    opens = [(m.start(), 'open') for m in re.finditer(r'<pre[\s>]', text, re.IGNORECASE)]
    closes = [(m.start(), 'close') for m in re.finditer(r'</pre>', text, re.IGNORECASE)]
    if len(opens) != len(closes):
        # Pair tags in document order to locate the offender
        stack = []
        first_surplus_close = None
        for pos, kind in sorted(opens + closes):
            if kind == 'open':
                stack.append(pos)
            elif stack:
                stack.pop()
            elif first_surplus_close is None:
                first_surplus_close = pos
        pos = stack[0] if len(opens) > len(closes) else first_surplus_close
        line, snippet = _line_at(text, pos)
        issues.append(BoundaryIssue(kind="pre_tag", line=line, snippet=snippet))

    return issues


def check_boundary_integrity(text: str) -> bool:
    """Check whether the text contains broken structural blocks.

    Detects:
    - Unbalanced ``` fences (odd count)
    - Unbalanced <pre>...</pre> tags
    """
    return len(find_boundary_issues(text)) == 0


def calculate_context_depth(headings_count: int, max_level: int) -> int:
    """Depth of preserved context.

    Returns max_level if headings exist, else 0.
    """
    if headings_count > 0 and max_level > 0:
        return max_level
    return 0


# Metric weights shared by calculate_grade and penalty_breakdown —
# the composite invariant is score == 1 - sum(penalties).
NOISE_WEIGHT = 0.4
BOUNDARY_WEIGHT = 0.3
CONTEXT_WEIGHT = 0.3


def _context_score(context_depth: int) -> float:
    """Context sub-score: depth >= 2 = 1.0, depth == 1 = 0.5, depth == 0 = 0.0."""
    if context_depth >= 2:
        return 1.0
    if context_depth == 1:
        return 0.5
    return 0.0


def penalty_breakdown(noise_ratio: float, boundary_ok: bool, context_depth: int) -> List[tuple]:
    """Score lost per metric, as (label, penalty) pairs.

    Uses the same weights as calculate_grade so the decomposition can
    never drift from the composite score.
    """
    return [
        ("noise", NOISE_WEIGHT * noise_ratio),
        ("boundary", 0.0 if boundary_ok else BOUNDARY_WEIGHT),
        ("context", CONTEXT_WEIGHT * (1.0 - _context_score(context_depth))),
    ]


def calculate_grade(noise_ratio: float, boundary_ok: bool, context_depth: int) -> tuple:
    """Calculate composite score (0-1) and grade (A/B/C).

    Weights:
    - noise_ratio: 40% (lower = better -> score_noise = 1 - noise_ratio)
    - boundary_integrity: 30% (True = 1.0, False = 0.0)
    - context_depth: 30% (depth >= 2 = 1.0, depth == 1 = 0.5, depth == 0 = 0.0)
    """
    score_noise = 1.0 - noise_ratio
    score_boundary = 1.0 if boundary_ok else 0.0
    score_context = _context_score(context_depth)

    score = (score_noise * NOISE_WEIGHT
             + score_boundary * BOUNDARY_WEIGHT
             + score_context * CONTEXT_WEIGHT)

    if score >= 0.8:
        grade = "A"
    elif score >= 0.5:
        grade = "B"
    else:
        grade = "C"

    return score, grade


def score_chunk(
    chunk_id: str,
    text: str,
    raw_words: int,
    extracted_words: int,
    headings_count: int,
    max_heading_level: int,
) -> ChunkScore:
    """Main function — calculate all metrics for a chunk."""
    noise = calculate_noise_ratio(raw_words, extracted_words)
    boundary_ok = check_boundary_integrity(text)
    depth = calculate_context_depth(headings_count, max_heading_level)
    score, grade = calculate_grade(noise, boundary_ok, depth)

    return ChunkScore(
        chunk_id=chunk_id,
        word_count=len(text.split()),
        noise_ratio=noise,
        boundary_integrity=boundary_ok,
        context_depth=depth,
        score=score,
        grade=grade,
    )
