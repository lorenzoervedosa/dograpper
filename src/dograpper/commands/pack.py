"""Pack subcommand."""

import os
import json
import click
import logging
from datetime import datetime, timezone

from ..lib.config_loader import load_config
from ..lib.ignore_parser import filter_files
from ..lib.chunker import chunk_by_size, chunk_by_semantic, write_chunks, read_source_text

logger = logging.getLogger(__name__)

@click.command(
    epilog=(
        "\b\n"
        "Examples:\n"
        "  dograpper pack ./docs -o ./chunks\n"
        "  dograpper pack ./docs -o ./chunks --strategy semantic --max-words-per-chunk 300000\n"
        "  dograpper pack ./docs -o ./chunks --bundle notebooklm --context-header --score\n"
        "  dograpper pack ./docs -o ./chunks --format jsonl --cross-refs --score\n"
    )
)
@click.argument('input_dir', type=click.Path(exists=True, file_okay=False, dir_okay=True), required=True)
@click.option('--output', '-o', required=True, type=click.Path(),
              help="Directory where chunks will be saved")
@click.option('--max-words-per-chunk', type=int, default=500000, show_default=True,
              help="Word limit per chunk (NotebookLM per-source ceiling)")
@click.option('--max-chunks', type=int, default=50, show_default=True,
              help="Total chunk limit (per-notebook source ceiling)")
@click.option('--strategy', type=click.Choice(['size', 'semantic']), default='size', show_default=True,
              help="size: pack by word count. semantic: group by directory first")
@click.option('--ignore-file', type=click.Path(), default='./.docsignore', show_default=True,
              help="Exclusion file with gitignore syntax")
@click.option('--ignore', multiple=True, type=str, default=[],
              help="Inline exclusion pattern (repeatable): --ignore '*.png' --ignore '**/404.html'")
@click.option('--prefix', type=str, default="docs_chunk_", show_default=True,
              help="Prefix for generated files")
@click.option('--with-index/--no-index', default=True, show_default=True,
              help="Include a file summary in the header of each chunk")
@click.option('--format', type=click.Choice(['txt', 'md', 'jsonl', 'xml']), default='md', show_default=True,
              help="Chunk output format. 'xml' is deprecated.")
@click.option('--no-extract', is_flag=True, default=False,
              help="Disable smart content extraction. Use the whole HTML as in the previous behavior.")
@click.option('--show-tokens', is_flag=True, default=False,
              help="Show per-chunk and total token count in the final summary.")
@click.option('--token-encoding', type=str, default="cl100k", show_default=True,
              help="Tokenizer encoding (cl100k, o200k, p50k). Requires --show-tokens.")
@click.option('--dry-run', is_flag=True, default=False,
              help="Simulate the pack without writing files. Prints compression report and chunk projection.")
@click.option('--dedup', type=click.Choice(['off', 'exact', 'fuzzy', 'both'], case_sensitive=False),
              default='off', show_default=True,
              help="Cross-file block deduplication. "
                   "'exact' removes identical blocks, 'fuzzy' removes near-identical ones, "
                   "'both' applies both.")
@click.option('--dedup-threshold', type=int, default=3, show_default=True,
              help="Maximum Hamming distance for fuzzy dedup (0-10). Lower = more conservative.")
@click.option('--context-header', is_flag=True, default=False,
              help="Inject a context header (source, heading breadcrumb) "
                   "at the top of each file within the chunk to improve LLM ingestion.")
@click.option('--cross-refs', is_flag=True, default=False,
              help="Generate cross_refs.json with cross-references between chunks "
                   "and annotate chunk text with [-> chunk_id] pointers.")
@click.option('--delta', is_flag=True, default=False,
              help="Reprocess only files changed since the last pack.")
@click.option('--manifest', type=str, default=".dograpper-manifest.json",
              show_default=True,
              help="Download manifest used for delta comparison.")
@click.option('--bundle', type=click.Choice(['notebooklm', 'rag-standard']),
              default=None,
              help="Optimized packaging preset. "
                   "'notebooklm': ≤50 balanced chunks. "
                   "'rag-standard': no special restrictions.")
@click.option('--score', is_flag=True, default=False,
              help="Compute LLM Readiness Score per chunk. "
                   "Generates llm-readiness.json in the output.")
