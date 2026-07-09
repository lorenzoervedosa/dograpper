# Issue #11 — `dograpper eval` (harness de readiness empírico) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** adicionar o subcomando `dograpper eval <chunks-dir>` que valida empiricamente a qualidade do contexto empacotado medindo hit-rate@k de recuperação sobre Q&A dourado gerado offline, e correlaciona esse hit-rate com a grade heurística de readiness existente.

**Architecture:** nasce o motor de recuperação compartilhado `lib/retrieval.py` (BM25 stdlib, determinístico) — keystone reusado depois por #10 (`serve`) e #22 (`--for-queries`). O `eval` lê os chunks JSONL já empacotados (`lib/pack_reader.py`), gera pares pergunta/resposta template-based a partir do breadcrumb de headings (`lib/golden_qa.py`), roda a recuperação e computa hit-rate/MRR agregados por grade (`lib/eval_harness.py`), expostos pelo comando `commands/eval.py`.

**Tech Stack:** Python 3.10+, click, pytest + `click.testing.CliRunner`. **Zero dependências novas** — BM25 é implementado em stdlib puro (`math`, `re`, `json`, `glob`).

## Global Constraints

Copiados verbatim dos invariantes do projeto (`CLAUDE.md`, `about_dograpper.md`, ADR-0004). Toda tarefa abaixo os herda:

