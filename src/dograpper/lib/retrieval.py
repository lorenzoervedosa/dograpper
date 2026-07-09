"""Deterministic BM25 retrieval engine over packed chunks.

Shared infrastructure consumed by `eval` (#11), and later `serve` (#10)
and `pack --for-queries` (#22). Pure stdlib — no network, no heavy deps.

Determinism: stable tokenization, and ties in ranking are broken by
ascending ``doc_id`` so the same query always yields the same order.
"""

import math
import re
from dataclasses import dataclass
from typing import List, Dict

_TOKEN_RE = re.compile(r"[a-z0-9]+")

_K1 = 1.5
_B = 0.75


def tokenize(text: str) -> List[str]:
    """Lowercase and split into alphanumeric tokens. Deterministic."""
    return _TOKEN_RE.findall(text.lower())


@dataclass
class RetrievalHit:
    doc_id: str
    score: float
    rank: int


@dataclass
class BM25Index:
    doc_ids: List[str]
    doc_lengths: List[int]
    doc_freqs: List[Dict[str, int]]
    df: Dict[str, int]
    avgdl: float
    n_docs: int
    k1: float = _K1
    b: float = _B

    def _score_doc(self, i: int, q_terms: List[str]) -> float:
        freqs = self.doc_freqs[i]
        dl = self.doc_lengths[i]
        score = 0.0
        for t in q_terms:
            f = freqs.get(t, 0)
            if f == 0:
                continue
            df = self.df.get(t, 0)
            idf = math.log((self.n_docs - df + 0.5) / (df + 0.5) + 1.0)
            if self.avgdl > 0:
                denom = f + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            else:
                denom = f + self.k1
            if denom > 0:
                score += idf * (f * (self.k1 + 1) / denom)
        return score

    def search(self, query: str, k: int = 5) -> List[RetrievalHit]:
        q_terms = tokenize(query)
        scored = [(self.doc_ids[i], self._score_doc(i, q_terms))
                  for i in range(self.n_docs)]
        # Higher score first; ties broken by ascending doc_id for determinism.
        scored.sort(key=lambda x: (-x[1], x[0]))
        return [RetrievalHit(doc_id=doc_id, score=score, rank=rank)
                for rank, (doc_id, score) in enumerate(scored[:k], start=1)]


def build_index(docs) -> BM25Index:
    """Build a BM25 index. ``docs`` = iterable of objects with ``.id`` and ``.text``."""
    doc_ids: List[str] = []
    doc_lengths: List[int] = []
    doc_freqs: List[Dict[str, int]] = []
    df: Dict[str, int] = {}

    for doc in docs:
        toks = tokenize(doc.text)
        freqs: Dict[str, int] = {}
        for t in toks:
            freqs[t] = freqs.get(t, 0) + 1
        doc_ids.append(doc.id)
        doc_lengths.append(len(toks))
        doc_freqs.append(freqs)
        for t in freqs:
            df[t] = df.get(t, 0) + 1

    n = len(doc_ids)
    avgdl = (sum(doc_lengths) / n) if n else 0.0
    return BM25Index(
        doc_ids=doc_ids,
        doc_lengths=doc_lengths,
        doc_freqs=doc_freqs,
        df=df,
        avgdl=avgdl,
        n_docs=n,
    )
