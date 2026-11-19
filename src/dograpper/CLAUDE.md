# `src/dograpper/`

Pacote `dograpper`: o entry point e as linhas de contexto que protegem código de mais de um diretório (este arquivo carrega ao ler qualquer arquivo sob `src/dograpper/`). Contratos, gates e fluxo de sessão: `CLAUDE.md` da raiz.

## Módulos

```
src/dograpper/
├── cli.py                  # Entry point click, flags globais (--verbose, --quiet, --config)
```

## Arquivos de contexto

| Arquivo | Quando ler |
|---|---|
| `docs/superpowers/specs/2026-11-13-httrack-downloader-profile-design.md` | Antes de alterar `lib/httrack/` ou `commands/_httrack_profile.py`: desvios aprovados em relação ao HTTrack e roteiro dos próximos PRs do perfil. Evidência por comportamento (com citações do código do HTTrack) em `docs/discovery/httrack-mirroring-requirements.md` |
| `docs/discovery/firecrawl-header-behavior.md` | Antes de alterar os headers do fire-engine (`lib/fire_engine/fetcher.py`) ou o tratamento de `--user-agent` em `commands/download.py`: evidência do comportamento do Firecrawl e do curl_cffi (#136) e o comportamento-alvo decidido pelo mantenedor (opção B: `--user-agent` livre que derruba os `sec-ch-ua*`, mais `--header` repetível) |
| `docs/discovery/pack-performance-profile.md` | Antes de otimizar desempenho de `pack` ou `download` (cache de extração #21, worker pool #24): onde o tempo vai por etapa e por corpus, quantas vezes cada página é extraída, e os protótipos medidos |
| `tests/test_pack.py` | Antes de alterar qualquer coisa em `lib/chunker.py` ou `commands/pack.py` |
| `tests/test_page_layout.py` | Antes de alterar `lib/page_layout.py`, `commands/_page_layout.py` ou o despacho `--layout` de `commands/pack.py` (nomes, formato do `INDEX.md`, posse de `pages/`, flags rejeitadas) |
| `tests/test_query_packer.py` | Antes de alterar `lib/query_packer.py` ou a integração `--for-queries` em `commands/pack.py` |
| `tests/test_pack_error_pages.py` | Antes de alterar `utils/error_page.py` ou a etapa 6a-1 de `commands/pack.py` |
| `tests/test_pack_redirect_stubs.py` | Antes de alterar `utils/redirect_stub.py`, `utils/html_scan.py` ou a etapa 6a-3 de `commands/pack.py`; a fixture sai de `tests/fixtures/rustdoc_redirect/regenerate.sh` (rustdoc 1.96), nunca editar o HTML à mão |
| `tests/test_pack_challenge.py` | Antes de alterar `utils/challenge.py` ou a etapa 6a de `commands/pack.py` |
| `tests/test_pack_scoring.py` | Antes de alterar `lib/pack_scoring.py` ou a etapa 9c de `commands/pack.py` |
| `tests/test_pack_artifacts.py` | Antes de alterar `lib/pack_artifacts.py` ou as escritas de sidecar (9d, 10b, 10d–10e) de `commands/pack.py` |
| `tests/test_source_urls.py` | Antes de alterar `lib/source_urls.py`, a carga do manifest (`_load_url_manifest`) ou o passo 7c de `commands/pack.py` |
| `tests/test_sync_precedence.py` | Antes de alterar `commands/sync.py` ou `lib/config_loader.py` (mecanismo CLI_EXPLICIT_PARAMS) |
| `tests/test_download.py` | Antes de alterar qualquer coisa em `lib/wget_mirror.py`, `lib/spa_detector.py`, `lib/playwright_crawl.py` ou `commands/download.py` |
| `tests/test_fire_engine.py` | Antes de alterar `lib/fire_engine/fetcher.py`, `commands/_fire_engine_profile.py` ou o despacho `fire-engine`/guards de `--proxy`/`--impersonate` em `commands/download.py` |
| `tests/test_dedup.py` | Antes de alterar `utils/dedup.py` ou a integração de dedup em `commands/pack.py` |
| `tests/test_dry_run.py` | Antes de alterar `utils/dry_run_report.py` ou a lógica de dry-run em `commands/pack.py` |
| `tests/test_heading_extractor.py` | Antes de alterar `utils/heading_extractor.py` ou a lógica de context-header em `commands/pack.py` |
| `tests/test_httrack_changes.py` | Antes de alterar `lib/httrack/changes.py`, o `payload_md5` de `crawl.record_of` ou a escrita do `hts-changes.json` em `commands/_httrack_profile.py` |
| `tests/test_httrack_fetcher.py` | Antes de alterar `lib/httrack/fetcher.py`, `utils/challenge.py` ou `lib/httrack/escape.py` |
| `tests/test_httrack_mirror.py` | Antes de alterar `lib/httrack/mirror.py` ou o caminho de crawl de `commands/_httrack_profile.py` |
| `tests/test_httrack_naming.py` | Antes de alterar `lib/httrack/naming.py` ou `utils/portable_names.py` |
| `tests/test_markdown_render.py` | Antes de alterar o modo `markdown` de `utils/html_stripper.py`, `count_words(markdown=True)` em `utils/word_counter.py` ou a escolha md/plain em `lib/chunker.py`, `lib/page_layout.py`, `lib/pack_scoring.py` e `commands/pack.py` |
| `tests/test_link_extractor.py` | Antes de alterar `utils/link_extractor.py` ou a lógica de cross-refs em `commands/pack.py` |
| `tests/test_scorer.py` | Antes de alterar `utils/scorer.py` ou a lógica de score em `commands/pack.py` |
| `tests/test_readiness_report.py` | Antes de alterar `utils/readiness_report.py` ou a lógica de `--report` em `commands/pack.py` |
| `tests/test_api_reference.py` | Antes de alterar `utils/api_reference/` ou a integração `--api-records` em `commands/pack.py` e `lib/chunker.py`. As fixtures saem de `tests/fixtures/javadoc/src` via `tests/fixtures/javadoc/regenerate.sh` (javadoc 25) e de `tests/fixtures/sphinx/` via `tests/fixtures/sphinx/regenerate.sh` (Sphinx 9.2 num venv descartável, nunca dependência do projeto); nunca editar o HTML à mão |
| `tests/test_explain.py` | Antes de alterar `commands/explain.py` ou `utils/chunk_inspector.py` |
| `tests/test_mcp_serve.py` | Antes de alterar `commands/serve.py` ou `lib/mcp_server.py` (protocolo, tools e seus argumentos) |
| `tests/test_drift.py` | Antes de alterar `lib/readiness_diff.py` ou `commands/drift.py` (formatos markdown/text são literais testados) |
| `tests/test_bundle_notebooklm.py` | Antes de alterar lógica de `--bundle` |
| `tests/test_boundary_chunking.py` | Antes de alterar `_split_text_by_words` ou `utils/code_fence.py` |
| `docs/schema-v1.md` | Referência do schema `dograpper-context-v1` — manter sincronizado com `heading_extractor.py` e `chunker.py` |
| `tests/test_cli_help_coverage.py` | Antes de adicionar comando ou opção: ambos precisam de descrição/help escrito, dizendo o que fazem e o efeito do default |
| `tests/test_cli_regression.py` | Antes de adicionar/renomear subcomando ou flag no help top-level — o baseline `tests/fixtures/help_baseline.txt` precisa ser regenerado |
