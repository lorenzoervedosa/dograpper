"""Tests for lib/query_packer.py — query-oriented file ordering (issue #22)."""

import os
import tempfile

import pytest

from dograpper.lib.query_packer import load_queries, order_files_by_queries


# --- load_queries ---

def _write_queries(path, content):
    with open(path, 'w', encoding='utf-8') as f:
        f.write(content)


def test_load_queries_parses_lines_in_order():
    with tempfile.TemporaryDirectory() as d:
        qfile = os.path.join(d, 'queries.txt')
        _write_queries(qfile, "how to install\nhow to test\nhow to configure\n")
        assert load_queries(qfile) == [
            "how to install", "how to test", "how to configure"]


def test_load_queries_skips_blank_lines_and_comments():
    with tempfile.TemporaryDirectory() as d:
        qfile = os.path.join(d, 'queries.txt')
        _write_queries(qfile, "# expected user queries\n\nfirst query\n"
                              "   \n# another comment\nsecond query\n")
        assert load_queries(qfile) == ["first query", "second query"]


def test_load_queries_missing_file_raises():
    with tempfile.TemporaryDirectory() as d:
        with pytest.raises(OSError):
            load_queries(os.path.join(d, 'nope.txt'))


def test_load_queries_only_comments_yields_empty():
    with tempfile.TemporaryDirectory() as d:
        qfile = os.path.join(d, 'queries.txt')
        _write_queries(qfile, "# just a comment\n\n")
        assert load_queries(qfile) == []


# --- order_files_by_queries ---

TEXTS = {
    "guide/install.html": "installation installation pip package manager",
    "misc/notes.html": ("installation mentioned once here surrounded by many "
                        "unrelated filler words about various other topics "
                        "that dilute the term frequency considerably overall"),
    "guide/testing.html": "pytest testing runner fixtures assertions",
    "extra/orphan.html": "banana smoothie recipe with oats",
    "extra/zebra.html": "zebra stripes savanna wildlife",
}

QUERIES = ["installation pip", "pytest testing"]


def test_order_files_by_queries_colocation_and_score_order():
    result = order_files_by_queries(list(TEXTS.keys()), TEXTS, QUERIES)
    # Query 1 files first, in score order: install.html has higher term
    # frequency and a shorter doc than notes.html.
    assert result.assignments[0].files == [
        "guide/install.html", "misc/notes.html"]
    assert result.assignments[1].files == ["guide/testing.html"]
    assert result.ordered_paths[:3] == [
        "guide/install.html", "misc/notes.html", "guide/testing.html"]


def test_order_files_by_queries_unmatched_last_sorted():
    result = order_files_by_queries(list(TEXTS.keys()), TEXTS, QUERIES)
    assert result.ordered_paths[3:] == [
        "extra/orphan.html", "extra/zebra.html"]
    assert result.unmatched_files == ["extra/orphan.html", "extra/zebra.html"]
    assert result.matched_count == 3


def test_order_files_by_queries_deterministic():
    first = order_files_by_queries(list(TEXTS.keys()), TEXTS, QUERIES)
    # Shuffled input path order must not change the outcome.
    shuffled = list(reversed(sorted(TEXTS.keys())))
    second = order_files_by_queries(shuffled, TEXTS, QUERIES)
    assert first.ordered_paths == second.ordered_paths
    assert [a.files for a in first.assignments] == [
        a.files for a in second.assignments]


def test_order_files_by_queries_tiebreak_by_doc_id():
    # n=2 is below MIN_DOCS_FOR_DF_FILTER, so "widgets" being in both
    # docs does not disqualify it here.
    texts = {
        "b.html": "identical content about widgets",
        "a.html": "identical content about widgets",
    }
    result = order_files_by_queries(list(texts.keys()), texts, ["widgets"])
    assert result.assignments[0].files == ["a.html", "b.html"]


def test_order_files_by_queries_file_assigned_once():
    texts = dict(TEXTS)
    texts["guide/both.html"] = "installation and pytest together"
    result = order_files_by_queries(
        list(texts.keys()), texts, QUERIES)
    assert result.ordered_paths.count("guide/both.html") == 1
    assert "guide/both.html" in result.assignments[0].files
    assert "guide/both.html" not in result.assignments[1].files
    # every file appears exactly once overall
    assert sorted(result.ordered_paths) == sorted(texts.keys())


def test_order_files_by_queries_zero_match_query():
    result = order_files_by_queries(
        list(TEXTS.keys()), TEXTS,
        ["xyzzynonexistent terms", "pytest testing"])
    assert result.assignments[0].files == []
    assert result.assignments[0].total_hits == 0
    assert result.assignments[1].files == ["guide/testing.html"]
    assert result.assignments[1].total_hits > 0


def test_order_files_by_queries_common_terms_carry_no_signal():
    texts = {
        "a.html": "the guide covers installation steps",
        "b.html": "the guide covers testing steps",
        "c.html": "the guide covers deployment steps",
        "d.html": "the guide covers configuration steps",
        "e.html": "the guide covers upgrade steps",
    }
    # Every query term appears in all 5 docs (df ratio 1.0 > 0.5):
    # no co-location signal, so nothing may be assigned.
    result = order_files_by_queries(
        list(texts.keys()), texts, ["the guide steps"])
    assert result.assignments[0].files == []
    assert result.assignments[0].total_hits == 0
    assert result.unmatched_files == [
        "a.html", "b.html", "c.html", "d.html", "e.html"]
    assert result.matched_count == 0


def test_order_files_by_queries_mixed_query_uses_discriminative_terms():
    texts = {
        "a.html": "how to frobnicate the widget quickly",
        "b.html": "how to configure the settings panel",
        "c.html": "how to deploy the application stack",
        "d.html": "how to test the release branch",
        "e.html": "how to monitor the running service",
    }
    # "how"/"to"/"the" are in every doc (dropped); "frobnicate" only in
    # a.html — the query must assign via its discriminative term alone.
    result = order_files_by_queries(
        list(texts.keys()), texts, ["how do I frobnicate"])
    assert result.assignments[0].files == ["a.html"]
    assert result.unmatched_files == ["b.html", "c.html", "d.html", "e.html"]
    # Determinism holds with the filter active.
    again = order_files_by_queries(
        list(reversed(sorted(texts.keys()))), texts, ["how do I frobnicate"])
    assert again.ordered_paths == result.ordered_paths


def test_order_files_by_queries_small_corpus_skips_df_filter():
    # Delta subsets are often 1-2 files where every meaningful term is
    # "ubiquitous" by construction; below the floor the filter must not
    # discard exact-content queries.
    texts = {
        "a.html": "delta changed page about widgets",
        "b.html": "another delta changed page about widgets",
    }
    result = order_files_by_queries(list(texts.keys()), texts, ["widgets"])
    assert result.assignments[0].files == ["a.html", "b.html"]
    assert result.assignments[0].total_hits == 2
    assert result.unmatched_files == []
