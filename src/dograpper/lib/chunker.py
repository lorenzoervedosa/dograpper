"""Core logical engine for chunking texts natively in Python."""

import os
import re
import logging
from dataclasses import dataclass, field
from typing import List, Dict

from ..utils.word_counter import count_words_file
from ..utils.html_stripper import strip_html
from ..utils.content_extractor import extract_content

logger = logging.getLogger(__name__)

@dataclass
class ChunkFile:
    relative_path: str
    word_count: int

@dataclass
class Chunk:
    index: int
    files: List[ChunkFile] = field(default_factory=list)
    total_words: int = 0

def chunk_by_size(files: List[str], base_dir: str, max_words: int, no_extract: bool = False, word_counts: Dict[str, int] = None, preserve_order: bool = False) -> List[Chunk]:
    """Group incoming files in chunks keeping them under the soft limit max_words per chunk.

    With ``preserve_order=True`` the caller's list order is respected
    (used by ``pack --for-queries``); otherwise files are sorted
    alphabetically to keep things predictable.
    """

    sorted_files = list(files) if preserve_order else sorted(files)

    chunks = []
    current_chunk = Chunk(index=1)

    for f in sorted_files:
        rel_path = os.path.relpath(f, base_dir).replace(os.sep, '/')
        if word_counts and rel_path in word_counts:
            words = word_counts[rel_path]
        else:
            words = count_words_file(f, no_extract=no_extract)
        
        # Especial case: Single immense file
        if words > max_words:
            logger.warning(f"File '{rel_path}' has {words} words, exceeding max-words-per-chunk limit of {max_words}. Placing in its own chunk.")
            # If current chunk has something, wrap it up
            if current_chunk.files:
                chunks.append(current_chunk)

            # Form special massive chunk with a fresh, correct index
            special_chunk = Chunk(
                index=len(chunks) + 1,
                files=[ChunkFile(rel_path, words)],
                total_words=words,
            )
            chunks.append(special_chunk)

            # Advance ptr
            current_chunk = Chunk(index=len(chunks) + 1)
            continue
            
        if current_chunk.total_words + words > max_words:
            # Reached threshold for chunk, wrap and restart
            if current_chunk.files:
                chunks.append(current_chunk)
                current_chunk = Chunk(index=len(chunks) + 1)
                
        current_chunk.files.append(ChunkFile(rel_path, words))
        current_chunk.total_words += words
        
    if current_chunk.files:
        chunks.append(current_chunk)
        
    return chunks

def chunk_by_semantic(files: List[str], base_dir: str, max_words: int, no_extract: bool = False, word_counts: Dict[str, int] = None) -> List[Chunk]:
    """Group files by their parent directory, keeping related content together.

    Uses the *full* relative directory path (``os.path.dirname``) as the module
    proxy so nested sections stay together instead of being flattened into the
    top-level folder bucket. Files directly in ``base_dir`` are placed in the
    ``_`` group.
    """

    groups: Dict[str, List[str]] = {}
    for f in files:
        rel = os.path.relpath(f, base_dir)
        dirname = os.path.dirname(rel).replace(os.sep, '/')
        mod = dirname if dirname else '_'
        if mod not in groups:
            groups[mod] = []
        groups[mod].append(f)
    
    # Sort groups alphabetically
    sorted_mods = sorted(groups.keys())
    
    chunks = []
    current_chunk = Chunk(index=1)
    
    for mod in sorted_mods:
        mod_files = sorted(groups[mod])
        
        # Calculate group's total weight
        mod_word_counts = []
        mod_total_words = 0
        for f in mod_files:
            rel_path = os.path.relpath(f, base_dir).replace(os.sep, '/')
            if word_counts and rel_path in word_counts:
                wc = word_counts[rel_path]
            else:
                wc = count_words_file(f, no_extract=no_extract)
            mod_word_counts.append((f, rel_path, wc))
            mod_total_words += wc
            
        if mod_total_words <= max_words:
            if current_chunk.total_words + mod_total_words > max_words:
                # Group doesn't fit here, open new
                if current_chunk.files:
                    chunks.append(current_chunk)
                    current_chunk = Chunk(index=len(chunks) + 1)
            
            # Add entire group
            for f, rel_p, wc in mod_word_counts:
                current_chunk.files.append(ChunkFile(rel_p, wc))
                current_chunk.total_words += wc
        else:
            # Group exceeds max_words, break it using internal `size` strategy for these files
            if current_chunk.files:
                chunks.append(current_chunk)
                current_chunk = Chunk(index=len(chunks) + 1)
                
            sub_chunks = chunk_by_size(mod_files, base_dir, max_words, no_extract=no_extract, word_counts=word_counts)
            for sc in sub_chunks:
                sc.index = current_chunk.index
                chunks.append(sc)
                current_chunk = Chunk(index=len(chunks) + 1)
                
    if current_chunk.files:
        chunks.append(current_chunk)
        
    # Re-index all chunks strictly sequentially
    for i, c in enumerate(chunks):
        c.index = i + 1
        
    return chunks

