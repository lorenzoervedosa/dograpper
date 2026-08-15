"""Inspection of packed chunk files for the explain preview.

Pure parsing/loading helpers — no writes to disk. Understands the three
pack formats (md, txt, jsonl), the embedded dograpper-context-v1 headers,
and the sidecar artifacts llm-readiness.json / cross_refs.json.
"""

import glob
import json
import os
import re
from dataclasses import dataclass, field
from typing import List, Optional


V1_HEADER_RE = re.compile(
    r"<!-- dograpper-context-v1\n(.*?)\n-->\n?", re.DOTALL)
MD_SOURCE_RE = re.compile(r"<!-- SOURCE: (.*?) -->\n?")
TXT_SOURCE_RE = re.compile(r"=== SOURCE: (.*?) ===\n?")


@dataclass
class ChunkSection:
    """One LLM-visible section of a chunk: optional v1 header + content."""
    content: str
    header: Optional[dict] = None    # parsed dograpper-context-v1 payload
    source: str = ""                 # from header or SOURCE marker
    breadcrumb: List[str] = field(default_factory=list)


@dataclass
class ChunkInfo:
    """A chunk file found on disk."""
    chunk_id: str      # e.g. docs_chunk_00
    path: str
    format: str        # md | txt | jsonl


def discover_chunks(chunks_dir: str, prefix: str = "docs_chunk_") -> List[ChunkInfo]:
    """Find chunk files under chunks_dir, sorted by id. No writes."""
    infos: List[ChunkInfo] = []
    for ext in ("md", "txt", "jsonl"):
        for path in glob.glob(os.path.join(chunks_dir, f"{prefix}*.{ext}")):
            chunk_id = os.path.splitext(os.path.basename(path))[0]
            infos.append(ChunkInfo(chunk_id=chunk_id, path=path, format=ext))
    infos.sort(key=lambda c: (c.chunk_id, c.format))
    return infos


def parse_chunk_sections(text: str) -> List[ChunkSection]:
    """Split md/txt chunk text into sections exactly as the LLM sees them.

    Sections are delimited by dograpper-context-v1 headers when present,
    falling back to SOURCE markers, then to a single whole-file section.
    """
    matches = list(V1_HEADER_RE.finditer(text))
    if matches:
        sections = []
        leading = text[:matches[0].start()].strip("\n")
        if leading.strip():
            sections.append(ChunkSection(content=leading))
        for i, m in enumerate(matches):
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            content = text[m.end():end].strip("\n")
            try:
                payload = json.loads(m.group(1))
            except json.JSONDecodeError:
                payload = None
            sections.append(ChunkSection(
                content=content,
                header=payload,
                source=(payload or {}).get("source", ""),
                breadcrumb=list((payload or {}).get("context_breadcrumb", []) or []),
            ))
        return sections

    source_matches = (list(MD_SOURCE_RE.finditer(text))
                      or list(TXT_SOURCE_RE.finditer(text)))
    if source_matches:
        sections = []
        leading = text[:source_matches[0].start()].strip("\n")
        if leading.strip():
            sections.append(ChunkSection(content=leading))
        for i, m in enumerate(source_matches):
            end = (source_matches[i + 1].start()
                   if i + 1 < len(source_matches) else len(text))
            sections.append(ChunkSection(
                content=text[m.end():end].strip("\n"),
                source=m.group(1),
            ))
        return sections

    return [ChunkSection(content=text)]


def load_sidecar(chunks_dir: str, filename: str) -> Optional[dict]:
    """Load a JSON sidecar artifact (llm-readiness.json, cross_refs.json)."""
    path = os.path.join(chunks_dir, filename)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def readiness_for(readiness: Optional[dict], chunk_id: str) -> Optional[dict]:
    """Per-chunk entry from llm-readiness.json, or None."""
    if not readiness:
        return None
    for entry in readiness.get("chunks", []):
        if entry.get("chunk_id") == chunk_id:
            return entry
    return None


def cross_refs_for(cross_refs: Optional[dict], chunk_id: str) -> Optional[dict]:
    """Per-chunk entry from cross_refs.json, or None."""
    if not cross_refs:
        return None
    return cross_refs.get(chunk_id)
