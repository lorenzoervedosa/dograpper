# dograpper — Contexto do Projeto

## Visão geral

CLI em Python que implementa uma pipeline de engenharia de contexto
determinístico para ingestão em LLMs estáticos. Transforma documentação
HTML em contexto estruturado, dedupicado, pontuado e versionado — pronto
para NotebookLM, RAG pipelines, Claude Projects e fine-tuning. Três
subcomandos: `download` (espelha site via wget/playwright), `pack`
(processa e agrupa em chunks otimizados) e `sync` (download + pack delta).

## Stack técnica

- **Linguagem**: Python 3.10+
- **CLI framework**: click
- **Package manager**: uv
- **Filtro de arquivos**: pathspec (sintaxe gitignore)
- **Crawling SPA**: playwright (dependência opcional, import condicional)
- **Token counting**: tiktoken (dependência obrigatória)
- **Download padrão**: wget (dependência do sistema)
- **Testes**: pytest com click.testing.CliRunner

## Estrutura do repositório

```
src/dograpper/
├── cli.py                  # Entry point click, flags globais (--verbose, --quiet, --config)
├── commands/
│   ├── doctor.py           # Detecta e instala deps pesadas (wget, chromium) em DOGRAPPER_HOME; --check-system-libs
│   ├── download.py         # Cascade 4-layer: llms.txt → sitemap → wget --mirror → Playwright bounded
│   ├── drift.py            # Drift de contexto entre dois llm-readiness.json (+ delta_manifest.json opcional)
│   ├── eval.py             # Hit-rate empírico do pack JSONL: golden Q&A offline → BM25 → hit-rate@k/MRR por grade
│   ├── explain.py          # Preview read-only do que o LLM recebe por chunk (headers v1, cross-refs, grade)
│   ├── init.py             # Wizard de onboarding: gera .dograpper.json por alvo (notebooklm/rag/claude-project)
│   ├── pack.py             # Orquestração: list files → filter → chunk → write → summary
│   ├── serve.py            # Servidor MCP local (stdio) sobre o pack JSONL: search/get/cross-refs/readiness
│   └── sync.py             # Subcomando sync (download + pack em um passo)
├── lib/
│   ├── chunker.py          # Estratégias size e semantic, dataclasses Chunk/ChunkFile, write_chunks() (md, txt, jsonl)
│   ├── config_loader.py    # Merge com precedência: defaults < JSON < CLI (usa ctx.get_parameter_source)
│   ├── eval_harness.py     # evaluate() — hit-rate@k e MRR sobre pares golden, com breakdown por readiness grade
│   ├── golden_qa.py        # generate_golden_qa() — pares Q&A determinísticos a partir do breadcrumb de headings
│   ├── ignore_parser.py    # filter_files() com pathspec
│   ├── llms_txt_parser.py  # fetch_llms_txt() — parser do convention llmstxt.org (markdown links + bare URLs), stdlib-only
│   ├── manifest.py         # Dataclasses Manifest/ManifestEntry, load/save/build
│   ├── mcp_server.py       # Protocolo MCP stdlib-only: JSON-RPC 2.0 newline-delimited, tools/list, tools/call
│   ├── pack_reader.py      # load_chunks() — leitura tolerante dos chunks JSONL do pack em PackedChunk
│   ├── playwright_crawl.py # Crawler headless; hidratação bounded (domcontentloaded 10s + a[href] 5s + 500ms); aceita seed_urls
│   ├── query_packer.py     # load_queries() + order_files_by_queries() — ordenação gulosa por afinidade BM25 (pack --for-queries)
│   ├── readiness_diff.py   # compare_readiness() + render_markdown()/render_text() — diff de snapshots llm-readiness.json, stdlib-only
│   ├── retrieval.py        # build_index()/BM25Index — retrieval determinístico stdlib-only (tie-break por doc_id)
│   ├── sitemap_parser.py   # fetch_sitemap() — sitemap.xml + sitemapindex recursivo, gzip, same-netloc guard (SITEMAP_NS)
│   ├── spa_detector.py     # is_spa() via html.parser; small-sample branch (N<5) + errors='replace' encoding
│   ├── url_filter.py       # filter_urls() — same-netloc + path-prefix canonicalizado (rstrip('/')+'/' nos dois lados) + depth
│   └── wget_mirror.py      # run_wget_mirror() --mirror + run_wget_urls() -i; BROWSER_UA Chrome/120, --no-parent, --timestamping sempre
└── utils/
    ├── chunk_inspector.py  # Parsing read-only de chunks empacotados: seções v1, sidecars (readiness, cross-refs)
    ├── content_extractor.py # extract_content() — extração inteligente de HTML (semantic containers, density scoring, blacklist)
    ├── dedup.py            # deduplicate() — dedup cross-file via MD5 (exact) e SimHash (fuzzy)
    ├── dep_resolver.py     # resolve_wget()/resolve_browser_dir() — deps em DOGRAPPER_HOME (env lido no import)
    ├── dry_run_report.py   # generate_report() — relatório formatado para --dry-run
    ├── heading_extractor.py # extract_with_headings(), get_active_headings(), format_context_header() — formato dograpper-context-v1
    ├── html_stripper.py    # strip_html() via html.parser, descarta script/style, emite \n\n entre blocos HTML
    ├── link_extractor.py   # extract_links(), build_cross_ref_index(), annotate_cross_refs()
    ├── logger.py           # setup_logger() com suporte a verbose/quiet
    ├── readiness_report.py # PageReadiness, find_removed_blocks(), generate_html_report(), format_terminal_report() — relatório do --report
    ├── scorer.py           # LLM Readiness Score: noise_ratio, boundary_integrity, context_depth → grade A/B/C
    ├── token_counter.py    # count_tokens() — tiktoken opcional, fallback estimativa palavras→tokens
    └── word_counter.py     # count_words() e count_words_file()
tests/
├── test_action_yml.py      # Guard estrutural do action.yml (inputs, outputs, marcador, branding)
├── test_boundary_chunking.py # Boundary-aware chunking: preservação de blocos estruturais
├── test_bundle_notebooklm.py # Bundle presets: notebooklm, rag-standard
├── test_claude_md_inventory.py # Guard estrutural do CLAUDE.md: árvore completa e referências de caminho válidas
├── test_cli_regression.py  # Baseline literal de `dograpper --help` (tests/fixtures/help_baseline.txt)
├── test_cli_smoke.py       # Help, flags obrigatórias, mutual exclusion
├── test_config.py          # Precedência, JSON inválido, arquivo ausente
├── test_content_extractor.py # Extração inteligente: semantic, density, blacklist, edge cases, CLI
├── test_context_v1.py      # Formato dograpper-context-v1: JSON header, campos opcionais, schema
├── test_dedup.py           # Dedup: _split_blocks, _simhash, _hamming_distance, exact/fuzzy/both, CLI
├── test_delta_manifest.py  # Delta pack: reprocessamento incremental via manifest
├── test_dep_resolver.py    # Resolução de wget/chromium via DOGRAPPER_HOME (fallback para PATH, reload de módulo)
├── test_doctor.py          # Doctor: detecção, --install (download verificado, lock, idempotência), --check-system-libs
├── test_download.py        # wget mock, SPA detector, manifest roundtrip, UA/headers, run_wget_urls, bounded hydration
├── test_download_cascade.py # Cascade 4-layer: layer-1/2/3/4 wins, below-threshold fall-through, headless, post-wget-i SPA, observability
├── test_drift.py           # Drift: compare_readiness, renders markdown/text (literais), CLI (first run, fail-on-drift, --output)
├── test_dry_run.py         # Dry-run: report generation, CLI integration, edge cases
├── test_e2e.py             # Integração ponta-a-ponta usando ./test-docs
├── test_eval_command.py    # Integração do `dograpper eval` sobre um pack JSONL (--json, erros de pré-requisito)
├── test_eval_harness.py    # evaluate(): hit-rate, MRR por rank, breakdown por grade, pares vazios
├── test_explain.py         # Explain preview: parsing de seções v1, sidecars, modos CLI, roundtrip pack→explain
├── test_golden_qa.py       # generate_golden_qa: um par por chunk, heading mais profundo, determinismo
├── test_heading_extractor.py # Heading extraction, active headings, context header v1, CLI integration
├── test_init_wizard.py     # Init wizard: presets por alvo, overwrite guard, modos interativo/não-interativo
├── test_jsonl_format.py    # JSONL format: criação, validação JSON, word count, multi-chunk, CLI
├── test_link_extractor.py  # Link extraction, cross-ref index, annotation, CLI integration
├── test_llms_txt_parser.py # fetch_llms_txt: markdown, bare URLs, comments, dedup, llms-full fallback, 404, UA, gzip
├── test_mcp_serve.py       # MCP server: protocolo (initialize/ping/tools), stdio loop, tools sobre pack, CLI
├── test_pack.py            # word_counter, ignore_parser, chunker, write_chunks, CLI integration
├── test_pack_reader.py     # load_chunks: campos, linhas malformadas, ordem determinística entre arquivos
├── test_query_packer.py    # load_queries (comments/blanks, erros) e order_files_by_queries (determinismo, co-locação, tie-break)
├── test_readiness_report.py # Readiness report: find_removed_blocks, builders HTML/terminal, CLI --report
├── test_retrieval.py       # BM25: tokenize, ranking, top-k, determinismo e tie-break por doc_id
├── test_scorer.py          # LLM Readiness Score: noise_ratio, boundary, context_depth, grades, CLI
├── test_sitemap_parser.py  # fetch_sitemap: namespace, urlset, gzip, sitemapindex recursivo, cross-host reject, 404, UA
├── test_sync.py            # Pass-through de flags do sync para download/pack (sem precedência)
├── test_sync_precedence.py # Precedência de config através do ctx.invoke do sync (CLI explícita > JSON > defaults)
├── test_token_counter.py   # Token counting: fallback, tiktoken, format_summary, CLI integration
└── test_url_filter.py      # filter_urls: same-netloc, path-prefix canonicalizado, depth=0 unlimited, depth bounded, dedup
action.yml                  # Composite GitHub Action: download + full pack --score → drift → comentário de PR (nunca pack --delta; ver ADR-0007)
```

