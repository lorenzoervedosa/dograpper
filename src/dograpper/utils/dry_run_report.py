"""Dry-run report generation for the pack command.

Receives processed pipeline data (file stats, projected chunks,
word/token counts) and produces a formatted terminal report.
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class FileStats:
    """Per-file statistics collected during pipeline."""
    filepath: str
    words_before_extraction: int
    words_after_extraction: int
    tokens: Optional[int] = None
    words_after_dedup: Optional[int] = None


@dataclass
class DryRunData:
    """Aggregated data for the dry-run report."""
    total_files_found: int
    total_files_excluded: int
    file_stats: list
    projected_chunks: int
    max_chunks: int
    max_words_per_chunk: int
    strategy: str
    show_tokens: bool = False
    token_encoding: str = "cl100k"
    oversize_files: int = 0
    dedup_stats: object = None  # Optional DedupStats
    readiness_scores: list = field(default_factory=list)
    show_score: bool = False


def _effective_words(f: FileStats) -> int:
    """Return the most-processed word count for a file."""
    if f.words_after_dedup is not None:
        return f.words_after_dedup
    return f.words_after_extraction


def generate_report(data: DryRunData) -> str:
    """Build the full dry-run report as a formatted string."""
    lines = []
    lines.append("")
    lines.append("Dry-run report (no files written):")
    lines.append("\u2500" * 55)

    # --- Section 1: Overview ---
    lines.append("")
    lines.append("  Files found:           " + str(data.total_files_found))
    lines.append("  Files excluded:        " + str(data.total_files_excluded))
    lines.append("  Files processed:       " + str(len(data.file_stats)))

    total_before = sum(f.words_before_extraction for f in data.file_stats)
    total_after = sum(f.words_after_extraction for f in data.file_stats)

    lines.append("")
    lines.append("  Words (raw):           " + f"{total_before:,}")
    lines.append("  Words (extracted):     " + f"{total_after:,}")

    if total_before > 0:
        reduction = (total_before - total_after) * 100 // total_before
        lines.append(f"  Extraction reduction:  {reduction}%")

    # Dedup stats
    if data.dedup_stats is not None:
        total_after_dedup = sum(_effective_words(f) for f in data.file_stats)
        lines.append(f"  Words (post-dedup):    {total_after_dedup:,}")
        if total_after > 0:
            dedup_pct = data.dedup_stats.words_removed * 100 // total_after
        else:
            dedup_pct = 0
        lines.append(
            f"  Dedup removed:         {data.dedup_stats.words_removed:,} words "
            f"({dedup_pct}%) \u2014 {data.dedup_stats.blocks_removed_exact} exact, "
            f"{data.dedup_stats.blocks_removed_fuzzy} fuzzy"
        )
        # Same wording as the "Matches kept" line of the pack summary (commands/pack.py).
        lines.append(
            f"  Dedup matches kept:    {data.dedup_stats.blocks_kept_same_page} same-page, "
            f"{data.dedup_stats.blocks_kept_leading_token} leading-token, "
            f"{data.dedup_stats.blocks_kept_numbers} numbers-only"
        )

    if data.show_tokens:
        total_tokens = sum(f.tokens for f in data.file_stats if f.tokens is not None)
        lines.append(f"  Total tokens:          {total_tokens:,} ({data.token_encoding})")

    # --- Section 2: Chunk projection ---
    lines.append("")
    lines.append("  Strategy:              " + data.strategy)
    lines.append("  Limit per chunk:       " + f"{data.max_words_per_chunk:,} words")
    lines.append("  Projected chunks:      " + f"{data.projected_chunks} / {data.max_chunks} (max)")
    if data.oversize_files > 0:
        lines.append(f"  \u26a0 Oversize files:      {data.oversize_files} (exceed the limit on their own)")

    # --- Section 3: Top 10 files ---
    lines.append("")
    lines.append("  Top 10 files by words (after extraction):")
    lines.append("  " + "\u2500" * 53)

    sorted_files = sorted(data.file_stats, key=lambda f: _effective_words(f), reverse=True)
    top_n = sorted_files[:10]

    for i, f in enumerate(top_n, 1):
        name = _truncate_path(f.filepath, max_len=40)
        ew = _effective_words(f)
        words_str = f"{ew:,}"

        if data.show_tokens and f.tokens is not None:
            tokens_str = f"{f.tokens:,} tok"
            line = f"  {i:>2}. {name:<40} {words_str:>7} words  {tokens_str:>10}"
        else:
            compression = ""
            if f.words_before_extraction > 0 and f.words_before_extraction != ew:
                pct = (f.words_before_extraction - ew) * 100 // f.words_before_extraction
                compression = f"  (-{pct}%)"
            line = f"  {i:>2}. {name:<40} {words_str:>7} words{compression}"

        lines.append(line)

    # --- Section 4: Projected distribution ---
    if data.projected_chunks > 0:
        total_effective = sum(_effective_words(f) for f in data.file_stats)
        avg_words = total_effective // data.projected_chunks
        lines.append("")
        lines.append(f"  Projected average:     ~{avg_words:,} words/chunk")

    # --- Section 5: LLM Readiness (opt-in) ---
    if data.show_score and data.readiness_scores:
        lines.append("")
        lines.append("  LLM Readiness Score (boundary not verifiable in dry-run):")
        lines.append("  " + "─" * 53)
        lines.append(f"  {'Chunk':<20} {'Score':>6} {'Grade':>6} {'Noise':>7} {'Boundary':>9} {'Depth':>6}")
        lines.append("  " + "─" * 53)
        for s in data.readiness_scores:
            boundary = "–"
            lines.append(
                f"  {s.chunk_id:<20} {s.score:>5.2f} {s.grade:>6} "
                f"{s.noise_ratio:>6.1%} {boundary:>9} {s.context_depth:>6}"
            )
        avg = sum(s.score for s in data.readiness_scores) / len(data.readiness_scores)
        lines.append("  " + "─" * 53)
        lines.append(f"  {'Average':<20} {avg:>5.2f}")

    # --- Footer ---
    lines.append("")
    lines.append("\u2500" * 55)
    lines.append("Adjust parameters and run without --dry-run to pack.")
    lines.append("")

    return "\n".join(lines)


def _truncate_path(path: str, max_len: int = 40) -> str:
    """Shorten long paths keeping the tail visible."""
    if len(path) <= max_len:
        return path
    return "..." + path[-(max_len - 3):]
