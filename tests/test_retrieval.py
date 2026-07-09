"""Tests for the deterministic BM25 retrieval engine."""

from dataclasses import dataclass

from dograpper.lib.retrieval import tokenize, build_index, RetrievalHit


@dataclass
class _Doc:
    id: str
    text: str


def _corpus():
    return [
        _Doc(id="c1", text="Click is a Python package for creating command line interfaces."),
        _Doc(id="c2", text="Flask is a lightweight WSGI web application framework in Python."),
        _Doc(id="c3", text="The command line parser handles options and arguments."),
    ]


def test_tokenize_lowercases_and_splits():
    assert tokenize("Hello, WORLD! 123") == ["hello", "world", "123"]


def test_tokenize_empty():
    assert tokenize("") == []


def test_search_returns_relevant_doc_first():
    index = build_index(_corpus())
    hits = index.search("command line interface", k=3)
    assert hits[0].doc_id in {"c1", "c3"}
    assert all(isinstance(h, RetrievalHit) for h in hits)
    assert [h.rank for h in hits] == [1, 2, 3]


def test_search_top_k_limits_results():
    index = build_index(_corpus())
    hits = index.search("python", k=2)
    assert len(hits) == 2


def test_search_is_deterministic():
    index = build_index(_corpus())
    first = index.search("python framework", k=3)
    second = index.search("python framework", k=3)
    assert [(h.doc_id, h.score, h.rank) for h in first] == \
           [(h.doc_id, h.score, h.rank) for h in second]


def test_search_tie_break_by_doc_id():
    # Two docs with identical text score equally -> stable order by doc_id asc.
    docs = [_Doc(id="zeta", text="same words here"),
            _Doc(id="alpha", text="same words here")]
    index = build_index(docs)
    hits = index.search("same words", k=2)
    assert [h.doc_id for h in hits] == ["alpha", "zeta"]


def test_search_no_match_returns_zero_scores():
    index = build_index(_corpus())
    hits = index.search("zzzznonexistentterm", k=3)
    assert all(h.score == 0.0 for h in hits)
