# dograpper — Contexto do Projeto

## Visão geral

CLI em Python que implementa uma pipeline de engenharia de contexto
determinístico para ingestão em LLMs estáticos. Transforma documentação
HTML em contexto estruturado, dedupicado, pontuado e versionado — pronto
para NotebookLM, RAG pipelines, Claude Projects e fine-tuning. Três
subcomandos: `download` (espelha site via wget/playwright, ou perfil httrack), `pack`
(processa e agrupa em chunks otimizados) e `sync` (download + pack delta).

## Stack técnica

- **Linguagem**: Python 3.10+
- **CLI framework**: click
- **Package manager**: uv
- **Filtro de arquivos**: pathspec (sintaxe gitignore)
- **Crawling SPA**: playwright (dependência opcional, import condicional)
- **Token counting**: tiktoken (dependência obrigatória)
- **Download padrão**: wget (dependência do sistema); perfil opt-in `--downloader httrack` (Python puro, `lib/httrack/`; extra `httrack` = brotli + zstandard; exige OpenSSL >= 3.5 para o handshake idêntico)
- **Testes**: pytest com click.testing.CliRunner

## Estrutura do repositório

```
src/dograpper/
├── cli.py                  # Entry point click, flags globais (--verbose, --quiet, --config)
├── commands/
│   ├── _httrack_profile.py # Modo `--downloader httrack` do download: resolve_profile() (opções do perfil, guarda sob wget, policy_kw), discovery_fetch() (robots antes do GET), run_httrack() (fetch semeado + relatório + fail-loud)
│   ├── _page_layout.py     # Modo `pack --layout page` (ADR-0010): check_flags() (flags só-chunk na CLI ou no config, --bundle, --for-queries, --api-records, --format jsonl, --dedup ≠ off → exit 2), check_ownership() (pages/ sem INDEX.md → exit 1), write() (falha de escrita → exit 1)
│   ├── docs.py             # `dograpper docs`: build_page() (HTML puro, autocontido, gerado da árvore click) + make_server() (http.server em 127.0.0.1; porta ocupada falha, nunca troca de porta)
│   ├── doctor.py           # Detecta e instala deps pesadas (wget, chromium) em DOGRAPPER_HOME; --check-system-libs
│   ├── download.py         # Opções click + despacho do --downloader; cascade 4-layer do wget: llms.txt → sitemap → wget --mirror → Playwright bounded (layers 1+2 compartilhadas com o perfil httrack)
│   ├── drift.py            # Drift de contexto entre dois llm-readiness.json (+ delta_manifest.json opcional)
│   ├── eval.py             # Hit-rate empírico do pack JSONL: golden Q&A offline → BM25 → hit-rate@k/MRR por grade
│   ├── explain.py          # Preview read-only do que o LLM recebe por chunk (headers v1, cross-refs, grade)
│   ├── init.py             # Wizard de onboarding: gera .dograpper.json por alvo (notebooklm/rag/claude-project/claude-code); claude-code também escreve um SKILL.md stub em --skill-dir (nunca sobrescreve; pack não toca nele)
│   ├── pack.py             # Orquestração: list files → filter → chunk → write → summary; --layout chunk|page (modo page em _page_layout.py); --api-records (só jsonl) chama utils/api_reference/
│   ├── serve.py            # Servidor MCP local (stdio) sobre o pack JSONL: search/get/cross-refs/readiness
│   └── sync.py             # Subcomando sync (download + pack em um passo); repassa --downloader, as flags do perfil (PROFILE_OPTIONS de _httrack_profile.py) e --layout
├── lib/
│   ├── chunker.py          # Estratégias size e semantic, dataclasses Chunk/ChunkFile (Chunk.page_path no layout page), chunk_id() (id único de chunk nos sidecars), write_chunks() (md, txt, jsonl; no md cada seção de context header termina com as definições de link que usa)
│   ├── config_loader.py    # Merge com precedência: defaults < JSON < CLI (usa ctx.get_parameter_source); read_config_section() — seção do JSON (quais chaves o config define)
│   ├── eval_harness.py     # evaluate() — hit-rate@k e MRR sobre pares golden, com breakdown por readiness grade
│   ├── golden_qa.py        # generate_golden_qa() — pares Q&A determinísticos a partir do breadcrumb de headings
│   ├── httrack/
│   │   ├── crawl.py        # fetch_url_list() — lista semeada: cada URL é start URL (navigate), robots, /cdn-cgi/ fora de escopo, redirects same-host (até 5), só 2xx não-desafio é escrito (atômico), front_failed; ThreadPool com Fetcher e NameRegistry compartilhados
│   │   ├── escape.py       # escape_unsafe()/request_target() — percent-escape do HTTrack (htslib.c escape_check_url); fonte única para o alvo no fio (fetcher), o Referer (policy) e as regras do robots.txt
│   │   ├── fetcher.py      # Fetcher.get()/robots_for() — conexão persistente por thread, pacing (conn-rate, banda, gap por host), retries, gate global de Retry-After relido após o sleep, decode de Content-Encoding limitado a MAX_BODY_BYTES, corpo curto = IncompleteRead retentado, alvo percent-encoded e Host IDNA como o HTTrack, robots com redirects same-host; same_host() — escopo de redirect (fonte única para robots, crawl e descoberta)
│   │   ├── naming.py       # NameRegistry.assign() — nome local estilo HTTrack: <host>/<path> (IPv6 literal → [addr] com ':' → _), index.html, .html por content-type (substitui extensão conhecida pelo HTTrack — tabela MIME, dinâmica .php/.cgi…, .txt/.pdf —, anexa às desconhecidas), caracteres proibidos pelo HTTrack → _, hash md5[:4] da query, sufixo -N em colisão (comparação casefold, sem caixa), thread-safe; None se o caminho escapa de output_dir (essas três regras vêm de utils/portable_names.py)
│   │   ├── policy.py       # build_policy() clamps e limites validados + request_headers() idênticos ao HTTrack 3.51 (por esquema, UA e referer; Referer sem userinfo nem fragmento, escapado como o alvo) + make_ssl_context() (perfil TLS) + accept_encoding()/decoder_module() (única fonte dos decoders br/zstd)
│   │   ├── report.py       # RunReport (contagens por status, challenged, robots_blocked, out_of_scope, filtered, errors, partial) + format_report() — URLs já redigidas, caracteres de controle neutralizados via utils/redact.py
│   │   └── robots.py       # parse_robots()/RobotsRules — RFC 9309 + semântica HTTrack (longest-match, Allow vence empate, Crawl-delay, Sitemap); regras percent-escapadas com escape.py, como o alvo no fio
│   ├── ignore_parser.py    # filter_files() com pathspec
│   ├── llms_txt_parser.py  # fetch_llms_txt() — parser do convention llmstxt.org (markdown links + bare URLs), stdlib-only
│   ├── manifest.py         # Dataclasses Manifest/ManifestEntry, read (levanta erro)/load (tolerante)/save/build, diff e narrow_diff_to_paths
│   ├── mcp_server.py       # Protocolo MCP stdlib-only: JSON-RPC 2.0 newline-delimited, tools/list, tools/call
│   ├── page_layout.py      # Layout por página (ADR-0010): assign_page_paths() (espelho do INPUT_DIR em pages/, regras de utils/portable_names.py + nomes reservados do Windows), page_chunks() (um Chunk por página), page_titles() (<title> sem sufixo do site → h1 cru → stem), write_pages() (pages/ montado em diretório temporário e trocado, INDEX.md atômico; no md, definição de link para página empacotada ou alias de redirect pulado aponta para o arquivo dela, relativo ao arquivo que linka); owns_pages()
│   ├── pack_artifacts.py   # Sidecars do pack: cross_refs.json, delta_manifest.json, llm-readiness.json, report HTML, tokens
│   ├── pack_reader.py      # load_chunks() — leitura tolerante dos chunks JSONL do pack em PackedChunk
│   ├── pack_scoring.py     # score_chunks() — readiness por chunk + páginas do --report, lê cada fonte uma vez
│   ├── playwright_crawl.py # Crawler headless; hidratação bounded (domcontentloaded 10s + a[href] 5s + 500ms); aceita seed_urls
│   ├── query_packer.py     # load_queries() + order_files_by_queries() — ordenação gulosa por afinidade BM25 (pack --for-queries)
│   ├── readiness_diff.py   # compare_readiness() + render_markdown()/render_text() — diff de snapshots llm-readiness.json, stdlib-only
│   ├── retrieval.py        # build_index()/BM25Index — retrieval determinístico stdlib-only (tie-break por doc_id)
│   ├── sitemap_parser.py   # fetch_sitemap() — sitemap.xml + sitemapindex recursivo, gzip, same-netloc guard (SITEMAP_NS)
│   ├── source_urls.py      # resolve_source_urls() — URL de origem por arquivo do pack: entrada do manifest (local_path casado também a partir de subdiretório do mirror; ambíguo = sem URL), senão marcador da página (HTTrack `Mirrored from`, `saved from url=(N)`) validado como entrada não confiável; format_url_summary()
│   ├── spa_detector.py     # is_spa() via html.parser; small-sample branch (N<5) + errors='replace' encoding
│   ├── url_filter.py       # filter_urls() — same-netloc + path-prefix canonicalizado (rstrip('/')+'/' nos dois lados) + depth; UrlFilters/rule_regex() — regras `--filter` (sintaxe HTTrack +/-, última vence) como regex lida igual por Python re e pelo POSIX ERE do wget, para todos os caminhos
│   └── wget_mirror.py      # run_wget_mirror() --mirror + run_wget_urls() -i; BROWSER_UA Chrome/120, --no-parent (url_filter_args(): --accept/--reject-regex quando há --filter), --timestamping sempre
└── utils/
    ├── api_reference/      # Registros de referência de API (ADR-0009), opt-in via `pack --api-records`
    │   ├── __init__.py     # split_api_pages()/split_page(): detecção pelo gerador (utils/generator.py) e despacho ao adaptador; ApiRecord (url() com âncora percent-encoded), NotSplit, aviso das páginas mantidas inteiras e linha do resumo
    │   ├── _html.py        # Regions/Text — leitura linear de HTML dos adaptadores: texto por região em linhas, pilha com contagem por tag (tag de fechamento solta em O(1)); fonte única da garantia de tempo linear
    │   └── javadoc.py      # records(): página de tipo javadoc 25 (javadoc/ClassWriter) → 1 registro contêiner + 1 por membro (section.detail); só a markup medida, senão NotSplit; leitura linear via _html.py
    ├── atomic_write.py     # atomic_write_bytes() — arquivo temporário no mesmo diretório + os.replace; modo padrão do umask
    ├── challenge.py        # is_challenge() / is_challenge_page() / find_challenge_files() — interstitial Cloudflare por cf-mitigated ou <title> "Just a moment..." (nunca pelo beacon /cdn-cgi/); fonte única do fetcher httrack e do pack
    ├── chunk_inspector.py  # Parsing read-only de chunks empacotados: seções v1, sidecars (readiness, cross-refs)
    ├── code_fence.py       # fence() / code_span() / split_blocks() / unfence() — bloco de código cercado (CommonMark): fonte única para o stripper (escreve), dedup e chunker (nunca partem um bloco em linha em branco), scorer e writers txt/jsonl (tiram a cerca)
    ├── content_extractor.py # extract_content() — extração inteligente de HTML (semantic containers, density scoring, blacklist)
    ├── dedup.py            # deduplicate() — dedup cross-file via MD5 (exact) e SimHash (fuzzy); nunca remove as definições de link do md e compara blocos pelo destino do link, não pelo número
    ├── dep_resolver.py     # resolve_wget()/resolve_browser_dir() — deps em DOGRAPPER_HOME (env lido no import)
    ├── dry_run_report.py   # generate_report() — relatório formatado para --dry-run
    ├── generator.py        # page_generator() — conteúdo do <meta name="generator"> (javadoc/…, MediaWiki …) nos primeiros 64 KiB; fonte única da detecção de gerador dos adaptadores (ADR-0009)
    ├── heading_extractor.py # extract_with_headings(), get_active_headings(), format_context_header() — formato dograpper-context-v1 (`title` só no layout page; metadata da página, ex. `version`, após `url`; `>` escrito como \u003e)
    ├── html_stripper.py    # strip_html() via html.parser, descarta script/style, emite \n\n entre blocos HTML; <pre> verbatim em bloco cercado com a linguagem das classes mw-highlight-lang-*/language-*/lang-*/highlight-* do <pre>, <code> ou div mais próxima que declare (PreCapture, render_text() compartilhados com heading_extractor); markdown=True (md): MarkdownStripper/render_markdown() escrevem títulos #, links de referência [texto][n] com um bloco `[n]: href` no fim da página, numerado por primeiro uso (sem âncora da própria página nem esquema fora de http/https/mailto; link dentro de <code>/<pre>/div.member-signature sai só como texto), listas -/N. aninhadas (item com bloco sai sem marcador) e tabelas pipe uma linha por linha, em tempo linear; escape_link_text() compartilhado com o INDEX.md; split_definitions()/definitions_used() (DEFINITION, REFERENCE) leem o bloco de definições para word_counter, dedup, chunker, link_extractor e page_layout
    ├── link_extractor.py   # extract_links(), build_cross_ref_index(), annotate_cross_refs() (marcador depois de um link Markdown [texto](url) ou [texto][n], nunca no destino nem numa linha de definição)
    ├── logger.py           # setup_logger() com suporte a verbose/quiet
    ├── mediawiki.py        # is_mediawiki() (meta generator via generator.py), clean(), page_metadata() e find_redirect_aliases() — limpeza por página de MediaWiki antes do extrator genérico: corta do fonte navbox, mw-editsection e caixas de manutenção (mbox com toggle mw-customtoggle-mbox-*); o banner de versão vira version/version_status do header e do registro JSONL (senão a 1ª categoria oculta Version X); banner de redação desconhecida fica no texto; alias de redirect (wgRedirectedFrom) cujo alvo (mesmo wgPageName) está no run é pulado pelo pack; página não-MediaWiki volta intacta
    ├── portable_names.py   # FORBIDDEN (caracteres proibidos pelo HTTrack → _), claim_unique() (colisão casefold → -N), resolve_under() (caminho real contido na raiz) — regras de nome compartilhadas por lib/httrack/naming.py e o layout por página do pack (ADR-0010)
    ├── progress.py         # ProgressReporter — linhas [progress] com throttle (≤1 a cada 5 s, só quando muda, final no finish()), forma lista fixa (N/M URLs, %, ETA após 10) ou total crescente (files, queued, last redigida); um reporter por etapa de fetch do download (#98, #78)
    ├── readiness_report.py # PageReadiness, find_removed_blocks(), generate_html_report(), format_terminal_report() — relatório do --report
    ├── redact.py           # redact_url() — remove userinfo (user:senha@) e percent-encoda caracteres de controle antes de logar; drop_userinfo() — fonte única da remoção de userinfo (logs e headers do perfil httrack); neutralize_controls() — fonte única da neutralização C0/DEL/C1
    ├── scorer.py           # LLM Readiness Score: noise_ratio, boundary_integrity, context_depth → grade A/B/C
    ├── token_counter.py    # count_tokens() — tiktoken opcional, fallback estimativa palavras→tokens
    └── word_counter.py     # count_words() (markdown=True: sem a marcação do md — marcadores de título/lista, pipes, linha delimitadora, bloco de definições de link no fim) e count_words_file()
tests/
├── conftest.py             # Fixture `server`: http.server local roteirizado por path (usado por test_httrack_crawl e test_download_cascade)
├── test_action_yml.py      # Guard estrutural do action.yml (inputs, outputs, marcador, branding)
├── test_api_reference.py   # --api-records: detecção/despacho, registros contêiner e membro sobre a fixture javadoc 25 (tests/fixtures/javadoc), markup não suportada, linearidade, CLI (erros de uso, dedup, --for-queries, --delta, serve)
├── test_atomic_write.py    # atomic_write_bytes: cria pais e conteúdo; falha/KeyboardInterrupt não deixa arquivo final nem *.tmp; modo segue o umask corrente, sem nunca alterá-lo
├── test_boundary_chunking.py # Boundary-aware chunking: preservação de blocos estruturais
├── test_bundle_notebooklm.py # Bundle presets: notebooklm, rag-standard
├── test_claude_md_inventory.py # Guard estrutural do CLAUDE.md: árvore completa e referências de caminho válidas
├── test_changelog.py       # Guard estrutural do CHANGELOG.md: seções válidas, ordem, versão casando com pyproject
├── test_cli_help_coverage.py # Guard: todo comando tem descrição e toda opção tem help (alimenta `--help` e o `docs`)
├── test_cli_regression.py  # Baseline literal de `dograpper --help` (tests/fixtures/help_baseline.txt)
├── test_cli_smoke.py       # Help, flags obrigatórias, mutual exclusion
├── test_config.py          # Precedência, JSON inválido, arquivo ausente
├── test_content_extractor.py # Extração inteligente: semantic, density, blacklist, edge cases, CLI
├── test_context_v1.py      # Formato dograpper-context-v1: JSON header, campos opcionais, schema
├── test_dedup.py           # Dedup: _split_blocks, _simhash, _hamming_distance, exact/fuzzy/both, CLI
├── test_delta_artifacts.py # Delta como portão de mudança: artefatos completos, pack_state.json, fluxo sync (ADR-0008)
├── test_delta_manifest.py  # Delta: diff_manifests e o contrato do delta_manifest.json
├── test_dep_resolver.py    # Resolução de wget/chromium via DOGRAPPER_HOME (fallback para PATH, reload de módulo)
├── test_docs_command.py    # docs: âncoras por comando/opção, tipos de opção, página autocontida, escape HTML, bind/porta/--no-browser
├── test_doctor.py          # Doctor: detecção, --install (download verificado, lock, idempotência), --check-system-libs
├── test_download.py        # wget mock, SPA detector, manifest roundtrip, UA/headers, run_wget_urls, bounded hydration
├── test_download_cascade.py # Cascade 4-layer: layer-1/2/3/4 wins, below-threshold fall-through, headless, post-wget-i SPA, observability
├── test_download_httrack_profile.py # Perfil `--downloader httrack`: flags só-httrack com wget, caminhos fail-loud, precedência de config, wiring da descoberta
├── test_drift.py           # Drift: compare_readiness, renders markdown/text (literais), CLI (first run, fail-on-drift, --output)
├── test_dry_run.py         # Dry-run: report generation, CLI integration, edge cases
├── test_e2e.py             # Integração ponta-a-ponta usando ./test-docs
├── test_eval_command.py    # Integração do `dograpper eval` sobre um pack JSONL (--json, erros de pré-requisito)
├── test_eval_harness.py    # evaluate(): hit-rate, MRR por rank, breakdown por grade, pares vazios
├── test_explain.py         # Explain preview: parsing de seções v1, sidecars, modos CLI, roundtrip pack→explain
├── test_generator.py      # page_generator: javadoc, MediaWiki após head longo, ordem/caixa de atributos, entidades, ausente, fora da janela
├── test_golden_qa.py       # generate_golden_qa: um par por chunk, heading mais profundo, determinismo
├── test_heading_extractor.py # Heading extraction, active headings, context header v1, CLI integration
├── test_httrack_crawl.py   # fetch_url_list: só 2xx não-desafio escrito, robots, redirects, front_failed, max_links, filtro de extensão, conflito de escrita, format_report
├── test_httrack_fetcher.py # Fetcher: retries, gate de Retry-After, pacing com relógio fake, decode gzip/deflate, ordem dos headers, robots_for, is_challenge
├── test_httrack_naming.py  # NameRegistry: index.html, extensão .html, hash de query, colisão -N (inclusive só de caixa) e estabilidade, host IPv6, traversal/symlink rejeitados, thread-safety
├── test_httrack_policy.py  # Policy: clamps, headers vs fixture httrack_wire, Accept-Encoding, contexto TLS, ClientHello (OpenSSL >= 3.5)
├── test_httrack_robots.py  # parse_robots: grupos, longest-match, Allow vence empate, wildcard/$, Crawl-delay, Sitemap, caps, corpo HTML sem regras
├── test_init_wizard.py     # Init wizard: presets por alvo, overwrite guard, modos interativo/não-interativo, stub SKILL.md do claude-code (nunca sobrescrito, sobrevive ao pack)
├── test_jsonl_format.py    # JSONL format: criação, validação JSON, word count, multi-chunk, registros de API, CLI
├── test_link_extractor.py  # Link extraction, cross-ref index, annotation, CLI integration
├── test_llms_txt_parser.py # fetch_llms_txt: markdown, bare URLs, comments, dedup, llms-full fallback, 404, UA, gzip
├── test_markdown_render.py # Markdown do md (#87): títulos, links, listas, tabelas, tempo linear, offsets de título, contagem sem marcação, pack md/txt/jsonl/page
├── test_mcp_serve.py       # MCP server: protocolo (initialize/ping/tools), stdio loop, tools sobre pack, CLI
├── test_mediawiki.py       # Limpeza MediaWiki: navbox (inclusive aninhado), mw-editsection, caixas de manutenção vs nota, markup fora do corte intacto, caixa sem fim mantida, página de outro gerador idêntica à extração de antes (sha256); versão como metadata (3 redações, categoria oculta, redação desconhecida), header nos dois layouts e registro JSONL (só MediaWiki), --dedup exact mantém a versão de cada página; aliases de redirect (alvo presente, ausente, dois aliases), pack pula e conta
├── test_page_layout.py     # Layout por página: nomes portáveis e colisões, títulos (sufixo, h1 fora do container, stem), INDEX.md literal, exit 2 de flags só-chunk (CLI e config), posse de pages/ (rebuild, exit 1, falha preserva), delta/cross-refs/score/tokens/dry-run, sync
├── test_pack.py            # word_counter, ignore_parser, chunker, write_chunks, CLI integration
├── test_pack_challenge.py  # Pack: páginas de challenge (Cloudflare) detectadas, avisadas e fora dos chunks; falso positivo em prosa
├── test_pack_artifacts.py  # Sidecars: cross-refs, delta manifest, snapshot de readiness, contagem de tokens
├── test_pack_reader.py     # load_chunks: campos, linhas malformadas, ordem determinística entre arquivos
├── test_pack_scoring.py    # score_chunks: ids, report pages, overrides de texto, tolerância a falha
├── test_progress.py       # ProgressReporter: formas lista fixa/total crescente, ETA após 10 URLs, throttle com relógio fake, finish() único, URL redigida, logger INFO
├── test_query_packer.py    # load_queries (comments/blanks, erros) e order_files_by_queries (determinismo, co-locação, tie-break)
├── test_readiness_report.py # Readiness report: find_removed_blocks, builders HTML/terminal, CLI --report
├── test_redact.py          # redact_url: userinfo removido, URL sem credenciais intacta, URL inválida falha seguro, caracteres de controle neutralizados
├── test_retrieval.py       # BM25: tokenize, ranking, top-k, determinismo e tie-break por doc_id
├── test_scorer.py          # LLM Readiness Score: noise_ratio, boundary, context_depth, grades, CLI
├── test_sitemap_parser.py  # fetch_sitemap: namespace, urlset, gzip, sitemapindex recursivo, cross-host reject, 404, UA
├── test_source_urls.py     # URLs de origem do pack --context-header: carga do manifest (explícito falha, default vira nota), marcadores HTTrack/saved-from, validação, precedência, resumo, pack de subdiretório do mirror
├── test_sync.py            # Pass-through de flags do sync para download/pack (sem precedência)
├── test_sync_precedence.py # Precedência de config através do ctx.invoke do sync (CLI explícita > JSON > defaults)
├── test_token_counter.py   # Token counting: fallback, tiktoken, format_summary, CLI integration
└── test_url_filter.py      # filter_urls: same-netloc, path-prefix canonicalizado, depth=0 unlimited, depth bounded, dedup; semântica das regras --filter
action.yml                  # Composite GitHub Action: download + full pack --score → drift → comentário de PR (nunca pack --delta; ver ADR-0007)
```