def balance_chunks(chunks: List[Chunk], target_chunks: int, max_words: int) -> List[Chunk]:
    """Redistribute files across chunks for uniform word balance.

    Used by --bundle to ensure chunks have similar sizes, improving
    LLM ingestion and NotebookLM Audio Overview quality.

    Does not alter file order within each chunk.
    Does not split files — operates at ChunkFile level.
    """
    # Flatten all files preserving order
    flat = []
    for c in chunks:
        flat.extend(c.files)

    if not flat:
        return []

    # If fewer files than target, each file becomes its own chunk
    if len(flat) <= target_chunks:
        result = []
        for i, cf in enumerate(flat):
            result.append(Chunk(index=i + 1, files=[cf], total_words=cf.word_count))
        return result

    total_words = sum(cf.word_count for cf in flat)
    target_words = total_words // target_chunks

    result = []
    current = Chunk(index=1)
    remaining_files = len(flat)

    for cf in flat:
        remaining_files -= 1
        remaining_budget = target_chunks - len(result) - 1  # chunks left after current

        # Close current chunk if adding this file would exceed max_words,
        # but only if we still have budget for more chunks
        if current.files and current.total_words + cf.word_count > max_words and remaining_budget > 0:
            result.append(current)
            current = Chunk(index=len(result) + 1)
            remaining_budget -= 1

        current.files.append(cf)
        current.total_words += cf.word_count

        # Close if we've hit the target and still have budget
        if current.total_words >= target_words and remaining_budget > 0 and remaining_files > 0:
            result.append(current)
            current = Chunk(index=len(result) + 1)

    # Last chunk gets whatever remains
    if current.files:
        result.append(current)

    # Re-index sequentially
    for i, c in enumerate(result):
        c.index = i + 1

    return result


def generate_import_guide(chunks: List[Chunk], output_dir: str, preset: str,
                          total_words: int, heading_map: Dict = None) -> str:
    """Generate IMPORT_GUIDE.md with upload instructions for the preset."""
    os.makedirs(output_dir, exist_ok=True)

    lines = []

    if preset == 'notebooklm':
        lines.append("# Import Guide — NotebookLM\n")
        lines.append("## Summary\n")
        lines.append(f"- **Total sources:** {len(chunks)} chunks")
        lines.append(f"- **Total words:** {total_words:,}")
        lines.append("- **NotebookLM limit:** 50 sources, 500,000 words/source\n")
        lines.append("## Recommended Upload Order\n")
        lines.append("Upload in the order below for the best Audio Overview result:\n")
        lines.append("| # | File | Words | Module/Section |")
        lines.append("|---|------|-------|----------------|")

        for c in chunks:
            chunk_name = f"docs_chunk_{c.index:02d}.md"
            words_fmt = f"{c.total_words:,}"

            # Derive section from heading_map or directory
            section = ""
            if c.files:
                first_file = c.files[0].relative_path
                if heading_map and first_file in heading_map and heading_map[first_file]:
                    section = heading_map[first_file][0].text
                else:
                    parent = os.path.dirname(first_file)
                    section = parent.split('/')[-1] if parent else os.path.splitext(first_file)[0]

            lines.append(f"| {c.index} | {chunk_name} | {words_fmt} | {section} |")

        lines.append("")
        lines.append("## Tips for Audio Overview\n")
        lines.append("- Upload all chunks before generating the overview.")
        lines.append("- NotebookLM processes better when chunks have similar size.")
        lines.append("- If the overview feels shallow, remove changelog/FAQ chunks")
        lines.append("  and keep only the conceptual ones.")
    else:
        # rag-standard: simple mapping, no tips
        lines.append("# Import Guide\n")
        lines.append("## Summary\n")
        lines.append(f"- **Total sources:** {len(chunks)} chunks")
        lines.append(f"- **Total words:** {total_words:,}")
        lines.append("")
        lines.append("## Chunk Mapping\n")
        lines.append("| # | File | Words | Module/Section |")
        lines.append("|---|------|-------|----------------|")

        for c in chunks:
            chunk_name = f"docs_chunk_{c.index:02d}.md"
            words_fmt = f"{c.total_words:,}"
            section = ""
            if c.files:
                first_file = c.files[0].relative_path
                if heading_map and first_file in heading_map and heading_map[first_file]:
                    section = heading_map[first_file][0].text
                else:
                    parent = os.path.dirname(first_file)
                    section = parent.split('/')[-1] if parent else os.path.splitext(first_file)[0]
            lines.append(f"| {c.index} | {chunk_name} | {words_fmt} | {section} |")

    guide_path = os.path.join(output_dir, "IMPORT_GUIDE.md")
    with open(guide_path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines) + "\n")

    return guide_path


