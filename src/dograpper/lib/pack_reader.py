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


def load_chunks(chunks_dir: str, prefix: str = "docs_chunk_",
                files: List[str] = None) -> List[PackedChunk]:
    """Load JSONL chunk files under ``chunks_dir``.

    By default loads all ``<prefix>*.jsonl``; pass ``files`` (paths) to
    load an exact set instead — prefix globbing is ambiguous once chunk
    indices grow a digit (``docs_chunk_10`` also matches
    ``docs_chunk_100.jsonl``).
    """
    if files is not None:
        paths = sorted(files)
    else:
        paths = sorted(glob.glob(os.path.join(chunks_dir, f"{prefix}*.jsonl")))
    chunks: List[PackedChunk] = []
    for path in paths:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not isinstance(rec, dict):
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