## Como rodar localmente

```bash
git clone <repo-url>
cd dograpper
uv sync --extra dev --extra headless --extra httrack   # deps + pytest + playwright (sem baixar browser) + brotli/zstd do perfil httrack
uv run dograpper --help    # verifica que está funcionando
```

Para testar download real:
```bash
uv run dograpper download https://click.palletsprojects.com/en/stable/ -o ./test-docs -d 2
uv run dograpper pack ./test-docs -o ./chunks
```

## Arquivos de contexto importantes

| Arquivo | Quando ler |
|---|---|
| `README.md` | **Sempre.** Comportamento de cada subcomando, flags, formato de config e exemplos de uso. É a fonte de verdade do contrato observável. |
| `docs/adr/` | Antes de reverter ou contornar uma decisão arquitetural (repomix, contagem por palavras, deps opcionais, query-oriented packing, delta na Action, registros de referência de API, layout por página) |
| `docs/superpowers/specs/2026-11-13-httrack-downloader-profile-design.md` | Antes de alterar `lib/httrack/` ou `commands/_httrack_profile.py`: desvios aprovados em relação ao HTTrack e roteiro dos próximos PRs do perfil. Evidência por comportamento (com citações do código do HTTrack) em `docs/discovery/httrack-mirroring-requirements.md` |
| `GLOSSARY.md` | Ao nomear conceitos de entrada/saída (página, registro, chunk, símbolo, contêiner, membro, target) em código, docs, issues ou PRs |
| `.dograpper.json.example` | Ao mexer em `config_loader.py` ou no merge de configuração |
| `.docsignore.example` | Ao mexer em `ignore_parser.py` |
| `tests/test_pack.py` | Antes de alterar qualquer coisa em `lib/chunker.py` ou `commands/pack.py` |
| `tests/test_page_layout.py` | Antes de alterar `lib/page_layout.py`, `commands/_page_layout.py` ou o despacho `--layout` de `commands/pack.py` (nomes, formato do `INDEX.md`, posse de `pages/`, flags rejeitadas) |
| `tests/test_progress.py` | Antes de alterar `utils/progress.py` (formato e throttle das linhas `[progress]`) |
| `tests/test_query_packer.py` | Antes de alterar `lib/query_packer.py` ou a integração `--for-queries` em `commands/pack.py` |
| `tests/test_pack_challenge.py` | Antes de alterar `utils/challenge.py` ou a etapa 6a de `commands/pack.py` |
| `tests/test_pack_scoring.py` | Antes de alterar `lib/pack_scoring.py` ou a etapa 9c de `commands/pack.py` |
| `tests/test_pack_artifacts.py` | Antes de alterar `lib/pack_artifacts.py` ou as escritas de sidecar (10a-10e) de `commands/pack.py` |
| `tests/test_source_urls.py` | Antes de alterar `lib/source_urls.py`, a carga do manifest (`_load_url_manifest`) ou o passo 7c de `commands/pack.py` |
| `tests/test_sync_precedence.py` | Antes de alterar `commands/sync.py` ou `lib/config_loader.py` (mecanismo CLI_EXPLICIT_PARAMS) |
| `tests/test_download.py` | Antes de alterar qualquer coisa em `lib/wget_mirror.py`, `lib/spa_detector.py`, `lib/playwright_crawl.py` ou `commands/download.py` |
| `tests/test_download_cascade.py` | Antes de alterar a orquestração de `commands/download.py` ou o threshold `MIN_URLS_TO_CONSIDER_DISCOVERED` |
| `tests/test_download_httrack_profile.py` | Antes de alterar `commands/_httrack_profile.py` ou o despacho `--downloader` de `commands/download.py` (flags `[httrack]`, mensagens fail-loud, injeção do `Fetcher` na descoberta) |
| `tests/test_llms_txt_parser.py` | Antes de alterar `lib/llms_txt_parser.py` ou o parser de `llms.txt` / `llms-full.txt` |
| `tests/test_sitemap_parser.py` | Antes de alterar `lib/sitemap_parser.py`, recursão `sitemapindex` ou same-netloc guard |
| `tests/test_url_filter.py` | Antes de alterar `lib/url_filter.py` (canonicalização de path-prefix, semântica de `depth` ou das regras `--filter`) |
| `tests/test_content_extractor.py` | Antes de alterar `utils/content_extractor.py` ou o tratamento de `<pre>` em `utils/html_stripper.py` |
| `tests/test_mediawiki.py` | Antes de alterar `utils/mediawiki.py` ou o gancho MediaWiki de `extract_content()` em `utils/content_extractor.py` |
| `tests/test_token_counter.py` | Antes de alterar `utils/token_counter.py` |
| `tests/test_dedup.py` | Antes de alterar `utils/dedup.py` ou a integração de dedup em `commands/pack.py` |
| `tests/test_dry_run.py` | Antes de alterar `utils/dry_run_report.py` ou a lógica de dry-run em `commands/pack.py` |
| `tests/test_heading_extractor.py` | Antes de alterar `utils/heading_extractor.py` ou a lógica de context-header em `commands/pack.py` |
| `tests/test_httrack_crawl.py` | Antes de alterar `lib/httrack/crawl.py` ou `lib/httrack/report.py` |
| `tests/test_httrack_fetcher.py` | Antes de alterar `lib/httrack/fetcher.py`, `utils/challenge.py` ou `lib/httrack/escape.py` |
| `tests/test_httrack_naming.py` | Antes de alterar `lib/httrack/naming.py` ou `utils/portable_names.py` |
| `tests/test_httrack_policy.py` | Antes de alterar `lib/httrack/policy.py` |
| `tests/test_httrack_robots.py` | Antes de alterar `lib/httrack/robots.py` |
| `tests/test_init_wizard.py` | Antes de alterar `commands/init.py` ou os presets `TARGETS` |
| `tests/test_markdown_render.py` | Antes de alterar o modo `markdown` de `utils/html_stripper.py`, `count_words(markdown=True)` em `utils/word_counter.py` ou a escolha md/plain em `lib/chunker.py`, `lib/page_layout.py`, `lib/pack_scoring.py` e `commands/pack.py` |
| `tests/test_link_extractor.py` | Antes de alterar `utils/link_extractor.py` ou a lógica de cross-refs em `commands/pack.py` |
| `tests/test_scorer.py` | Antes de alterar `utils/scorer.py` ou a lógica de score em `commands/pack.py` |
| `tests/test_readiness_report.py` | Antes de alterar `utils/readiness_report.py` ou a lógica de `--report` em `commands/pack.py` |
| `tests/test_context_v1.py` | Antes de alterar o formato `dograpper-context-v1` em `utils/heading_extractor.py` |
| `tests/test_jsonl_format.py` | Antes de alterar a escrita JSONL em `lib/chunker.py` |
| `tests/test_api_reference.py` | Antes de alterar `utils/api_reference/` ou a integração `--api-records` em `commands/pack.py` e `lib/chunker.py`. A fixture sai de `tests/fixtures/javadoc/src` via `tests/fixtures/javadoc/regenerate.sh` (javadoc 25; nunca editar o HTML à mão) |
| `tests/test_delta_manifest.py` | Antes de alterar `lib/manifest.py` ou lógica de `--delta` |
| `tests/test_delta_artifacts.py` | Antes de alterar o portão de `--delta` em `commands/pack.py` ou `PACK_STATE_FILENAME` (semântica fixada na ADR-0008) |
| `tests/test_redact.py` | Antes de alterar `utils/redact.py` (usado por todo log que imprime URL) |
| `tests/test_retrieval.py` | Antes de alterar `lib/retrieval.py` (BM25, tokenização ou tie-break determinístico) |
| `tests/test_pack_reader.py` | Antes de alterar `lib/pack_reader.py` ou o formato JSONL que ele consome |
| `tests/test_generator.py` | Antes de alterar `utils/generator.py` (detecção de gerador usada pelos adaptadores) |
| `tests/test_golden_qa.py` | Antes de alterar `lib/golden_qa.py` ou o template de perguntas |
| `tests/test_eval_harness.py` | Antes de alterar `lib/eval_harness.py` (hit-rate, MRR, breakdown por grade) |
| `tests/test_eval_command.py` | Antes de alterar `commands/eval.py` |
| `tests/test_drift.py` | Antes de alterar `lib/readiness_diff.py` ou `commands/drift.py` (formatos markdown/text são literais testados) |
| `tests/test_action_yml.py` | Antes de alterar `action.yml` (inputs/outputs/marcador exigidos) |
| `tests/test_atomic_write.py` | Antes de alterar `utils/atomic_write.py` |
| `tests/test_bundle_notebooklm.py` | Antes de alterar lógica de `--bundle` |
| `tests/test_boundary_chunking.py` | Antes de alterar `_split_text_by_words` ou `utils/code_fence.py` |
| `CHANGELOG.md` | **Toda vez que a mudança for observável pelo usuário.** O cabeçalho do arquivo define a regra: o que ganha entrada, em qual seção, e quando (no mesmo PR, em `## [Unreleased]`) |
| `docs/schema-v1.md` | Referência do schema `dograpper-context-v1` — manter sincronizado com `heading_extractor.py` e `chunker.py` |
| `tests/test_docs_command.py` | Antes de alterar `commands/docs.py` (página gerada da árvore click, bind em 127.0.0.1, política de porta) |
| `tests/test_doctor.py` | Antes de alterar `commands/doctor.py` (detecção, `--install`, lock, `--check-system-libs`) |
| `tests/test_dep_resolver.py` | Antes de alterar `utils/dep_resolver.py` ou a semântica de `DOGRAPPER_HOME` |
| `tests/test_cli_help_coverage.py` | Antes de adicionar comando ou opção: ambos precisam de descrição/help escrito, dizendo o que fazem e o efeito do default |
| `tests/test_cli_regression.py` | Antes de adicionar/renomear subcomando ou flag no help top-level — o baseline `tests/fixtures/help_baseline.txt` precisa ser regenerado |

