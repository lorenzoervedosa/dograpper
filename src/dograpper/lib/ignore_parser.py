"""Parser for exclusion rules."""

import os
import logging
from typing import List, Optional

import pathspec

logger = logging.getLogger(__name__)

# Binary / non-text file extensions that must never be read as text. The pack
# pipeline reads every file with errors="replace" and counts len(text.split())
# as "words"; feeding it a PNG/JPEG turns raw binary bytes into tens of
# thousands of bogus "words", polluting chunks, token counts and dedup. These
# are skipped during file discovery by default, regardless of user ignore rules.
BINARY_EXTENSIONS = frozenset({
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".ico", ".bmp", ".tiff",
    ".pdf", ".zip", ".gz", ".tar", ".bz2", ".7z", ".rar",
    ".mp4", ".webm", ".mov", ".avi", ".mp3", ".wav", ".ogg",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".exe", ".dmg", ".bin", ".wasm", ".so", ".dll",
})


def is_binary_path(path: str) -> bool:
    """Return True if ``path`` has a known binary/non-text extension."""
    _, ext = os.path.splitext(path)
    return ext.lower() in BINARY_EXTENSIONS


def filter_files(file_paths: List[str], ignore_file: Optional[str], ignore_patterns: List[str], base_dir: str, skip_binary: bool = True) -> List[str]:
    """Applies pathspec validation filtering against `.docsignore` files and inline filters.

    When ``skip_binary`` is True (default), files with a known binary extension
    (see ``BINARY_EXTENSIONS``) are dropped up front so the pack pipeline never
    reads their bytes as text.
    """
    # Drop binary/non-text files first: they would otherwise be read as text
    # and have their raw bytes counted as words downstream.
    if skip_binary:
        kept = []
        for full_path in file_paths:
            if is_binary_path(full_path):
                logger.debug(f"Excluded (binary): {full_path}")
            else:
                kept.append(full_path)
        file_paths = kept

    patterns = []

    # Load from ignore_file if it exists
    if ignore_file and os.path.exists(ignore_file):
        try:
            with open(ignore_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#'):
                        patterns.append(line)
        except Exception as e:
            logger.warning(f"Could not read ignore file {ignore_file}: {e}")

    # Combine with inline patterns
    for pat in ignore_patterns:
        if pat.strip():
            patterns.append(pat.strip())
            
    if not patterns:
        # No patterns, everything passes
        return list(file_paths)
        
    spec = pathspec.PathSpec.from_lines('gitignore', patterns)
    
    filtered_paths = []
    for full_path in file_paths:
        try:
            rel_path = os.path.relpath(full_path, base_dir)
            
            # pathspec handles unix separators uniformly best
            unix_rel_path = rel_path.replace(os.sep, '/')
            
            if spec.match_file(unix_rel_path):
                logger.debug(f"Excluded: {unix_rel_path}")
            else:
                filtered_paths.append(full_path)
        except ValueError:
            # If path represents something outside base_dir just append it implicitly
            filtered_paths.append(full_path)
            
    return filtered_paths