def read_source_text(path: str, no_extract: bool = False) -> str:
    """Read a source file applying the standard extraction policy:
    HTML files go through extract_content (unless no_extract) and then
    strip_html; everything else is returned raw. Reads with
    errors='replace'. Raises on unreadable files — callers choose
    their own failure policy.
    """
    with open(path, 'r', encoding='utf-8', errors='replace') as source_f:
        content = source_f.read()
    if path.lower().endswith(('.html', '.htm')):
        if not no_extract:
            content = extract_content(content)
        content = strip_html(content)
    return content


def _read_source_content(base_dir: str, cf: ChunkFile, no_extract: bool = False, text_overrides: Dict[str, str] = None) -> str:
    """Read a source file from disk, stripping HTML markup if applicable."""
    if text_overrides and cf.relative_path in text_overrides:
        return text_overrides[cf.relative_path]
    true_filepath = os.path.join(base_dir, cf.relative_path)
    try:
        return read_source_text(true_filepath, no_extract=no_extract)
    except Exception as e:
        logger.error(f"Failed to copy contents of {cf.relative_path}: {e}")
        return f"[Excluded unreadable blob: {e}]"


def _group_into_blocks(paragraphs: list) -> list:
    """Group paragraphs into indivisible structural blocks.

    Returns list of strings where each string is either a single
    paragraph or multiple paragraphs joined by ``\\n\\n`` that form
    a structural unit (fenced code block, ``<pre>`` block, contiguous
    list, or markdown table).
    """
    blocks = []
    i = 0
    while i < len(paragraphs):
        para = paragraphs[i]

        # Fenced code block: starts with ```
        if para.lstrip().startswith("```"):
            lines = para.split("\n")
            fence_count = sum(1 for l in lines if l.strip().startswith("```"))
            if fence_count >= 2:
                # Self-contained in one paragraph
                blocks.append(para)
                i += 1
                continue
            # Accumulate until closing fence
            group = [para]
            i += 1
            while i < len(paragraphs):
                group.append(paragraphs[i])
                if paragraphs[i].rstrip().endswith("```") or paragraphs[i].strip() == "```":
                    i += 1
                    break
                i += 1
            blocks.append("\n\n".join(group))
            continue

        # <pre> block without closing </pre>
        if "<pre" in para.lower() and "</pre>" not in para.lower():
            group = [para]
            i += 1
            while i < len(paragraphs):
                group.append(paragraphs[i])
                if "</pre>" in paragraphs[i].lower():
                    i += 1
                    break
                i += 1
            blocks.append("\n\n".join(group))
            continue

        # Contiguous list items
        if re.match(r'^(\s*[-*+]\s|\s*\d+\.\s)', para):
            group = [para]
            i += 1
            while i < len(paragraphs) and re.match(r'^(\s*[-*+]\s|\s*\d+\.\s)', paragraphs[i]):
                group.append(paragraphs[i])
                i += 1
            blocks.append("\n\n".join(group))
            continue

        # Contiguous table rows
        if "|" in para and para.strip().startswith("|"):
            group = [para]
            i += 1
            while i < len(paragraphs) and "|" in paragraphs[i] and paragraphs[i].strip().startswith("|"):
                group.append(paragraphs[i])
                i += 1
            blocks.append("\n\n".join(group))
            continue

        # Regular paragraph
        blocks.append(para)
        i += 1

    return blocks


def _split_text_by_words(text: str, max_words: int) -> list:
    """Split text into sub-chunks respecting structural block boundaries.

    Groups paragraphs into indivisible blocks (code fences, lists, tables,
    ``<pre>`` blocks) before accumulating by word count.  The word limit
    may be slightly exceeded to preserve block integrity.

    Returns list of (text, char_offset) tuples where char_offset is the
    position of the sub-chunk's start in the original text.
    """
    if not text or max_words <= 0:
        return [(text or "", 0)]

    paragraphs = text.split("\n\n")
    blocks = _group_into_blocks(paragraphs)

    result = []
    current_parts = []
    current_words = 0
    char_pos = 0
    chunk_start = 0

    for idx, block in enumerate(blocks):
        block_words = len(block.split())

        if current_words + block_words > max_words and current_parts:
            result.append(("\n\n".join(current_parts), chunk_start))
            chunk_start = char_pos
            current_parts = []
            current_words = 0

        current_parts.append(block)
        current_words += block_words
        char_pos += len(block)
        if idx < len(blocks) - 1:
            char_pos += 2  # \n\n separator

    if current_parts:
        result.append(("\n\n".join(current_parts), chunk_start))

    return result if result else [("", 0)]