## Regras críticas

1. **Dependências com problemas de compatibilidade devem ser opcionais.** Libs que exigem binários do sistema, compilação nativa problemática, ou que não funcionam em todos os ambientes (ex: playwright, que requer `playwright install chromium`) devem ser import condicional com mensagem de erro amigável. Dependências pip puras podem ser obrigatórias sem restrição.
2. **Não usar repomix.** A concatenação de chunks é feita em Python puro. Essa é uma decisão arquitetural tomada — não reverter.
3. **Contagem de palavras, não bytes.** O chunking usa `len(text.split())` como métrica. Os limites do NotebookLM são em palavras. Não mudar para bytes.
4. **Playwright nunca é import top-level.** Sempre import condicional dentro da função, com mensagem de erro amigável se ausente. Dependências pip puras (tiktoken, etc.) podem ser import top-level normalmente.
5. **Testes existentes não podem quebrar.** Qualquer mudança deve manter `uv run pytest tests/ -v` passando integralmente antes de commitar.
6. **Config precedência é inviolável**: defaults do click < `.dograpper.json` < flags CLI explícitas. Usa `ctx.get_parameter_source()` para distinguir. Não simplificar esse mecanismo.
7. **Encoding tolerante.** Leitura de arquivos sempre com `errors="replace"`. O CLI não deve crashar por causa de caracteres estranhos em HTMLs baixados.
8. Ignorar (não ler) tudo que estiver em `./temporario/`
9. **Mudança observável pelo usuário exige entrada no `CHANGELOG.md`**, em `## [Unreleased]`, no mesmo PR. Observável = superfície do CLI (comando, flag, output, exit code), arquivos escritos ou seu formato, comportamento da Action, ou requisito de instalação. `refactor`/`test`/`chore`/`ci`/`build`/`docs` não geram entrada — se gerariam, o commit foi tipado errado. A regra completa está no cabeçalho do `CHANGELOG.md`; `tests/test_changelog.py` guarda a parte mecânica.
10. **Release**: renomear `## [Unreleased]` para `## [X.Y.Z] - AAAA-MM-DD`, abrir uma `## [Unreleased]` vazia e bumpar `version` no `pyproject.toml` no mesmo commit. `dograpper --version` lê o metadata do pacote instalado — tag sem bump publica binário que se identifica errado.

