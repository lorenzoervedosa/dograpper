"""Tests for the hit-rate evaluation harness."""

from dograpper.lib.pack_reader import PackedChunk
from dograpper.lib.golden_qa import generate_golden_qa
from dograpper.lib.retrieval import build_index
from dograpper.lib.eval_harness import EvalReport, evaluate


def _chunks():
    return [
        PackedChunk(id="c1", source="c1", grade="A",
                    text="Installation guide: run pip install to set up the package.",
                    breadcrumb=["Guide", "Installation"]),
        PackedChunk(id="c2", source="c2", grade="B",
                    text="Configuration options control logging verbosity and output.",
                    breadcrumb=["Guide", "Configuration"]),
    ]


def test_report_shape_and_perfect_hit_rate():
    chunks = _chunks()
    pairs = generate_golden_qa(chunks)
    index = build_index(chunks)
    report = evaluate(index, chunks, pairs, k=5)
    assert isinstance(report, EvalReport)
    assert report.total_questions == 2
    assert report.hits == 2
    assert report.hit_rate == 1.0
    assert report.k == 5


def test_mrr_reflects_rank():
    chunks = _chunks()
    pairs = generate_golden_qa(chunks)
    index = build_index(chunks)
    report = evaluate(index, chunks, pairs, k=5)
    # Both expected chunks retrieved at rank 1 -> MRR == 1.0
    assert report.mrr == 1.0


def test_genuine_miss_scores_zero():
    # Target chunk's own text does NOT contain the token from its deepest
    # breadcrumb heading ("gamma"), so the generated question can never
    # score the target highest on its own content.
    target = PackedChunk(id="z_target", source="z", grade="C",
                          text="entirely unrelated filler content here",
                          breadcrumb=["Section", "Gamma"])
    # Decoy has an empty breadcrumb (generates no golden pair of its own)
    # but is saturated with the "gamma" token, so it outranks the target
    # for the question "What does the documentation say about Gamma?".
    decoy = PackedChunk(id="a_decoy", source="a", grade="A",
                         text="gamma gamma gamma gamma",
                         breadcrumb=[])
    chunks = [target, decoy]
    pairs = generate_golden_qa(chunks)
    assert len(pairs) == 1
    assert pairs[0].expected_id == "z_target"

    index = build_index(chunks)
    report = evaluate(index, chunks, pairs, k=1)
    assert report.total_questions == 1
    assert report.hits == 0
    assert report.hit_rate == 0.0
    assert report.mrr == 0.0


def test_per_grade_breakdown():
    chunks = _chunks()
    pairs = generate_golden_qa(chunks)
    index = build_index(chunks)
    report = evaluate(index, chunks, pairs, k=5)
    assert set(report.per_grade.keys()) == {"A", "B"}
    assert report.per_grade["A"]["questions"] == 1
    assert report.per_grade["A"]["hit_rate"] == 1.0


def test_empty_pairs_returns_zeroed_report():
    report = evaluate(build_index(_chunks()), _chunks(), [], k=5)
    assert report.total_questions == 0
    assert report.hit_rate == 0.0
    assert report.mrr == 0.0


def test_unknown_grade_bucketed():
    chunks = [PackedChunk(id="c1", source="c1", grade="", text="alpha beta",
                          breadcrumb=["X", "Alpha"])]
    pairs = generate_golden_qa(chunks)
    report = evaluate(build_index(chunks), chunks, pairs, k=3)
    assert "unknown" in report.per_grade