def _write_file_with_context(f, cf: ChunkFile, content: str, headings: list, max_words: int, url_map: Dict[str, str] = None, readiness_map: Dict[str, dict] = None, chunk_id: str = ""):
    """Write a file's content with per-sub-chunk context headers.

    Splits the content at paragraph boundaries respecting max_words,
    computes the active heading hierarchy for each sub-chunk, and
    writes the context header before each piece.
    """
    from ..utils.heading_extractor import get_active_headings, format_context_header

    if headings and max_words > 0:
        sub_chunks = _split_text_by_words(content, max_words)
    else:
        sub_chunks = [(content, 0)]

    total_sub = len(sub_chunks)
    for j, (sub_text, char_offset) in enumerate(sub_chunks):
        if j > 0:
            f.write("\n\n")
        active = get_active_headings(headings, char_offset) if headings else []
        # For the first sub-chunk, if no headings found at offset 0 (due to
        # leading whitespace), look ahead to the first heading's position
        if not active and headings and j == 0:
            active = get_active_headings(headings, headings[0].char_offset)
        word_count = len(sub_text.split())
        header = format_context_header(
            active_headings=active,
            source_path=cf.relative_path,
            chunk_index=j + 1,
            total_chunks=total_sub,
            word_count=word_count,
            url=url_map.get(cf.relative_path, "") if url_map else "",
            readiness=readiness_map.get(chunk_id) if readiness_map and chunk_id else None,
        )
        f.write(header)
        f.write(sub_text)


def _write_chunk_text(chunk: Chunk, base_dir: str, out_filepath: str, with_index: bool, total_chunks: int, no_extract: bool = False, text_overrides: Dict[str, str] = None, heading_map: Dict = None, max_words: int = 0, url_map: Dict[str, str] = None, readiness_map: Dict[str, dict] = None, prefix: str = "docs_chunk_"):
    """Write a chunk as plain text (no markdown or HTML markup)."""
    with open(out_filepath, 'w', encoding='utf-8') as f:
        if with_index:
            f.write(f"Chunk {chunk.index:02d} of {total_chunks:02d}\n")
            f.write(f"Files in this chunk ({len(chunk.files)} files, ~{chunk.total_words} words):\n")
            for cf in chunk.files:
                f.write(f"- {cf.relative_path} ({cf.word_count} words)\n")
            f.write("\n" + ("=" * 60) + "\n\n")

        for i, cf in enumerate(chunk.files):
            if i > 0:
                f.write("\n\n")
            content = _read_source_content(base_dir, cf, no_extract=no_extract, text_overrides=text_overrides)

            if heading_map is not None and cf.relative_path in heading_map:
                chunk_id = f"{prefix}{chunk.index:02d}"
                _write_file_with_context(f, cf, content, heading_map[cf.relative_path], max_words, url_map=url_map, readiness_map=readiness_map, chunk_id=chunk_id)
            else:
                f.write(f"=== SOURCE: {cf.relative_path} ===\n\n")
                f.write(content)


def _write_chunk_markdown(chunk: Chunk, base_dir: str, out_filepath: str, with_index: bool, total_chunks: int, no_extract: bool = False, text_overrides: Dict[str, str] = None, heading_map: Dict = None, max_words: int = 0, url_map: Dict[str, str] = None, readiness_map: Dict[str, dict] = None, prefix: str = "docs_chunk_"):
    with open(out_filepath, 'w', encoding='utf-8') as f:
        if with_index:
            f.write(f"# Chunk {chunk.index:02d} of {total_chunks:02d}\n\n")
            f.write(f"## Files in this chunk ({len(chunk.files)} files, ~{chunk.total_words} words):\n")
            for cf in chunk.files:
                f.write(f"- {cf.relative_path} ({cf.word_count} words)\n")
            f.write("\n---\n\n")

        for i, cf in enumerate(chunk.files):
            if i > 0:
                f.write("\n\n")
            content = _read_source_content(base_dir, cf, no_extract=no_extract, text_overrides=text_overrides)

            if heading_map is not None and cf.relative_path in heading_map:
                chunk_id = f"{prefix}{chunk.index:02d}"
                _write_file_with_context(f, cf, content, heading_map[cf.relative_path], max_words, url_map=url_map, readiness_map=readiness_map, chunk_id=chunk_id)
            else:
                f.write(f"<!-- SOURCE: {cf.relative_path} -->\n\n")
                f.write(content)