@click.option('--for-queries', type=click.Path(), default=None,
              help="Text file with one expected query per line. Reorders "
                   "files by BM25 query affinity before chunking so content "
                   "answering the same query is co-located. Requires "
                   "--strategy size.")
@click.pass_context
def pack(ctx: click.Context, input_dir: str, output: str, max_words_per_chunk: int, max_chunks: int, strategy: str, ignore_file: str, ignore: tuple, prefix: str, with_index: bool, format: str, no_extract: bool, show_tokens: bool, token_encoding: str, dry_run: bool, dedup: str, dedup_threshold: int, context_header: bool, cross_refs: bool, delta: bool, manifest: str, bundle: str, score: bool, for_queries: str):
    """Process and group files into chunks optimized for LLM ingestion.

    Walks INPUT_DIR, extracts main content, removes boilerplate and
    duplication, scores quality, and generates structured chunks with
    context metadata in the dograpper-context-v1 format.

    \b
    Grouping strategies:
      size      Pack by pure word count, alphabetical order.
      semantic  Group by directory, preserving thematic cohesion.

    \b
    Packaging presets (--bundle):
      notebooklm    ≤50 balanced chunks + IMPORT_GUIDE.md
      rag-standard  No restrictions, with mapping guide

    If a single file exceeds `--max-words-per-chunk`, it is placed alone
    in its own chunk and a warning is emitted (the CLI does not fail).
    """
    
    ctx.ensure_object(dict)
    config_path = ctx.obj.get('CONFIG_PATH', '.dograpper.json')
    
    cli_params = {
        'output': output,
        'max_words_per_chunk': max_words_per_chunk,
        'max_chunks': max_chunks,
        'strategy': strategy,
        'ignore_file': ignore_file,
        'ignore': ignore,
        'prefix': prefix,
        'with_index': with_index,
        'format': format,
        'no_extract': no_extract,
        'show_tokens': show_tokens,
        'token_encoding': token_encoding,
        'dry_run': dry_run,
        'dedup': dedup,
        'dedup_threshold': dedup_threshold,
        'context_header': context_header,
        'cross_refs': cross_refs,
        'delta': delta,
        'manifest': manifest,
        'bundle': bundle,
        'score': score,
        'for_queries': for_queries,
    }
    
    merged_params = load_config(config_path, 'pack', cli_params, ctx)
    
    output_dir = merged_params.get('output', output)
    max_w = merged_params.get('max_words_per_chunk', max_words_per_chunk)
    max_c = merged_params.get('max_chunks', max_chunks)
    strat = merged_params.get('strategy', strategy)
    ign_file = merged_params.get('ignore_file', ignore_file)
    ign_inline = list(merged_params.get('ignore', ignore))
    pref = merged_params.get('prefix', prefix)
    w_index = merged_params.get('with_index', with_index)
    fmt = merged_params.get('format', format)
    no_ext = merged_params.get('no_extract', no_extract)
    s_tokens = merged_params.get('show_tokens', show_tokens)
    t_encoding = merged_params.get('token_encoding', token_encoding)
    is_dry_run = merged_params.get('dry_run', dry_run)
    dedup_mode = merged_params.get('dedup', dedup)
    dedup_thresh = merged_params.get('dedup_threshold', dedup_threshold)
    ctx_header = merged_params.get('context_header', context_header)
    do_cross_refs = merged_params.get('cross_refs', cross_refs)
    is_delta = merged_params.get('delta', delta)
    manifest_path = merged_params.get('manifest', manifest)
    bundle_preset = merged_params.get('bundle', bundle)
    is_score = merged_params.get('score', score)
    for_queries_path = merged_params.get('for_queries', for_queries)

    # 2b. Bundle overrides
    if bundle_preset == 'notebooklm':
        max_c = min(max_c, 50)
        if max_w > 500000:
            max_w = 500000
        logger.info(f"[bundle:notebooklm] max_chunks={max_c}, max_words={max_w}")

    # 2c. Deprecate XML format
    if fmt == 'xml':
        raise click.ClickException(
            "XML format is deprecated since v1.x. Use 'md' (default) or 'jsonl'."
        )

    # 2d. Query-oriented packing: load queries early (fail fast, no silent fallback)
    query_list = None
    if for_queries_path:
        if strat == 'semantic':
            click.echo("Error: --for-queries requires --strategy size "
                       "(semantic grouping and query grouping are mutually "
                       "exclusive).", err=True)
            ctx.exit(1)
        from ..lib.query_packer import load_queries
        try:
            query_list = load_queries(for_queries_path)
        except OSError as e:
            click.echo(f"Error: cannot read queries file "
                       f"'{for_queries_path}': {e}", err=True)
            ctx.exit(1)
        if not query_list:
            click.echo(f"Error: queries file '{for_queries_path}' "
                       f"contains no queries.", err=True)
            ctx.exit(1)

    # 3. List all files
    # The queries file drives the ordering; it is never corpus content,
    # even when it lives inside INPUT_DIR.
    queries_realpath = os.path.realpath(for_queries_path) if for_queries_path else None
    all_files = []
    for root, _, files in os.walk(input_dir):
        for f in files:
            fpath = os.path.join(root, f)
            if queries_realpath and os.path.realpath(fpath) == queries_realpath:
                continue
            all_files.append(fpath)
            
    # 4. Check empty
    if not all_files:
        raise click.ClickException(f"No files found in {input_dir}. Did you run `download` first?")
        
    # 5. Filter
    filtered_paths = filter_files(all_files, ign_file, ign_inline, input_dir)
    
    # 6. Check empty after filter
    if not filtered_paths:
        raise click.ClickException("All files were excluded by ignore rules. Check your .docsignore or --ignore flags.")

    # 6b. Delta filtering (opt-in, after filter, before dedup)
    diff = None
    if is_delta:
        from ..lib.manifest import load_manifest, build_manifest, diff_manifests

        old_manifest = load_manifest(manifest_path)
        current_manifest = build_manifest(base_url="", output_dir=input_dir)
        diff = diff_manifests(old_manifest, current_manifest)

        delta_files = set(diff.added + diff.modified)
        pre_count = len(filtered_paths)

        filtered_paths = [
            f for f in filtered_paths
            if os.path.relpath(f, input_dir).replace(os.sep, '/') in delta_files
        ]

        logger.info(f"[delta] {pre_count} files → {len(filtered_paths)} changed "
                     f"({len(diff.added)} added, {len(diff.modified)} modified, "
                     f"{len(diff.removed)} removed)")

        if not filtered_paths:
            click.echo("Delta: no files changed since last pack. Nothing to do.")
            return

    # 7. Deduplication (opt-in, before chunking)
    dedup_stats = None
    dedup_word_counts = None
    dedup_text_overrides = None
    processed_texts = None

    if dedup_mode != "off":
        from ..utils.dedup import deduplicate

        processed_texts = {}
        for fpath in filtered_paths:
            rel = os.path.relpath(fpath, input_dir).replace(os.sep, '/')
            try:
                processed_texts[rel] = read_source_text(fpath, no_extract=no_ext)
            except Exception:
                continue

        dedup_result = deduplicate(processed_texts, mode=dedup_mode, hamming_threshold=dedup_thresh)
        dedup_stats = dedup_result.stats
        dedup_word_counts = {rp: len(t.split()) for rp, t in dedup_result.texts.items()}
        dedup_text_overrides = dedup_result.texts

    # 7b. Extract headings for context-header or scoring (opt-in, before chunking)
    heading_map = None
    if ctx_header or is_score:
        from ..utils.heading_extractor import extract_with_headings
        from ..utils.content_extractor import extract_content as _extract_ctx

        heading_map = {}
        # Initialize text_overrides if not already set by dedup, so the writer
        # uses the same text from which heading offsets were calculated.
        if dedup_text_overrides is None:
            dedup_text_overrides = {}

        for fpath in filtered_paths:
            rel = os.path.relpath(fpath, input_dir).replace(os.sep, '/')
            if fpath.lower().endswith(('.html', '.htm')):
                try:
                    with open(fpath, 'r', encoding='utf-8', errors='replace') as fh:
                        raw = fh.read()
                    if not no_ext:
                        raw = _extract_ctx(raw)
                    doc = extract_with_headings(raw, source_path=rel)
                    heading_map[rel] = doc.headings
                    # Use doc.text for consistent offsets (only if dedup didn't override)
                    if rel not in dedup_text_overrides:
                        dedup_text_overrides[rel] = doc.text
                    logger.debug(f"[context] {rel}: {len(doc.headings)} headings extracted")
                except Exception:
                    heading_map[rel] = []
            else:
                heading_map[rel] = []

    # 7c. Build url_map from manifest (for context-header URLs)
    url_map = None
    if ctx_header:
        try:
            from ..lib.manifest import load_manifest
            manifest_data = load_manifest(manifest_path)
            if manifest_data and manifest_data.files:
                url_map = {}
                for fpath in filtered_paths:
                    rel = os.path.relpath(fpath, input_dir).replace(os.sep, '/')
                    for key, entry in manifest_data.files.items():
                        local = entry.local_path or key
                        if local == rel or key == rel:
                            url_map[rel] = entry.url
                            break
        except Exception:
            pass

    # 7d. Query-oriented ordering (opt-in, after delta/dedup, before chunking)
    query_pack_result = None
    if query_list is not None:
        from ..lib.query_packer import order_files_by_queries

        rel_map = {os.path.relpath(f, input_dir).replace(os.sep, '/'): f
                   for f in filtered_paths}
        if processed_texts is not None:
            # Reuse the extraction pass the dedup step already did.
            query_texts = processed_texts
        else:
            query_texts = {}
            for rel, fpath in rel_map.items():
                try:
                    query_texts[rel] = read_source_text(fpath, no_extract=no_ext)
                except Exception:
                    continue

        query_pack_result = order_files_by_queries(
            list(rel_map.keys()), query_texts, query_list)
        for assignment in query_pack_result.assignments:
            if assignment.total_hits == 0:
                click.echo(f"Warning: query matched no files: "
                           f"'{assignment.query}'", err=True)
        filtered_paths = [rel_map[rp] for rp in query_pack_result.ordered_paths]

    # 8. Execute chunking
    if strat == 'semantic':
        chunks = chunk_by_semantic(filtered_paths, input_dir, max_w, no_extract=no_ext, word_counts=dedup_word_counts)
    else:
        chunks = chunk_by_size(filtered_paths, input_dir, max_w, no_extract=no_ext, word_counts=dedup_word_counts, preserve_order=query_pack_result is not None)

    # 8b. Bundle balancing (post-process)
    if bundle_preset == 'notebooklm':
        from ..lib.chunker import balance_chunks
        chunks = balance_chunks(chunks, target_chunks=max_c, max_words=max_w)

    generated_chunk_count = len(chunks)

    # 9. Validate against max
    if generated_chunk_count > max_c:
        logger.warning(f"Generated {generated_chunk_count} chunks, exceeding max-chunks limit of {max_c}. Consider increasing --max-words-per-chunk or adding --ignore rules.")

    # 9b. Dry-run: generate report and exit without writing
    if is_dry_run:
        from ..utils.html_stripper import strip_html
        from ..utils.content_extractor import extract_content
        from ..utils.dry_run_report import DryRunData, FileStats, generate_report

        file_stats = []
        for fpath in filtered_paths:
            try:
                with open(fpath, 'r', encoding='utf-8', errors='replace') as fh:
                    raw = fh.read()
            except Exception:
                continue

            rel = os.path.relpath(fpath, input_dir).replace(os.sep, '/')
            is_html_file = fpath.lower().endswith(('.html', '.htm'))

            if is_html_file:
                text_before = strip_html(raw)
                if not no_ext:
                    text_after = strip_html(extract_content(raw))
                else:
                    text_after = text_before
            else:
                text_before = raw
                text_after = raw

            words_before = len(text_before.split())
            words_after = len(text_after.split())

            # Use post-dedup word count if available
            words_after_dedup = None
            if dedup_word_counts and rel in dedup_word_counts:
                words_after_dedup = dedup_word_counts[rel]

            tokens = None
            if s_tokens:
                from ..utils.token_counter import count_tokens
                token_text = dedup_text_overrides[rel] if dedup_text_overrides and rel in dedup_text_overrides else text_after
                tokens = count_tokens(token_text, encoding=t_encoding).tokens

            file_stats.append(FileStats(
                filepath=rel,
                words_before_extraction=words_before,
                words_after_extraction=words_after,
                tokens=tokens,
                words_after_dedup=words_after_dedup,
            ))

        # Use post-dedup word counts for oversize check when available
        def _effective_words(fs):
            return fs.words_after_dedup if fs.words_after_dedup is not None else fs.words_after_extraction

        oversize = sum(1 for fs in file_stats if _effective_words(fs) > max_w)

        report_data = DryRunData(
            total_files_found=len(all_files),
            total_files_excluded=len(all_files) - len(filtered_paths),
            file_stats=file_stats,
            projected_chunks=generated_chunk_count,
            max_chunks=max_c,
            max_words_per_chunk=max_w,
            strategy=strat,
            show_tokens=s_tokens,
            token_encoding=t_encoding,
            oversize_files=oversize,
            dedup_stats=dedup_stats,
        )

        if is_score:
            from ..utils.scorer import score_chunk as _dr_score_chunk

            dr_scores = []
            for chunk in chunks:
                chunk_id = f"{pref}{chunk.index:02d}"
                raw_total = 0
                extracted_total = 0
                headings_count = 0
                max_heading_level = 0

                for cf in chunk.files:
                    matching = [fs for fs in file_stats if fs.filepath == cf.relative_path]
                    if matching:
                        raw_total += matching[0].words_before_extraction
                        extracted_total += matching[0].words_after_extraction

                    if heading_map and cf.relative_path in heading_map:
                        hdgs = heading_map[cf.relative_path]
                        headings_count += len(hdgs)
                        if hdgs:
                            max_heading_level = max(max_heading_level, max(h.level for h in hdgs))

                cs = _dr_score_chunk(
                    chunk_id=chunk_id,
                    text="",  # no final text in dry-run
                    raw_words=raw_total,
                    extracted_words=extracted_total,
                    headings_count=headings_count,
                    max_heading_level=max_heading_level,
                )
                # In dry-run, boundary can't be checked — force True
                cs.boundary_integrity = True
                dr_scores.append(cs)

            report_data.readiness_scores = dr_scores
            report_data.show_score = True

        click.echo(generate_report(report_data))
        return

    # 9c. LLM Readiness scoring (before write, so readiness can be injected into headers)
    readiness_scores = []
    readiness_map = None
    if is_score:
        from ..utils.scorer import score_chunk
        from ..utils.html_stripper import strip_html as _score_strip
        from ..utils.content_extractor import extract_content as _score_extract

        for chunk in chunks:
            chunk_id = f"{pref}{chunk.index:02d}"

            raw_total = 0
            extracted_total = 0
            headings_count = 0
            max_heading_level = 0
            chunk_text_parts = []

            for cf in chunk.files:
                fpath = os.path.join(input_dir, cf.relative_path)
                if fpath.lower().endswith(('.html', '.htm')):
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='replace') as fh:
                            raw_html = fh.read()
                        raw_total += len(_score_strip(raw_html).split())
                        if not no_ext:
                            extracted_total += len(_score_strip(_score_extract(raw_html)).split())
                        else:
                            extracted_total += len(_score_strip(raw_html).split())
                    except Exception:
                        pass
                else:
                    try:
                        wc = len(open(fpath, 'r', encoding='utf-8', errors='replace').read().split())
                        raw_total += wc
                        extracted_total += wc
                    except Exception:
                        pass

                if heading_map and cf.relative_path in heading_map:
                    hdgs = heading_map[cf.relative_path]
                    headings_count += len(hdgs)
                    if hdgs:
                        max_heading_level = max(max_heading_level, max(h.level for h in hdgs))

                # Read content for boundary check
                if dedup_text_overrides and cf.relative_path in dedup_text_overrides:
                    chunk_text_parts.append(dedup_text_overrides[cf.relative_path])
                else:
                    try:
                        with open(fpath, 'r', encoding='utf-8', errors='replace') as fh:
                            raw = fh.read()
                        if fpath.lower().endswith(('.html', '.htm')):
                            if not no_ext:
                                raw = _score_extract(raw)
                            raw = _score_strip(raw)
                        chunk_text_parts.append(raw)
                    except Exception:
                        pass

            chunk_text = "\n\n".join(chunk_text_parts)

            cs = score_chunk(
                chunk_id=chunk_id,
                text=chunk_text,
                raw_words=raw_total,
                extracted_words=extracted_total,
                headings_count=headings_count,
                max_heading_level=max_heading_level,
            )
            readiness_scores.append(cs)

        # Build readiness_map for header injection (md/txt) and JSONL grade
        if ctx_header or fmt == 'jsonl':
            readiness_map = {
                s.chunk_id: {
                    "score": round(s.score, 2),
                    "grade": s.grade,
                    "noise_ratio": round(s.noise_ratio, 3),
                }
                for s in readiness_scores
            }

    # 10. Write outputs
    write_chunks(chunks, input_dir, output_dir, pref, fmt, w_index, generated_chunk_count, no_extract=no_ext, text_overrides=dedup_text_overrides, heading_map=heading_map, max_words=max_w, url_map=url_map, readiness_map=readiness_map)

    # 10a. Cross-references (opt-in, after write)
    cross_ref_total = 0
    cross_ref_unresolved = 0
    if do_cross_refs:
        import json as _json
        from ..utils.link_extractor import extract_links, build_cross_ref_index, annotate_cross_refs

        # Build file_to_chunk map (with normalized variants for index.html)
        file_to_chunk = {}
        for chunk in chunks:
            chunk_id = f"{pref}{chunk.index:02d}"
            for cf in chunk.files:
                file_to_chunk[cf.relative_path] = chunk_id
                # Also register normalized path (without /index.html suffix)
                # so that links resolved by extract_links can match
                rp = cf.relative_path
                if rp.endswith("/index.html"):
                    file_to_chunk[rp[:-len("/index.html")]] = chunk_id
                elif rp == "index.html":
                    file_to_chunk[""] = chunk_id

        # Extract links from all HTML files
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
            file_links = extract_links(raw_html, rel)
            all_links.extend(file_links)

        # Build index and write JSON
        cross_index = build_cross_ref_index(all_links, file_to_chunk)
        cross_ref_total = sum(
            len(entry.get("links", []))
            for key, entry in cross_index.items()
            if key != "unresolved"
        )
        cross_ref_unresolved = len(cross_index.get("unresolved", []))

        cross_refs_path = os.path.join(output_dir, "cross_refs.json")
        with open(cross_refs_path, 'w', encoding='utf-8') as jf:
            _json.dump(cross_index, jf, indent=2, ensure_ascii=False)

        # Annotate written chunk files
        for chunk in chunks:
            chunk_id = f"{pref}{chunk.index:02d}"
            chunk_filename = f"{chunk_id}.{fmt}"
            chunk_filepath = os.path.join(output_dir, chunk_filename)
            # Collect links whose source files are in this chunk
            chunk_links = [
                lnk for lnk in all_links
                if file_to_chunk.get(lnk.source_path) == chunk_id
            ]
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

    # 10b. Delta manifest (opt-in, after write)
    if is_delta and diff is not None:
        delta_info = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "added": diff.added,
            "modified": diff.modified,
            "removed": diff.removed,
            "chunks_generated": [
                {
                    "chunk": f"{pref}{c.index:02d}",
                    "files": [cf.relative_path for cf in c.files]
                }
                for c in chunks
            ],
        }
        delta_path = os.path.join(output_dir, "delta_manifest.json")
        with open(delta_path, 'w', encoding='utf-8') as df:
            json.dump(delta_info, df, indent=2)

    # 10c. Import guide (opt-in, for bundle presets)
    guide_path = None
    if bundle_preset is not None:
        from ..lib.chunker import generate_import_guide
        total_words_for_guide = sum(c.total_words for c in chunks)
        guide_path = generate_import_guide(
            chunks, output_dir, bundle_preset, total_words_for_guide,
            heading_map=heading_map
        )

    # 10d. LLM Readiness — write JSON (scoring already done in step 9c)
    if is_score and readiness_scores:
        readiness_path = os.path.join(output_dir, "llm-readiness.json")
        readiness_data = {
            "summary": {
                "total_chunks": len(readiness_scores),
                "avg_score": round(sum(s.score for s in readiness_scores) / len(readiness_scores), 2) if readiness_scores else 0,
                "grades": {
                    "A": sum(1 for s in readiness_scores if s.grade == "A"),
                    "B": sum(1 for s in readiness_scores if s.grade == "B"),
                    "C": sum(1 for s in readiness_scores if s.grade == "C"),
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
                for s in readiness_scores
            ],
        }
        with open(readiness_path, 'w', encoding='utf-8') as rf:
            json.dump(readiness_data, rf, indent=2)

    # 10e. Token counting (opt-in)
    token_counts = []
    if s_tokens:
        from ..utils.token_counter import count_tokens, format_token_summary

        for chunk in chunks:
            # Read the written chunk file to count tokens on the final output
            chunk_filename = f"{pref}{chunk.index:02d}.{fmt}"
            chunk_filepath = os.path.join(output_dir, chunk_filename)
            try:
                with open(chunk_filepath, 'r', encoding='utf-8', errors='replace') as cf:
                    chunk_text = cf.read()
                tc = count_tokens(chunk_text, encoding=t_encoding)
                token_counts.append(tc)
                logger.debug(f"[tokens] {chunk_filename}: {tc.words} words → {tc.tokens} tokens ({tc.encoding})")
            except Exception as e:
                logger.warning(f"Failed to count tokens for {chunk_filename}: {e}")

    # 11. Summary footprint calculation
    files_processed = sum(len(c.files) for c in chunks)
    files_excluded = len(all_files) - len(filtered_paths)
    total_words = sum(c.total_words for c in chunks)
    
    if generated_chunk_count > 0:
        avg_w = total_words / generated_chunk_count
        min_w = min(c.total_words for c in chunks)
        max_w_actual = max(c.total_words for c in chunks)
    else:
        avg_w = min_w = max_w_actual = 0
        
    # Formatting the summary outputs
    click.echo("\nPack complete:")
    click.echo(f"  Files processed: {files_processed}")
    click.echo(f"  Files excluded:  {files_excluded}")
    click.echo(f"  Chunks generated: {generated_chunk_count} / {max_c} (max)")
    
    if generated_chunk_count > 0:
         click.echo(f"  Words per chunk:  ~{avg_w:,.0f} avg (min: {min_w:,}, max: {max_w_actual:,})")
    else:
         click.echo("  Words per chunk:  0")

    click.echo(f"  Total words:     {total_words:,}")

    if dedup_stats is not None:
        click.echo(f"  Dedup mode:        {dedup_mode}")
        click.echo(f"  Blocks analyzed:   {dedup_stats.total_blocks}")
        click.echo(f"  Blocks removed:    {dedup_stats.blocks_removed} ({dedup_stats.blocks_removed_exact} exact + {dedup_stats.blocks_removed_fuzzy} fuzzy)")
        if total_words + dedup_stats.words_removed > 0:
            pct = dedup_stats.words_removed * 100 // (total_words + dedup_stats.words_removed)
        else:
            pct = 0
        click.echo(f"  Words removed:     {dedup_stats.words_removed:,} (~{pct}%)")

    if query_pack_result is not None:
        click.echo(f"  Query packing:   {len(query_list)} queries, "
                   f"{query_pack_result.matched_count} files matched, "
                   f"{len(query_pack_result.unmatched_files)} unmatched")

    if is_delta and diff is not None:
        click.echo(f"  Delta:           {len(diff.added)} added, {len(diff.modified)} modified, {len(diff.removed)} removed")
        click.echo(f"  Delta manifest:  {os.path.join(output_dir, 'delta_manifest.json')}")

    if guide_path is not None:
        click.echo(f"  Import guide:    {guide_path}")

    click.echo(f"  Output:          {output_dir}/")

    if readiness_scores:
        readiness_path = os.path.join(output_dir, "llm-readiness.json")
        grade_counts = {"A": 0, "B": 0, "C": 0}
        for s in readiness_scores:
            grade_counts[s.grade] += 1
        avg_score = sum(s.score for s in readiness_scores) / len(readiness_scores)
        click.echo(f"  LLM Readiness:   {readiness_path}")
        click.echo(f"                   {grade_counts['A']}x A, {grade_counts['B']}x B, {grade_counts['C']}x C "
                   f"(avg: {avg_score:.2f})")

    if do_cross_refs:
        click.echo(f"  Cross-refs:        {output_dir}/cross_refs.json ({cross_ref_total} links, {cross_ref_unresolved} unresolved)")

    if token_counts:
        from ..utils.token_counter import format_token_summary
        click.echo(format_token_summary(token_counts))
    
    # Warnings at bottom
    oversized = [c for c in chunks if c.total_words > max_w]
    if oversized:
        plural = "s" if len(oversized) > 1 else ""
        click.echo(f"  \u26a0 {len(oversized)} chunk{plural} exceeds the word limit")
        
    if generated_chunk_count > max_c:
        click.echo(f"  \u26a0 Chunk count exceeds max-chunks limit ({generated_chunk_count} > {max_c})")
