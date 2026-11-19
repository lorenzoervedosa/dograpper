# `src/dograpper/lib/`

Pipeline: chunking, config, manifest, descoberta (llms.txt, sitemap), wget, Playwright, retrieval, eval, layout por página. Contratos, gates e fluxo de sessão: `CLAUDE.md` da raiz.

## Módulos

```
src/dograpper/lib/
│   ├── chunker.py          # Estratégias size e semantic, dataclasses Chunk/ChunkFile (Chunk.page_path no layout page), chunk_id() (id único de chunk nos sidecars), write_chunks() (md, txt, jsonl; no md cada seção de context header termina com as definições de link que usa); balance_chunks() e generate_import_guide() — balanceamento e guia de importação do `--bundle`
│   ├── config_loader.py    # Merge com precedência: defaults < JSON < CLI (usa ctx.get_parameter_source); read_config_section() — seção do JSON (quais chaves o config define)
│   ├── eval_harness.py     # evaluate() — hit-rate@k e MRR sobre pares golden, com breakdown por readiness grade
│   ├── golden_qa.py        # generate_golden_qa() — pares Q&A determinísticos a partir do breadcrumb de headings
│   ├── ignore_parser.py    # filter_files() com pathspec (pula binários: BINARY_EXTENSIONS, is_binary_path()); DOGRAPPER_STATE_NAMES/NON_DOC_NAMES — arquivos de estado do dograpper (e robots.txt) que manifest e pack nunca listam; exclude_subtree() (saída dentro da entrada), normalize_extensions()/split_by_extension() (`--include-extensions` de download e pack)
│   ├── llms_txt_parser.py  # fetch_llms_txt() — parser do convention llmstxt.org (markdown links + bare URLs), stdlib-only
│   ├── manifest.py         # Dataclasses Manifest/ManifestEntry, read (levanta erro)/load (tolerante)/save/build, diff (hash de conteúdo decide quando os dois lados têm; mtime só para entrada antiga) e narrow_diff_to_paths; build grava os records do perfil httrack (RECORD_FIELDS: status, content_type, etag, last_modified, redirected, payload_md5) e mantém os do manifest anterior para arquivo não tocado; find_manifest() — manifest que o pack usa por padrão, achado também a partir de um subdiretório do mirror (até MAX_MANIFEST_LEVELS acima, nunca acima do diretório do host); merge_manifests() — junta o manifest anterior ao novo no download (etag/last_modified antigos ficam se o tamanho não mudou e não há record do motor)
│   ├── mcp_server.py       # Protocolo MCP stdlib-only: JSON-RPC 2.0 newline-delimited, tools/list, tools/call
│   ├── page_layout.py      # Layout por página (ADR-0010): assign_page_paths() (espelho do INPUT_DIR em pages/, regras de utils/portable_names.py + nomes reservados do Windows), page_chunks() (um Chunk por página), page_titles() (<title> sem sufixo do site → h1 cru → stem), write_pages() (pages/ montado em diretório temporário e trocado, INDEX.md atômico; no md, definição de link para página empacotada ou alias de redirect pulado aponta para o arquivo dela, relativo ao arquivo que linka); owns_pages()
│   ├── pack_artifacts.py   # Sidecars do pack: cross_refs.json, delta_manifest.json, llm-readiness.json, report HTML, tokens
│   ├── pack_reader.py      # load_chunks() — leitura tolerante dos chunks JSONL do pack em PackedChunk
│   ├── pack_scoring.py     # score_chunks() — readiness por chunk + páginas do --report, lê cada fonte uma vez
│   ├── playwright_crawl.py # Crawler headless; hidratação bounded (domcontentloaded 10s + a[href] 5s + 500ms); aceita seed_urls; navigator= (lib/httrack/browser.py) põe o crawl sob o perfil httrack: semeado = só as sementes, about:blank antes de cada página, goto na URL final que o Navigator devolveu, página recusada ou não-HTML nunca aberta, links no escopo do perfil (dentro do --depth), nome/escrita do Navigator
│   ├── query_packer.py     # load_queries() + order_files_by_queries() — ordenação gulosa por afinidade BM25 (pack --for-queries)
│   ├── readiness_diff.py   # compare_readiness() + render_markdown()/render_text() — diff de snapshots llm-readiness.json, stdlib-only
│   ├── retrieval.py        # build_index()/BM25Index — retrieval determinístico stdlib-only (tie-break por doc_id)
│   ├── sitemap_parser.py   # fetch_sitemap() — sitemap.xml + sitemapindex recursivo (até MAX_RECURSION_DEPTH), gzip, guarda de escopo (candidatos de topo só do host do start; sub-sitemap do mesmo netloc, ou de outro host sob o prefixo de path da base), SITEMAP_NS
│   ├── source_urls.py      # resolve_source_urls() — URL de origem por arquivo do pack: entrada do manifest (local_path casado também a partir de subdiretório do mirror; ambíguo = sem URL), senão marcador da página (HTTrack `Mirrored from`, `saved from url=(N)`) validado como entrada não confiável; format_url_summary()
│   ├── spa_detector.py     # is_spa() via html.parser; small-sample branch (N<5) + errors='replace' encoding
│   ├── url_filter.py       # filter_urls() — same-netloc + path-prefix canonicalizado (rstrip('/')+'/' nos dois lados) + depth; UrlFilters/rule_regex() — regras `--filter` (sintaxe HTTrack +/-, última vence) como regex lida igual por Python re e pelo POSIX ERE do wget, para todos os caminhos
│   └── wget_mirror.py      # run_wget_mirror() --mirror + run_wget_urls() -i; BROWSER_UA Chrome/120, --no-parent (url_filter_args(): --accept/--reject-regex quando há --filter), --timestamping sempre
```

## Arquivos de contexto

| Arquivo | Quando ler |
|---|---|
| `.dograpper.json.example` | Ao mexer em `config_loader.py` ou no merge de configuração |
| `.docsignore.example` | Ao mexer em `ignore_parser.py` |
| `tests/test_llms_txt_parser.py` | Antes de alterar `lib/llms_txt_parser.py` ou o parser de `llms.txt` / `llms-full.txt` |
| `tests/test_sitemap_parser.py` | Antes de alterar `lib/sitemap_parser.py`, recursão `sitemapindex` ou same-netloc guard |
| `tests/test_url_filter.py` | Antes de alterar `lib/url_filter.py` (canonicalização de path-prefix, semântica de `depth` ou das regras `--filter`) |
| `tests/test_jsonl_format.py` | Antes de alterar a escrita JSONL em `lib/chunker.py` |
| `tests/test_delta_manifest.py` | Antes de alterar `lib/manifest.py` ou lógica de `--delta` |
| `tests/test_retrieval.py` | Antes de alterar `lib/retrieval.py` (BM25, tokenização ou tie-break determinístico) |
| `tests/test_pack_reader.py` | Antes de alterar `lib/pack_reader.py` ou o formato JSONL que ele consome |
| `tests/test_golden_qa.py` | Antes de alterar `lib/golden_qa.py` ou o template de perguntas |
| `tests/test_httrack_browser.py` | Antes de alterar `lib/httrack/browser.py` ou o caminho `navigator=` de `lib/playwright_crawl.py` (navegação pelo Fetcher do perfil, aborto antes do render, redirect antes do goto, escopo de iframe/popup/subrecurso) |
| `tests/test_eval_harness.py` | Antes de alterar `lib/eval_harness.py` (hit-rate, MRR, breakdown por grade) |
