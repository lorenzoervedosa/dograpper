"""LLM readiness scoring across the chunks a pack run produced.

Each chunk's source files are read once and turned into three things: the
per-chunk :class:`~dograpper.utils.scorer.ChunkScore`, the map injected into
chunk headers, and — only when a readiness report was asked for — the
per-page rows that report is built from.
"""

import logging
import os
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ..utils.content_extractor import extract_content
from ..utils.html_stripper import strip_html
from ..utils.readiness_report import PageReadiness, find_removed_blocks
from ..utils.scorer import (
    ChunkScore,
    calculate_noise_ratio,
    find_boundary_issues,
    score_chunk,
)

logger = logging.getLogger(__name__)


@dataclass
class ScoringResult:
    """Everything the pack run needs out of a scoring pass."""

    scores: List[ChunkScore] = field(default_factory=list)
    # chunk_id -> per-page rows; empty unless the caller asked for a report.
    report_pages: Dict[str, List[PageReadiness]] = field(default_factory=dict)

    def header_map(self) -> Dict[str, dict]:
        """Readiness values injected into chunk headers and JSONL records."""
        return {
            s.chunk_id: {
                "score": round(s.score, 2),
                "grade": s.grade,
                "noise_ratio": round(s.noise_ratio, 3),
            }
            for s in self.scores
        }


def _read_page(fpath: str, rel_path: str, no_extract: bool):
    """Return (raw_text, extracted_text) for one source file, or (None, None).

    Any failure — unreadable file, extractor blowing up on malformed markup —
    drops the page from the score instead of failing the whole run.
    """
    is_html = fpath.lower().endswith(('.html', '.htm'))
    try:
        with open(fpath, 'r', encoding='utf-8', errors='replace') as fh:
            content = fh.read()
        if not is_html:
            return content, content
        raw_text = strip_html(content)
        extracted_text = raw_text if no_extract else strip_html(extract_content(content))
        return raw_text, extracted_text
    except Exception as e:
        kind = "unprocessable" if is_html else "unreadable"
        logger.warning(f"[score] Skipping {kind} file {rel_path}: {e}")
        return None, None


def score_chunks(
    chunks,
    input_dir: str,
    prefix: str,
    no_extract: bool,
    heading_map: Optional[Dict[str, list]] = None,
    text_overrides: Optional[Dict[str, str]] = None,
    with_report: bool = False,
) -> ScoringResult:
    """Score every chunk, optionally collecting per-page report rows.

    ``text_overrides`` (post-dedup text keyed by relative path) wins over the
    freshly extracted text for the boundary check, so the score reflects what
    is actually written to disk.
    """
    result = ScoringResult()

    for chunk in chunks:
        chunk_id = f"{prefix}{chunk.index:02d}"

        raw_total = 0
        extracted_total = 0
        headings_count = 0
        max_heading_level = 0
        chunk_text_parts = []
        chunk_pages = []

        for cf in chunk.files:
            fpath = os.path.join(input_dir, cf.relative_path)
            raw_text, extracted_text = _read_page(fpath, cf.relative_path, no_extract)
            if raw_text is not None and extracted_text is not None:
                raw_total += len(raw_text.split())
                extracted_total += len(extracted_text.split())

            file_headings = []
            if heading_map and cf.relative_path in heading_map:
                file_headings = heading_map[cf.relative_path]
                headings_count += len(file_headings)
                if file_headings:
                    max_heading_level = max(
                        max_heading_level, max(h.level for h in file_headings))

            # Content for the boundary check: the dedup override wins over
            # the text re-processed above.
            if text_overrides and cf.relative_path in text_overrides:
                chunk_text_parts.append(text_overrides[cf.relative_path])
            elif extracted_text is not None:
                chunk_text_parts.append(extracted_text)

            if with_report and raw_text is not None and extracted_text is not None:
                page_raw = len(raw_text.split())
                page_extracted = len(extracted_text.split())
                chunk_pages.append(PageReadiness(
                    relative_path=cf.relative_path,
                    raw_words=page_raw,
                    extracted_words=page_extracted,
                    noise_ratio=calculate_noise_ratio(page_raw, page_extracted),
                    headings_count=len(file_headings),
                    max_heading_level=max((h.level for h in file_headings), default=0),
                    first_headings=[h.text for h in file_headings[:3]],
                    removed_samples=find_removed_blocks(raw_text, extracted_text),
                    boundary_issues=find_boundary_issues(extracted_text),
                ))

        result.scores.append(score_chunk(
            chunk_id=chunk_id,
            text="\n\n".join(chunk_text_parts),
            raw_words=raw_total,
            extracted_words=extracted_total,
            headings_count=headings_count,
            max_heading_level=max_heading_level,
        ))

        if with_report:
            result.report_pages[chunk_id] = chunk_pages

    return result