def _write_chunk_jsonl(chunk: Chunk, base_dir: str, out_filepath: str,
                       with_index: bool, total_chunks: int,
                       no_extract: bool = False,
                       text_overrides: Dict[str, str] = None,
                       heading_map: Dict = None,
                       max_words: int = 0,
                       url_map: Dict[str, str] = None,
                       readiness_map: Dict[str, dict] = None,
                       prefix: str = "docs_chunk_"):
    """Write a chunk as a JSONL file (one JSON line per source file/sub-chunk)."""
    import json

    lines = []

    for cf in chunk.files:
        content = _read_source_content(base_dir, cf, no_extract=no_extract,
                                       text_overrides=text_overrides)

        if heading_map is not None and cf.relative_path in heading_map:
            from ..utils.heading_extractor import get_active_headings
            headings = heading_map[cf.relative_path]
            if headings and max_words > 0:
                sub_chunks = _split_text_by_words(content, max_words)
            else:
                sub_chunks = [(content, 0)]

            total_sub = len(sub_chunks)
            for j, (sub_text, char_offset) in enumerate(sub_chunks):
                active = get_active_headings(headings, char_offset) if headings else []
                if not active and headings and j == 0:
                    active = get_active_headings(headings, headings[0].char_offset)

                record = {
                    "id": f"{chunk.index:02d}_{cf.relative_path}",
                    "source": cf.relative_path,
                    "words": len(sub_text.split()),
                    "content": sub_text,
                    "schema_version": "v1",
                }
                if active:
                    record["breadcrumb"] = [h.text for h in active]
                if total_sub > 1:
                    record["chunk_index"] = j + 1
                    record["total_chunks"] = total_sub
                    record["id"] = f"{chunk.index:02d}_{j+1}_{cf.relative_path}"
                if url_map and cf.relative_path in url_map:
                    record["url"] = url_map[cf.relative_path]
                if readiness_map:
                    chunk_id = f"{prefix}{chunk.index:02d}"
                    if chunk_id in readiness_map:
                        record["readiness_grade"] = readiness_map[chunk_id]["grade"]

                lines.append(json.dumps(record, ensure_ascii=False))
        else:
            record = {
                "id": f"{chunk.index:02d}_{cf.relative_path}",
                "source": cf.relative_path,
                "words": len(content.split()),
                "content": content,
                "schema_version": "v1",
            }
            if url_map and cf.relative_path in url_map:
                record["url"] = url_map[cf.relative_path]
            lines.append(json.dumps(record, ensure_ascii=False))

    with open(out_filepath, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines) + "\n")


def write_chunks(chunks: List[Chunk], base_dir: str, output_dir: str, prefix: str, format: str, with_index: bool, total_chunks: int, no_extract: bool = False, text_overrides: Dict[str, str] = None, heading_map: Dict = None, max_words: int = 0, url_map: Dict[str, str] = None, readiness_map: Dict[str, dict] = None) -> List[str]:
    """Flush chunk classes out as disk files with or without headings."""
    os.makedirs(output_dir, exist_ok=True)
    generated_paths = []

    fmt = format.lower()
    for chunk in chunks:
        out_filename = f"{prefix}{chunk.index:02d}.{format}"
        out_filepath = os.path.join(output_dir, out_filename)
        generated_paths.append(out_filepath)

        if fmt == "xml":
            raise ValueError(
                "XML format is deprecated. Use 'md' (default) or 'jsonl'."
            )
        elif fmt == "jsonl":
            _write_chunk_jsonl(chunk, base_dir, out_filepath, with_index, total_chunks, no_extract=no_extract, text_overrides=text_overrides, heading_map=heading_map, max_words=max_words, url_map=url_map, readiness_map=readiness_map, prefix=prefix)
        elif fmt == "txt":
            _write_chunk_text(chunk, base_dir, out_filepath, with_index, total_chunks, no_extract=no_extract, text_overrides=text_overrides, heading_map=heading_map, max_words=max_words, url_map=url_map, readiness_map=readiness_map, prefix=prefix)
        else:
            _write_chunk_markdown(chunk, base_dir, out_filepath, with_index, total_chunks, no_extract=no_extract, text_overrides=text_overrides, heading_map=heading_map, max_words=max_words, url_map=url_map, readiness_map=readiness_map, prefix=prefix)

    return generated_paths
