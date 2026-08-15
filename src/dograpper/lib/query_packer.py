"""Query-oriented file ordering for `pack --for-queries` (issue #22).

Reorders source files by BM25 affinity to a list of expected user
queries, so content answering the same query lands in the same chunk.
Reuses the deterministic BM25 engine from lib/retrieval.py. Pure
library layer — no click, no CLI concerns.
"""

from dataclasses import dataclass, field
from typing import Dict, List

from .retrieval import build_index, tokenize

# Invariant: a query term present in more than this fraction of the
# corpus carries no co-location signal and is ignored when matching
# (BM25 idf is always > 0 here, so without this filter a stopword-laden
# first query would claim nearly every file).
COMMON_TERM_DF_RATIO = 0.5

# The df filter exists to stop one query from absorbing a LARGE corpus;
# below this floor (e.g. a --delta subset of 1-2 files) it only creates
# spurious zero-match warnings — an n=1 corpus must still match a query
# quoting its exact content.
MIN_DOCS_FOR_DF_FILTER = 5


@dataclass
class _Doc:
    id: str
    text: str


@dataclass
class QueryAssignment:
    """Files newly assigned to one query, in BM25 hit order."""
    query: str
    files: List[str] = field(default_factory=list)
    total_hits: int = 0  # hits with score > 0, regardless of assignment


@dataclass
class QueryPackResult:
    ordered_paths: List[str]
    assignments: List[QueryAssignment]
    unmatched_files: List[str]
    matched_count: int


def load_queries(path: str) -> List[str]:
    """Read one query per line; blank lines and '#' comments are skipped.

    Raises OSError for a missing or unreadable file — the CLI layer
    turns that into a user-facing error.
    """
    queries = []
    with open(path, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith('#'):
                continue
            queries.append(stripped)
    return queries


def order_files_by_queries(rel_paths, texts: Dict[str, str],
                           queries: List[str]) -> QueryPackResult:
    """Reorder ``rel_paths`` by greedy BM25 assignment to ``queries``.

    Docs are indexed in sorted(rel_paths) order; each query (in file
    order) drops its corpus-common terms (COMMON_TERM_DF_RATIO), then
    claims its still-unassigned hits with score > 0, keeping the
    engine's (-score, doc_id) hit order. Unassigned files go last,
    sorted. Fully deterministic.
    """
    docs = [_Doc(id=rp, text=texts.get(rp, "")) for rp in sorted(rel_paths)]
    index = build_index(docs)

    assigned = set()
    assignments = []
    for query in queries:
        if index.n_docs >= MIN_DOCS_FOR_DF_FILTER:
            # tokenize is idempotent on its own output, so re-joining the
            # surviving terms searches exactly those terms.
            search_query = " ".join(
                t for t in tokenize(query)
                if index.df.get(t, 0) <= COMMON_TERM_DF_RATIO * index.n_docs)
        else:
            search_query = query
        hits = index.search(search_query, k=len(docs))
        assignment = QueryAssignment(query=query)
        for hit in hits:
            if hit.score <= 0:
                continue
            assignment.total_hits += 1
            if hit.doc_id not in assigned:
                assigned.add(hit.doc_id)
                assignment.files.append(hit.doc_id)
        assignments.append(assignment)

    unmatched = sorted(rp for rp in rel_paths if rp not in assigned)
    ordered = [rp for a in assignments for rp in a.files] + unmatched
    return QueryPackResult(
        ordered_paths=ordered,
        assignments=assignments,
        unmatched_files=unmatched,
        matched_count=len(assigned),
    )
