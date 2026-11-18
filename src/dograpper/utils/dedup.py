"""Deduplication of content across documentation files.

Two strategies:
- exact: MD5 hashing of blocks to eliminate 100% identical duplicates.
- fuzzy: simhash to identify near-identical blocks (similarity > threshold).

Blocks = text segments separated by blank lines (paragraphs).

Dedup is cross-file: a match only removes a block when no keep rule applies
(see _keep_reason).
"""

import hashlib
import re
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# Blocks with fewer than MIN_BLOCK_WORDS are skipped by dedup.
MIN_BLOCK_WORDS = 10

# Default Hamming distance threshold for fuzzy dedup.
# Simhash 64-bit: 0 = identical, 64 = completely different.
DEFAULT_HAMMING_THRESHOLD = 3

SIMHASH_BITS = 64

# A token holding a digit: version, date, count, id.
_NUMBER_TOKEN = re.compile(r"\S*\d\S*")


@dataclass
class DedupStats:
    """Deduplication statistics for reporting."""
    total_blocks: int = 0
    blocks_removed_exact: int = 0
    blocks_removed_fuzzy: int = 0
    words_removed: int = 0
    # Blocks that matched an earlier block but were kept by a _keep_reason rule.
    blocks_kept_same_page: int = 0
    blocks_kept_leading_token: int = 0
    blocks_kept_numbers: int = 0

    @property
    def blocks_removed(self) -> int:
        return self.blocks_removed_exact + self.blocks_removed_fuzzy


@dataclass
class DedupResult:
    """Result of deduplicating a set of files."""
    texts: dict  # filepath -> deduplicated text
    stats: DedupStats


def deduplicate(
    texts: dict,
    mode: str = "both",
    hamming_threshold: int = DEFAULT_HAMMING_THRESHOLD,
) -> DedupResult:
    """Deduplicate text blocks across multiple files.

    Args:
        texts: dict filepath -> clean text (post-strip, pre-chunk).
               Iteration order determines which occurrence is kept
               (first wins, alphabetical by path).
        mode: "exact", "fuzzy", or "both".
        hamming_threshold: max Hamming distance for fuzzy dedup.

    Returns:
        DedupResult with deduplicated texts and statistics.
    """
    stats = DedupStats()

    sorted_paths = sorted(texts.keys())

    seen_fuzzy: list = []            # (simhash, filepath, normalized) tuples
    first_seen_exact: dict = {}      # hash -> filepath

    # Track first-seen for logging
    first_seen_fuzzy: list = []      # (simhash, filepath) tuples

    result_texts: dict = {}

    for path in sorted_paths:
        text = texts[path]
        blocks = _split_blocks(text)
        kept_blocks: list = []

        for block in blocks:
            word_count = len(block.split())
            stats.total_blocks += 1

            if word_count < MIN_BLOCK_WORDS:
                kept_blocks.append(block)
                continue

            normalized = _normalize(block)
            kept_by = None  # DedupStats counter of the rule that kept a match

            # --- Exact dedup ---
            if mode in ("exact", "both"):
                block_hash = hashlib.md5(normalized.encode("utf-8")).hexdigest()

                if block_hash not in first_seen_exact:
                    first_seen_exact[block_hash] = path
                elif first_seen_exact[block_hash] == path:
                    kept_by = "blocks_kept_same_page"
                else:
                    stats.blocks_removed_exact += 1
                    stats.words_removed += word_count
                    logger.debug(
                        f"[dedup] exact: removed block ({word_count} words) "
                        f"from \"{path}\" — first seen in \"{first_seen_exact[block_hash]}\""
                    )
                    continue

            # --- Fuzzy dedup ---
            if mode in ("fuzzy", "both"):
                block_simhash = _simhash(normalized)

                matched_path = None
                for existing_hash, existing_path, existing_text in seen_fuzzy:
                    if _hamming_distance(block_simhash, existing_hash) > hamming_threshold:
                        continue
                    reason = _keep_reason(path, normalized, existing_path, existing_text)
                    if reason is None:
                        matched_path = existing_path
                        break
                    kept_by = kept_by or reason

                if matched_path is not None:
                    stats.blocks_removed_fuzzy += 1
                    stats.words_removed += word_count
                    logger.debug(
                        f"[dedup] fuzzy: removed block ({word_count} words) "
                        f"from \"{path}\" — similar to block in \"{matched_path}\""
                    )
                    continue
                seen_fuzzy.append((block_simhash, path, normalized))

            if kept_by:
                setattr(stats, kept_by, getattr(stats, kept_by) + 1)
                logger.debug(f"[dedup] {kept_by}: kept block ({word_count} words) in \"{path}\"")
            kept_blocks.append(block)

        result_texts[path] = "\n\n".join(kept_blocks)

    return DedupResult(texts=result_texts, stats=stats)


def _keep_reason(path: str, text: str, other_path: str, other_text: str):
    """Return the DedupStats counter of the rule that keeps normalized block
    ``text`` of ``path`` although it matches ``other_text`` of ``other_path``,
    or None when it is a duplicate to remove.
    """
    if path == other_path:
        # Repeats inside one page are page content (sibling list entries,
        # parameters sharing a description), not cross-page boilerplate.
        return "blocks_kept_same_page"
    if _leading_token(text) != _leading_token(other_text):
        # A different key, tag or parameter name: a different entry whose
        # body happens to look alike (base:hardcover vs base:hollowbook).
        return "blocks_kept_leading_token"
    if text != other_text and _NUMBER_TOKEN.sub("#", text) == _NUMBER_TOKEN.sub("#", other_text):
        # Only numbers differ, so they are the page's own data: a version
        # banner (42.5.1 vs 42.17.0), a date, a count.
        return "blocks_kept_numbers"
    return None


def _leading_token(text: str) -> str:
    """First token holding a letter or digit, skipping list bullets and pipes."""
    return next((t for t in text.split() if re.search(r"\w", t)), "")


def _split_blocks(text: str) -> list:
    """Split text into blocks separated by blank lines."""
    raw_blocks = text.split("\n\n")
    return [b.strip() for b in raw_blocks if b.strip()]


def _normalize(text: str) -> str:
    """Normalize text for dedup comparison (lowercase, collapse whitespace)."""
    text = text.lower()
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _simhash(text: str, bits: int = SIMHASH_BITS) -> int:
    """Compute simhash of text using word 3-gram shingles.

    Pure Python implementation using hashlib from stdlib.
    """
    words = text.split()
    if len(words) < 3:
        h = hashlib.md5(text.encode("utf-8")).digest()
        return int.from_bytes(h[:8], "big")

    shingles = [" ".join(words[i:i + 3]) for i in range(len(words) - 2)]

    vector = [0] * bits

    for shingle in shingles:
        h = hashlib.md5(shingle.encode("utf-8")).digest()
        h_int = int.from_bytes(h[:8], "big")

        for i in range(bits):
            if (h_int >> i) & 1:
                vector[i] += 1
            else:
                vector[i] -= 1

    fingerprint = 0
    for i in range(bits):
        if vector[i] > 0:
            fingerprint |= (1 << i)

    return fingerprint


def _hamming_distance(a: int, b: int) -> int:
    """Count differing bits between two integers."""
    return bin(a ^ b).count("1")