## Como rodar localmente

```bash
git clone <repo-url>
cd dograpper
uv sync --extra dev --extra headless   # deps + pytest + playwright (sem baixar browser)
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
| `docs/adr/` | Antes de reverter ou contornar uma decisão arquitetural (repomix, contagem por palavras, deps opcionais, query-oriented packing, delta na Action) |
| `.dograpper.json.example` | Ao mexer em `config_loader.py` ou no merge de configuração |
| `.docsignore.example` | Ao mexer em `ignore_parser.py` |
| `tests/test_pack.py` | Antes de alterar qualquer coisa em `lib/chunker.py` ou `commands/pack.py` |
| `tests/test_query_packer.py` | Antes de alterar `lib/query_packer.py` ou a integração `--for-queries` em `commands/pack.py` |
| `tests/test_sync_precedence.py` | Antes de alterar `commands/sync.py` ou `lib/config_loader.py` (mecanismo CLI_EXPLICIT_PARAMS) |
| `tests/test_download.py` | Antes de alterar qualquer coisa em `lib/wget_mirror.py`, `lib/spa_detector.py`, `lib/playwright_crawl.py` ou `commands/download.py` |
| `tests/test_download_cascade.py` | Antes de alterar a orquestração de `commands/download.py` ou o threshold `MIN_URLS_TO_CONSIDER_DISCOVERED` |
| `tests/test_llms_txt_parser.py` | Antes de alterar `lib/llms_txt_parser.py` ou o parser de `llms.txt` / `llms-full.txt` |
| `tests/test_sitemap_parser.py` | Antes de alterar `lib/sitemap_parser.py`, recursão `sitemapindex` ou same-netloc guard |
| `tests/test_url_filter.py` | Antes de alterar `lib/url_filter.py` (canonicalização de path-prefix ou semântica de `depth`) |
| `tests/test_content_extractor.py` | Antes de alterar `utils/content_extractor.py` |
| `tests/test_token_counter.py` | Antes de alterar `utils/token_counter.py` |
| `tests/test_dedup.py` | Antes de alterar `utils/dedup.py` ou a integração de dedup em `commands/pack.py` |
| `tests/test_dry_run.py` | Antes de alterar `utils/dry_run_report.py` ou a lógica de dry-run em `commands/pack.py` |
| `tests/test_heading_extractor.py` | Antes de alterar `utils/heading_extractor.py` ou a lógica de context-header em `commands/pack.py` |
| `tests/test_init_wizard.py` | Antes de alterar `commands/init.py` ou os presets `TARGETS` |
| `tests/test_link_extractor.py` | Antes de alterar `utils/link_extractor.py` ou a lógica de cross-refs em `commands/pack.py` |
| `tests/test_scorer.py` | Antes de alterar `utils/scorer.py` ou a lógica de score em `commands/pack.py` |
| `tests/test_readiness_report.py` | Antes de alterar `utils/readiness_report.py` ou a lógica de `--report` em `commands/pack.py` |
| `tests/test_context_v1.py` | Antes de alterar o formato `dograpper-context-v1` em `utils/heading_extractor.py` |
| `tests/test_jsonl_format.py` | Antes de alterar a escrita JSONL em `lib/chunker.py` |
| `tests/test_delta_manifest.py` | Antes de alterar `lib/manifest.py` ou lógica de `--delta` |
| `tests/test_retrieval.py` | Antes de alterar `lib/retrieval.py` (BM25, tokenização ou tie-break determinístico) |
| `tests/test_pack_reader.py` | Antes de alterar `lib/pack_reader.py` ou o formato JSONL que ele consome |
| `tests/test_golden_qa.py` | Antes de alterar `lib/golden_qa.py` ou o template de perguntas |
| `tests/test_eval_harness.py` | Antes de alterar `lib/eval_harness.py` (hit-rate, MRR, breakdown por grade) |
| `tests/test_eval_command.py` | Antes de alterar `commands/eval.py` |
| `tests/test_drift.py` | Antes de alterar `lib/readiness_diff.py` ou `commands/drift.py` (formatos markdown/text são literais testados) |
| `tests/test_action_yml.py` | Antes de alterar `action.yml` (inputs/outputs/marcador exigidos) |
| `tests/test_bundle_notebooklm.py` | Antes de alterar lógica de `--bundle` |
| `tests/test_boundary_chunking.py` | Antes de alterar `_split_text_by_words` |
| `docs/schema-v1.md` | Referência do schema `dograpper-context-v1` — manter sincronizado com `heading_extractor.py` e `chunker.py` |
| `tests/test_doctor.py` | Antes de alterar `commands/doctor.py` (detecção, `--install`, lock, `--check-system-libs`) |
| `tests/test_dep_resolver.py` | Antes de alterar `utils/dep_resolver.py` ou a semântica de `DOGRAPPER_HOME` |
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

## Padrões de commit e branch

- Commits em português ou inglês, sem preferência rígida
- Formato: `tipo: descrição curta` (ex: `feat: implementar estratégia semantic no chunker`, `fix: corrigir contagem de palavras em arquivos vazios`, `refactor: extrair módulos para lib/`)
- Branch principal: `main`
- Feature branches: `feat/nome-curto` ou `fix/nome-curto`

## CI/CD

`.github/workflows/ci.yml` roda a suíte em push para `main` e em pull request,
numa matriz Python 3.10 / 3.12, com `uv sync --extra dev --extra headless`
(o extra `headless` é necessário porque `tests/test_doctor.py` faz patch de
`playwright.__main__` — nenhum browser é baixado). `.github/workflows/release.yml`
cuida do release. Para replicar o CI localmente:

```bash
uv sync --extra dev --extra headless
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