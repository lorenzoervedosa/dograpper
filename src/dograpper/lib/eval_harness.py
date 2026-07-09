"""Hit-rate evaluation of packed chunks via deterministic retrieval.

For each golden pair, run the question through the BM25 index and check
whether the expected chunk id appears in the top-k. Reports overall
hit-rate and MRR, plus a per-readiness-grade breakdown so the heuristic
grade can be correlated with empirical retrieval quality (issue #11).
"""

from dataclasses import dataclass, field
from typing import List, Dict

from .retrieval import BM25Index
from .pack_reader import PackedChunk
from .golden_qa import GoldenPair


@dataclass
class EvalReport:
    k: int
    total_questions: int
    hits: int
    hit_rate: float
    mrr: float
    per_grade: Dict[str, dict] = field(default_factory=dict)


def evaluate(index: BM25Index, chunks: List[PackedChunk],
             pairs: List[GoldenPair], k: int = 5) -> EvalReport:
    grade_by_id = {c.id: c.grade for c in chunks}
    hits = 0
    reciprocal_sum = 0.0
    grade_totals: Dict[str, int] = {}
    grade_hits: Dict[str, int] = {}

    for pair in pairs:
        result = index.search(pair.question, k)
        rank = None
        for hit in result:
            if hit.doc_id == pair.expected_id:
                rank = hit.rank
                break
        grade = grade_by_id.get(pair.expected_id, "") or "unknown"
        grade_totals[grade] = grade_totals.get(grade, 0) + 1
        if rank is not None:
            hits += 1
            reciprocal_sum += 1.0 / rank
            grade_hits[grade] = grade_hits.get(grade, 0) + 1

    total = len(pairs)
    hit_rate = hits / total if total else 0.0
    mrr = reciprocal_sum / total if total else 0.0

    per_grade: Dict[str, dict] = {}
    for g in sorted(grade_totals.keys()):
        gt = grade_totals[g]
        gh = grade_hits.get(g, 0)
        per_grade[g] = {
            "questions": gt,
            "hits": gh,
            "hit_rate": gh / gt if gt else 0.0,
        }

    return EvalReport(
        k=k,
        total_questions=total,
        hits=hits,
        hit_rate=hit_rate,
        mrr=mrr,
        per_grade=per_grade,
    )