## Padrões de commit e branch

- Commits em português ou inglês, sem preferência rígida
- Formato: `tipo: descrição curta` (ex: `feat: implementar estratégia semantic no chunker`, `fix: corrigir contagem de palavras em arquivos vazios`, `refactor: extrair módulos para lib/`)
- Branch principal: `main`
- Feature branches: `feat/nome-curto` ou `fix/nome-curto`

## CI/CD

`.github/workflows/ci.yml` roda a suíte em push para `main` e em pull request,
numa matriz Python 3.10 / 3.12, com `uv sync --extra dev --extra headless --extra httrack`
(o extra `headless` é necessário porque `tests/test_doctor.py` faz patch de
`playwright.__main__` — nenhum browser é baixado; sem o extra `httrack`, os
testes de decode br/zstd são pulados em silêncio). `.github/workflows/release.yml`
cuida do release. Para replicar o CI localmente:

```bash
uv sync --extra dev --extra headless --extra httrack
uv run pytest tests/ -v
```

## Comandos úteis

```bash
# Rodar todos os testes
uv run pytest tests/ -v

# Rodar apenas testes do pack
uv run pytest tests/test_pack.py -v

# Rodar apenas testes do download
uv run pytest tests/test_download.py -v

# Rodar um teste específico
uv run pytest tests/test_pack.py::test_chunk_by_size_basic -v

# Ver help dos comandos
uv run dograpper --help
uv run dograpper download --help
uv run dograpper pack --help

# Download de teste rápido (site pequeno)
uv run dograpper download https://click.palletsprojects.com/en/stable/ -o ./test-docs -d 1

# Pack com limite baixo para forçar múltiplos chunks
uv run dograpper pack ./test-docs -o ./chunks --max-words-per-chunk 5000

# Pack com verbose para debug
uv run dograpper -v pack ./test-docs -o ./chunks --strategy semantic

# Pack sem extração inteligente (HTML integral)
uv run dograpper pack ./test-docs -o ./chunks --no-extract

# Pack com contagem de tokens
uv run dograpper pack ./test-docs -o ./chunks --show-tokens

# Rodar testes de extração de conteúdo
uv run pytest tests/test_content_extractor.py -v

# Rodar testes de token counter
uv run pytest tests/test_token_counter.py -v

# Rodar testes de deduplicação
uv run pytest tests/test_dedup.py -v

# Rodar testes de dry-run
uv run pytest tests/test_dry_run.py -v

# Pack com deduplicação (remove blocos repetidos entre páginas)
uv run dograpper pack ./test-docs -o ./chunks --dedup both

# Dry-run para calibrar parâmetros sem escrever arquivos
uv run dograpper pack ./test-docs -o ./chunks --dry-run --dedup both --show-tokens

# Pack com formato JSONL (para pipelines RAG)
uv run dograpper pack ./test-docs -o ./chunks --format jsonl

# Pack com LLM Readiness Score
uv run dograpper pack ./test-docs -o ./chunks --score

# JSONL com contexto e score injetados
uv run dograpper pack ./test-docs -o ./chunks --format jsonl --context-header --score

# Rodar testes do scorer
uv run pytest tests/test_scorer.py -v

# Rodar testes do context-v1
uv run pytest tests/test_context_v1.py -v

# Rodar testes do formato JSONL
uv run pytest tests/test_jsonl_format.py -v

# Pack com bundle NotebookLM
uv run dograpper pack ./test-docs -o ./chunks --bundle notebooklm --context-header --score

# Pack JSONL para RAG
uv run dograpper pack ./test-docs -o ./chunks --format jsonl --cross-refs

# Pack delta (apenas mudanças)
uv run dograpper pack ./test-docs -o ./chunks --delta

# Inspecionar o que o LLM recebe por chunk (read-only)
uv run dograpper explain ./chunks docs_chunk_01

# Servir o pack como servidor MCP local (stdio)
uv run dograpper serve ./chunks

# Sync (download + pack delta)
uv run dograpper sync https://click.palletsprojects.com/en/stable/ -o ./test-docs

# Drift entre dois snapshots llm-readiness.json (markdown com marcador p/ PR comment)
uv run dograpper drift --new ./chunks/llm-readiness.json --old ./old-readiness.json --delta-manifest ./chunks/delta_manifest.json

# Gerar .dograpper.json por alvo (wizard interativo; --target + --yes para scripts)
uv run dograpper init --target notebooklm --yes

# Verificar dependências (wget, chromium)
uv run dograpper doctor

# Instalar deps faltantes (wget + chromium)
uv run dograpper doctor --install

# Diagnosticar libs de sistema faltantes
uv run dograpper doctor --check-system-libs

# Buildar binário standalone (requer extras 'build' e 'headless')
uv run --extra build --extra headless pyinstaller dograpper.spec --clean
```