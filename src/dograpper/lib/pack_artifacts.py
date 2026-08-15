"""Sidecar artifacts a pack run writes next to the chunks.

Everything here runs after ``write_chunks`` and touches the output directory
only: cross-reference index, delta manifest, readiness JSON, readiness HTML
report, and the token count of each written chunk. Keeping them out of the
``pack`` orchestrator leaves it wiring steps together instead of formatting
files.
"""

import json
import logging
import os
from dataclasses import dataclass
from typing import Dict, List

from ..utils.link_extractor import annotate_cross_refs, build_cross_ref_index, extract_links

logger = logging.getLogger(__name__)


@dataclass
class CrossRefStats:
    total: int = 0
    unresolved: int = 0


def _chunk_id(prefix: str, chunk) -> str:
    return f"{prefix}{chunk.index:02d}"


def write_cross_refs(chunks, filtered_paths: List[str], input_dir: str,
                     output_dir: str, prefix: str, fmt: str) -> CrossRefStats:
    """Write ``cross_refs.json`` and annotate the chunk files in place."""
    # Map each source file to its chunk, including the normalized form of
    # index.html so links resolved by extract_links can match.
    file_to_chunk = {}
    for chunk in chunks:
        cid = _chunk_id(prefix, chunk)
        for cf in chunk.files:
            file_to_chunk[cf.relative_path] = cid
            rp = cf.relative_path
            if rp.endswith("/index.html"):
                file_to_chunk[rp[:-len("/index.html")]] = cid
            elif rp == "index.html":
                file_to_chunk[""] = cid

    all_links = []
    for fpath in filtered_paths:
        if not fpath.lower().endswith(('.html', '.htm')):
            continue
        try:
            with open(fpath, 'r', encoding='utf-8', errors='replace') as fh:
                raw_html = fh.read()
        except Exception:
            continue
        rel = os.path.relpath(fpath, input_dir).replace(os.sep, '/')
        all_links.extend(extract_links(raw_html, rel))

    cross_index = build_cross_ref_index(all_links, file_to_chunk)
    stats = CrossRefStats(
        total=sum(len(entry.get("links", []))
                  for key, entry in cross_index.items() if key != "unresolved"),
        unresolved=len(cross_index.get("unresolved", [])),
    )

    with open(os.path.join(output_dir, "cross_refs.json"), 'w', encoding='utf-8') as jf:
        json.dump(cross_index, jf, indent=2, ensure_ascii=False)

    for chunk in chunks:
        cid = _chunk_id(prefix, chunk)
        chunk_filename = f"{cid}.{fmt}"
        chunk_filepath = os.path.join(output_dir, chunk_filename)
        chunk_links = [lnk for lnk in all_links
                       if file_to_chunk.get(lnk.source_path) == cid]
        if not chunk_links:
            continue
        try:
            with open(chunk_filepath, 'r', encoding='utf-8', errors='replace') as cf:
                chunk_text = cf.read()
            annotated = annotate_cross_refs(chunk_text, chunk_links, file_to_chunk)
            if annotated != chunk_text:
                with open(chunk_filepath, 'w', encoding='utf-8') as cf:
                    cf.write(annotated)
        except Exception as e:
            logger.warning(f"Failed to annotate cross-refs for {chunk_filename}: {e}")

    return stats


def write_delta_manifest(diff, chunks, output_dir: str, prefix: str,
                         timestamp: str) -> str:
    """Record what this delta run reprocessed. Returns the file path."""
    delta_info = {
        "timestamp": timestamp,
        "added": diff.added,
        "modified": diff.modified,
        "removed": diff.removed,
        "chunks_generated": [
            {
                "chunk": _chunk_id(prefix, c),
                "files": [cf.relative_path for cf in c.files],
            }
            for c in chunks
        ],
    }
    delta_path = os.path.join(output_dir, "delta_manifest.json")
    with open(delta_path, 'w', encoding='utf-8') as df:
        json.dump(delta_info, df, indent=2)
    return delta_path


def readiness_snapshot(scores) -> Dict:
    """Build the ``llm-readiness.json`` payload from the chunk scores."""
    return {
        "summary": {
            "total_chunks": len(scores),
            "avg_score": round(sum(s.score for s in scores) / len(scores), 2) if scores else 0,
            "grades": {
                "A": sum(1 for s in scores if s.grade == "A"),
                "B": sum(1 for s in scores if s.grade == "B"),
                "C": sum(1 for s in scores if s.grade == "C"),
            },
        },
        "chunks": [
            {
                "chunk_id": s.chunk_id,
                "word_count": s.word_count,
                "noise_ratio": round(s.noise_ratio, 3),
                "boundary_integrity": s.boundary_integrity,
                "context_depth": s.context_depth,
                "score": round(s.score, 2),
                "grade": s.grade,
            }
            for s in scores
        ],
    }


def write_readiness_json(scores, output_dir: str) -> str:
    """Write ``llm-readiness.json``. Returns the file path."""
    readiness_path = os.path.join(output_dir, "llm-readiness.json")
    with open(readiness_path, 'w', encoding='utf-8') as rf:
        json.dump(readiness_snapshot(scores), rf, indent=2)
    return readiness_path


def write_readiness_report(scores, report_pages, output_dir: str) -> str:
    """Write ``readiness-report.html``. Returns the file path."""
    from ..utils.readiness_report import generate_html_report

    report_path = os.path.join(output_dir, "readiness-report.html")
    with open(report_path, 'w', encoding='utf-8') as rf:
        rf.write(generate_html_report(scores, report_pages))
    return report_path


def count_chunk_tokens(chunks, output_dir: str, prefix: str, fmt: str,
                       encoding: str) -> List:
    """Count tokens on the chunk files as written, skipping unreadable ones."""
    from ..utils.token_counter import count_tokens

    token_counts = []
    for chunk in chunks:
        chunk_filename = f"{_chunk_id(prefix, chunk)}.{fmt}"
        chunk_filepath = os.path.join(output_dir, chunk_filename)
        try:
            with open(chunk_filepath, 'r', encoding='utf-8', errors='replace') as cf:
                chunk_text = cf.read()
            tc = count_tokens(chunk_text, encoding=encoding)
            token_counts.append(tc)
            logger.debug(f"[tokens] {chunk_filename}: {tc.words} words → "
                         f"{tc.tokens} tokens ({tc.encoding})")
        except Exception as e:
            logger.warning(f"Failed to count tokens for {chunk_filename}: {e}")
    return token_counts