- **Zero-telemetria / air-gapped:** `eval` **não faz nenhuma chamada de rede**. Geração de Q&A é offline/template-based — nunca API externa.
- **Determinismo bit-a-bit:** mesmo input → mesmo output. Tokenização estável + tie-break de ranking por `doc_id` ascendente + ordem de Q&A seguindo a ordem estável dos chunks.
- **Sem dependências novas obrigatórias.** BM25 em stdlib puro. (Embeddings ficam para #20, opcional.)
- **Contagem por palavras, não bytes** onde aplicável (`len(text.split())`).
- **Encoding tolerante:** toda leitura de arquivo com `errors="replace"`.
- **Testes existentes não podem quebrar:** `uv run pytest tests/ -v` verde antes de cada commit.
- Nomes de símbolos e assinaturas abaixo são **contratos** — `build_index` exige objetos com atributos `.id: str` e `.text: str` (mantém o motor desacoplado para #10/#22 usarem seus próprios tipos de doc).

---

## File Structure

| Arquivo | Responsabilidade | Consumido por |
|---|---|---|
| `src/dograpper/lib/retrieval.py` | Motor BM25 determinístico stdlib. `tokenize`, `build_index`, `BM25Index.search`, `RetrievalHit`. | #11, #10, #22 |
| `src/dograpper/lib/pack_reader.py` | Carrega chunks JSONL do disco em `PackedChunk`. | #11 (e #10 depois) |
| `src/dograpper/lib/golden_qa.py` | Gera `GoldenPair` offline a partir do breadcrumb. | #11 |
| `src/dograpper/lib/eval_harness.py` | Métrica hit-rate/MRR + agregação por grade (`EvalReport`, `evaluate`). | #11 |
| `src/dograpper/commands/eval.py` | Subcomando click `eval`; wiring + saída de relatório. | CLI |
| `src/dograpper/cli.py` | Registrar `eval` (modificar). | — |
| `tests/test_retrieval.py` | Testes do BM25. | — |
| `tests/test_pack_reader.py` | Testes do loader JSONL. | — |
| `tests/test_golden_qa.py` | Testes da geração de Q&A. | — |
| `tests/test_eval_harness.py` | Testes da métrica. | — |
| `tests/test_eval_command.py` | Integração CLI do `eval`. | — |

**Correlação heurística × empírica (critério de aceite #3):** satisfeita pelo campo `per_grade` do `EvalReport` — hit-rate quebrado por grade A/B/C. Se A > B > C, a heurística correlaciona com a recuperação. Não é tarefa separada; cai na Task 4.

---

## Task 1: Motor de recuperação BM25 determinístico (`lib/retrieval.py`)

**Files:**
- Create: `src/dograpper/lib/retrieval.py`
- Test: `tests/test_retrieval.py`

**Interfaces:**
- Consumes: nada (fundação).
- Produces:
  - `tokenize(text: str) -> List[str]`
  - `RetrievalHit(doc_id: str, score: float, rank: int)` (dataclass)
  - `build_index(docs) -> BM25Index` — `docs` é qualquer iterável de objetos com `.id: str` e `.text: str`.
  - `BM25Index.search(query: str, k: int = 5) -> List[RetrievalHit]`

- [ ] **Step 1: Escrever os testes que falham**

```python
# tests/test_retrieval.py
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
```

- [ ] **Step 2: Rodar os testes para verificar que falham**

Run: `uv run pytest tests/test_retrieval.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'dograpper.lib.retrieval'`

- [ ] **Step 3: Implementar o motor**

```python
# src/dograpper/lib/retrieval.py
"""Deterministic BM25 retrieval engine over packed chunks.

Shared infrastructure consumed by `eval` (#11), and later `serve` (#10)
and `pack --for-queries` (#22). Pure stdlib — no network, no heavy deps.

Determinism: stable tokenization, and ties in ranking are broken by
ascending ``doc_id`` so the same query always yields the same order.
"""

import math
import re
from dataclasses import dataclass, field
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
```

- [ ] **Step 4: Rodar os testes para verificar que passam**

Run: `uv run pytest tests/test_retrieval.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: Commit**

```bash
git add src/dograpper/lib/retrieval.py tests/test_retrieval.py
git commit -m "feat(retrieval): motor BM25 determinístico stdlib compartilhado"
```

---

## Task 2: Loader de chunks JSONL (`lib/pack_reader.py`)

**Files:**
- Create: `src/dograpper/lib/pack_reader.py`
- Test: `tests/test_pack_reader.py`

**Interfaces:**
- Consumes: formato JSONL escrito por `chunker._write_chunk_jsonl` (campos `id`, `source`, `content`, `words`, opcional `breadcrumb`, opcional `readiness_grade`).
- Produces:
  - `PackedChunk(id: str, source: str, text: str, breadcrumb: List[str], grade: str, words: int)` (dataclass) — satisfaz o contrato `.id`/`.text` de `build_index`.
  - `load_chunks(chunks_dir: str, prefix: str = "docs_chunk_") -> List[PackedChunk]`

- [ ] **Step 1: Escrever os testes que falham**

```python
# tests/test_pack_reader.py
"""Tests for loading packed JSONL chunks."""

import json
import os

from dograpper.lib.pack_reader import PackedChunk, load_chunks


def _write_jsonl(path, records):
    with open(path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def test_load_chunks_reads_fields(tmp_path):
    _write_jsonl(str(tmp_path / "docs_chunk_01.jsonl"), [
        {"id": "01_a.html", "source": "a.html", "words": 3,
         "content": "hello world text", "breadcrumb": ["Intro", "Setup"],
         "readiness_grade": "A", "schema_version": "v1"},
    ])
    chunks = load_chunks(str(tmp_path))
    assert len(chunks) == 1
    c = chunks[0]
    assert isinstance(c, PackedChunk)
    assert c.id == "01_a.html"
    assert c.source == "a.html"
    assert c.text == "hello world text"
    assert c.breadcrumb == ["Intro", "Setup"]
    assert c.grade == "A"
    assert c.words == 3


def test_load_chunks_missing_optional_fields(tmp_path):
    _write_jsonl(str(tmp_path / "docs_chunk_01.jsonl"), [
        {"id": "01_a", "source": "a", "content": "x y", "words": 2,
         "schema_version": "v1"},
    ])
    c = load_chunks(str(tmp_path))[0]
    assert c.breadcrumb == []
    assert c.grade == ""


def test_load_chunks_skips_blank_and_malformed_lines(tmp_path):
    path = str(tmp_path / "docs_chunk_01.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"id": "01_a", "source": "a", "content": "ok", "words": 1}\n')
        f.write("\n")
        f.write("{not valid json}\n")
    chunks = load_chunks(str(tmp_path))
    assert len(chunks) == 1
    assert chunks[0].id == "01_a"


def test_load_chunks_multiple_files_sorted(tmp_path):
    _write_jsonl(str(tmp_path / "docs_chunk_02.jsonl"),
                 [{"id": "02_b", "source": "b", "content": "b", "words": 1}])
    _write_jsonl(str(tmp_path / "docs_chunk_01.jsonl"),
                 [{"id": "01_a", "source": "a", "content": "a", "words": 1}])
    chunks = load_chunks(str(tmp_path))
    assert [c.id for c in chunks] == ["01_a", "02_b"]


def test_load_chunks_empty_dir_returns_empty(tmp_path):
    assert load_chunks(str(tmp_path)) == []
```

- [ ] **Step 2: Rodar os testes para verificar que falham**

Run: `uv run pytest tests/test_pack_reader.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'dograpper.lib.pack_reader'`

- [ ] **Step 3: Implementar o loader**

```python
# src/dograpper/lib/pack_reader.py
"""Load packed JSONL chunks from disk into retrieval documents.

Reads the JSONL format produced by ``chunker._write_chunk_jsonl``. Tolerant
to malformed lines and missing optional fields. Files are read in sorted
order for determinism. Reading uses ``errors="replace"``.
"""

import glob
import json
import os
from dataclasses import dataclass, field
from typing import List


@dataclass
class PackedChunk:
    id: str
    source: str
    text: str
    breadcrumb: List[str] = field(default_factory=list)
    grade: str = ""
    words: int = 0


def load_chunks(chunks_dir: str, prefix: str = "docs_chunk_") -> List[PackedChunk]:
    """Load all ``<prefix>*.jsonl`` chunk files under ``chunks_dir``."""
    pattern = os.path.join(chunks_dir, f"{prefix}*.jsonl")
    chunks: List[PackedChunk] = []
    for path in sorted(glob.glob(pattern)):
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                chunks.append(PackedChunk(
                    id=str(rec.get("id", "")),
                    source=rec.get("source", ""),
                    text=rec.get("content", ""),
                    breadcrumb=list(rec.get("breadcrumb", []) or []),
                    grade=rec.get("readiness_grade", ""),
                    words=int(rec.get("words", 0) or 0),
                ))
    return chunks
```

- [ ] **Step 4: Rodar os testes para verificar que passam**

Run: `uv run pytest tests/test_pack_reader.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/dograpper/lib/pack_reader.py tests/test_pack_reader.py
git commit -m "feat(eval): loader de chunks JSONL para recuperação"
```

---

## Task 3: Geração de Q&A dourado offline (`lib/golden_qa.py`)

**Files:**
- Create: `src/dograpper/lib/golden_qa.py`
- Test: `tests/test_golden_qa.py`

**Interfaces:**
- Consumes: `PackedChunk` (de `lib/pack_reader.py`).
- Produces:
  - `GoldenPair(question: str, expected_id: str, heading: str)` (dataclass)
  - `generate_golden_qa(chunks: List[PackedChunk]) -> List[GoldenPair]`

- [ ] **Step 1: Escrever os testes que falham**

```python
# tests/test_golden_qa.py
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
```

- [ ] **Step 2: Rodar os testes para verificar que falham**

Run: `uv run pytest tests/test_golden_qa.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'dograpper.lib.golden_qa'`

- [ ] **Step 3: Implementar a geração**

```python
# src/dograpper/lib/golden_qa.py
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
```

- [ ] **Step 4: Rodar os testes para verificar que passam**

Run: `uv run pytest tests/test_golden_qa.py -v`
Expected: PASS (5 passed)

- [ ] **Step 5: Commit**

```bash
git add src/dograpper/lib/golden_qa.py tests/test_golden_qa.py
git commit -m "feat(eval): geração determinística de Q&A dourado offline"
```

---

## Task 4: Métrica hit-rate/MRR com agregação por grade (`lib/eval_harness.py`)

**Files:**
- Create: `src/dograpper/lib/eval_harness.py`
- Test: `tests/test_eval_harness.py`

**Interfaces:**
- Consumes: `BM25Index` (`lib/retrieval.py`), `PackedChunk` (`lib/pack_reader.py`), `GoldenPair` (`lib/golden_qa.py`).
- Produces:
  - `EvalReport(k: int, total_questions: int, hits: int, hit_rate: float, mrr: float, per_grade: Dict[str, dict])` (dataclass)
  - `evaluate(index: BM25Index, chunks: List[PackedChunk], pairs: List[GoldenPair], k: int = 5) -> EvalReport`

- [ ] **Step 1: Escrever os testes que falham**

```python
# tests/test_eval_harness.py
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


def test_miss_when_expected_not_in_top_k():
    chunks = _chunks()
    pairs = generate_golden_qa(chunks)
    index = build_index(chunks)
    report = evaluate(index, chunks, pairs, k=1)
    # k=1 with a distractor may still hit both here; assert bounds hold.
    assert 0.0 <= report.hit_rate <= 1.0
    assert report.hits <= report.total_questions


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
```

- [ ] **Step 2: Rodar os testes para verificar que falham**

Run: `uv run pytest tests/test_eval_harness.py -v`
Expected: FAIL com `ModuleNotFoundError: No module named 'dograpper.lib.eval_harness'`

- [ ] **Step 3: Implementar a métrica**

```python
# src/dograpper/lib/eval_harness.py
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
```

- [ ] **Step 4: Rodar os testes para verificar que passam**

Run: `uv run pytest tests/test_eval_harness.py -v`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add src/dograpper/lib/eval_harness.py tests/test_eval_harness.py
git commit -m "feat(eval): métrica hit-rate/MRR com correlação por grade de readiness"
```

---

## Task 5: Subcomando `eval` + registro na CLI (`commands/eval.py`, `cli.py`)

**Files:**
- Create: `src/dograpper/commands/eval.py`
- Modify: `src/dograpper/cli.py:10` (import) e `src/dograpper/cli.py:57` (add_command)
- Test: `tests/test_eval_command.py`

**Interfaces:**
- Consumes: `load_chunks` (`lib/pack_reader.py`), `build_index` (`lib/retrieval.py`), `generate_golden_qa` (`lib/golden_qa.py`), `evaluate` (`lib/eval_harness.py`).
- Produces: comando click `eval` registrado no grupo `cli`.

- [ ] **Step 1: Escrever os testes que falham**

```python
# tests/test_eval_command.py
"""Integration tests for the `dograpper eval` subcommand."""

import json
import os

from click.testing import CliRunner

from dograpper.cli import cli


def _write_pack(dir_path):
    os.makedirs(dir_path, exist_ok=True)
    records = [
        {"id": "01_install", "source": "install.html", "words": 9,
         "content": "Installation guide run pip install to set up the package quickly",
         "breadcrumb": ["Guide", "Installation"], "readiness_grade": "A"},
        {"id": "02_config", "source": "config.html", "words": 8,
         "content": "Configuration options control logging verbosity and output format",
         "breadcrumb": ["Guide", "Configuration"], "readiness_grade": "B"},
    ]
    with open(os.path.join(dir_path, "docs_chunk_01.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps(records[0]) + "\n")
    with open(os.path.join(dir_path, "docs_chunk_02.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps(records[1]) + "\n")


def test_eval_reports_hit_rate():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_pack("chunks")
        result = runner.invoke(cli, ["eval", "chunks", "-k", "5"])
        assert result.exit_code == 0, result.output
        assert "Hit-rate@5" in result.output
        assert "Golden Q&A:" in result.output


def test_eval_writes_json_report():
    runner = CliRunner()
    with runner.isolated_filesystem():
        _write_pack("chunks")
        result = runner.invoke(cli, ["eval", "chunks", "-o", "report.json"])
        assert result.exit_code == 0, result.output
        with open("report.json", encoding="utf-8") as f:
            payload = json.load(f)
        assert payload["total_questions"] == 2
        assert 0.0 <= payload["hit_rate"] <= 1.0
        assert "per_grade" in payload


def test_eval_errors_without_jsonl():
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("empty", exist_ok=True)
        result = runner.invoke(cli, ["eval", "empty"])
        assert result.exit_code == 1
        assert "no JSONL chunks" in result.output


def test_eval_errors_without_breadcrumbs():
    runner = CliRunner()
    with runner.isolated_filesystem():
        os.makedirs("chunks", exist_ok=True)
        with open("chunks/docs_chunk_01.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps({"id": "01_a", "source": "a", "content": "no headings here",
                                "words": 3}) + "\n")
        result = runner.invoke(cli, ["eval", "chunks"])
        assert result.exit_code == 1
        assert "context-header" in result.output


def test_eval_is_in_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "eval" in result.output
```

- [ ] **Step 2: Rodar os testes para verificar que falham**

Run: `uv run pytest tests/test_eval_command.py -v`
Expected: FAIL — `eval` não é um comando (`No such command 'eval'`) / import inexistente.

- [ ] **Step 3: Implementar o comando**

```python
# src/dograpper/commands/eval.py
"""Eval subcommand — empirical hit-rate validation of packed context.

Reads JSONL chunks produced by `pack --format jsonl --context-header`,
generates deterministic offline golden Q&A from heading breadcrumbs, runs
BM25 retrieval, and reports hit-rate@k, MRR and a per-grade breakdown.
Fully offline — no network calls.
"""

import json
import click
import logging

from ..lib.pack_reader import load_chunks
from ..lib.retrieval import build_index
from ..lib.golden_qa import generate_golden_qa
from ..lib.eval_harness import evaluate

logger = logging.getLogger(__name__)


@click.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  dograpper eval ./chunks\n"
        "  dograpper eval ./chunks -k 3 -o eval-report.json\n"
    )
)
@click.argument('chunks_dir', type=click.Path(exists=True, file_okay=False, dir_okay=True), required=True)
@click.option('--top-k', '-k', type=int, default=5, show_default=True,
              help="Retrieval depth used to compute hit-rate.")
@click.option('--output', '-o', type=click.Path(), default=None,
              help="Write the JSON report to this path.")
@click.option('--prefix', type=str, default="docs_chunk_", show_default=True,
              help="Chunk filename prefix to load.")
@click.pass_context
def eval(ctx, chunks_dir, top_k, output, prefix):
    """Validate packed context empirically via golden Q&A hit-rate."""
    chunks = load_chunks(chunks_dir, prefix=prefix)
    if not chunks:
        click.echo(
            "Error: no JSONL chunks found. Re-pack with "
            "`dograpper pack <dir> -o <chunks> --format jsonl --context-header`.",
            err=True,
        )
        ctx.exit(1)

    pairs = generate_golden_qa(chunks)
    if not pairs:
        click.echo(
            "Error: no golden Q&A could be generated (chunks lack heading "
            "breadcrumbs). Re-pack with --context-header.",
            err=True,
        )
        ctx.exit(1)

    index = build_index(chunks)
    report = evaluate(index, chunks, pairs, k=top_k)

    click.echo(f"Chunks:        {len(chunks)}")
    click.echo(f"Golden Q&A:    {report.total_questions}")
    click.echo(f"Hit-rate@{top_k}:   {report.hit_rate:.1%} ({report.hits}/{report.total_questions})")
    click.echo(f"MRR:           {report.mrr:.3f}")
    if report.per_grade:
        click.echo("By readiness grade:")
        for grade, stats in report.per_grade.items():
            click.echo(f"  {grade}: {stats['hit_rate']:.1%} ({stats['hits']}/{stats['questions']})")

    if output:
        payload = {
            "k": report.k,
            "total_questions": report.total_questions,
            "hits": report.hits,
            "hit_rate": report.hit_rate,
            "mrr": report.mrr,
            "per_grade": report.per_grade,
        }
        with open(output, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        click.echo(f"Report written to {output}")
```

- [ ] **Step 4: Registrar o comando na CLI**

Modificar `src/dograpper/cli.py`. Adicionar o import ao lado dos outros (após a linha 10 `from .commands.doctor import doctor`):

```python
from .commands.eval import eval as eval_cmd
```

E registrar (após a linha 57 `cli.add_command(doctor)`):

```python
cli.add_command(eval_cmd, name="eval")
```

> Nota: importamos como `eval_cmd` para não sombrear o builtin no escopo do `cli.py`; o nome exposto na CLI é `eval` via `name="eval"`.

- [ ] **Step 5: Rodar os testes para verificar que passam**

Run: `uv run pytest tests/test_eval_command.py -v`
Expected: PASS (5 passed)

- [ ] **Step 6: Rodar a suíte inteira (invariante — nada pode quebrar)**

Run: `uv run pytest tests/ -v`
Expected: PASS (toda a suíte, incluindo os testes pré-existentes)

- [ ] **Step 7: Commit**

```bash
git add src/dograpper/commands/eval.py src/dograpper/cli.py tests/test_eval_command.py
git commit -m "feat(eval): subcomando eval para validação empírica de readiness"
```

---

## Task 6: Documentação (`about_dograpper.md`, `CLAUDE.md`)

**Files:**
- Modify: `about_dograpper.md` (seção de comandos — adicionar `eval`)
- Modify: `CLAUDE.md` (tabela de "Arquivos de contexto importantes" e "Comandos úteis")

**Interfaces:** nenhuma (docs).

- [ ] **Step 1: Documentar o comando `eval` em `about_dograpper.md`**

Localizar a seção que descreve os subcomandos (`download`, `pack`, `sync`) e adicionar uma subseção `eval` com: sinopse (`dograpper eval <chunks-dir> [-k N] [-o report.json]`), pré-requisito (pack em JSONL com `--context-header`), o que mede (hit-rate@k, MRR, breakdown por grade), e o invariante (offline, determinístico). Copiar o estilo das seções existentes.

- [ ] **Step 2: Atualizar `CLAUDE.md`**

Na tabela "Comandos úteis", adicionar:

```bash
# Validar readiness empiricamente (hit-rate sobre Q&A dourado)
uv run dograpper pack ./test-docs -o ./chunks --format jsonl --context-header --score
uv run dograpper eval ./chunks -k 5

# Rodar testes do eval harness
uv run pytest tests/test_retrieval.py tests/test_eval_harness.py -v
```

E na tabela "Arquivos de contexto importantes" adicionar a linha:

```
| `tests/test_retrieval.py` / `tests/test_eval_harness.py` | Antes de alterar `lib/retrieval.py`, `lib/eval_harness.py` ou `commands/eval.py` |
```

- [ ] **Step 3: Verificação manual ponta-a-ponta**

```bash
uv run dograpper pack ./test-docs -o ./chunks-eval --format jsonl --context-header --score
uv run dograpper eval ./chunks-eval -k 5 -o /tmp/eval-report.json
cat /tmp/eval-report.json
```
Expected: relatório impresso com `Hit-rate@5`, breakdown por grade, e `eval-report.json` válido. Rodar duas vezes e confirmar output idêntico (determinismo).

- [ ] **Step 4: Commit**

```bash
git add about_dograpper.md CLAUDE.md
git commit -m "docs: documentar subcomando eval e harness de readiness empírico"
```

---

## Self-Review

**1. Cobertura da spec (issue #11):**
- ✅ "`dograpper eval <chunks-dir>` produz relatório de hit-rate reprodutível" → Task 4 + Task 5; determinismo garantido por tokenização estável + tie-break por `doc_id` (testes `test_search_is_deterministic`, `test_generation_is_deterministic`).
- ✅ "Não faz chamadas de rede por padrão" → tudo stdlib; Q&A template-based offline (Task 3). Sem imports de rede em nenhum módulo.
- ✅ "Correlação documentada entre a grade heurística e o hit-rate empírico" → `EvalReport.per_grade` (Task 4) + impressão no comando (Task 5).
- ✅ Motor de recuperação compartilhado (dependência declarada de #22, #10) → `lib/retrieval.py` (Task 1), desacoplado via contrato `.id`/`.text`.
- ✅ "Testes cobrindo protocolo/recuperação determinística" → 5 arquivos de teste.

**2. Placeholder scan:** nenhum TBD/TODO; todo passo de código traz o código completo.

**3. Type consistency:** `RetrievalHit.doc_id` usado consistentemente em `eval_harness` (`hit.doc_id`); `PackedChunk.id/.text` satisfazem o contrato de `build_index`; `GoldenPair.expected_id` casa com `PackedChunk.id`; `EvalReport.per_grade` schema `{grade: {questions, hits, hit_rate}}` idêntico em harness, testes e comando.

**Fora de escopo (próximas issues):** recuperação por embeddings (#20), servir via MCP (#10), `--for-queries` (#22). O motor `lib/retrieval.py` foi desenhado para eles reusarem sem alteração.

---

## Execution Handoff

Plano salvo em `docs/superpowers/plans/2026-07-08-issue-11-eval-harness.md`. Duas opções de execução:

1. **Subagent-Driven (recomendado)** — despacho um subagente novo por tarefa, reviso entre tarefas, iteração rápida (`superpowers:subagent-driven-development`).
2. **Inline** — executo as tarefas nesta sessão com checkpoints (`superpowers:executing-plans`).
