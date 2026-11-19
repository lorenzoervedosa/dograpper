# `src/dograpper/commands/`

Subcomandos click: um módulo por comando; os `_*.py` são modos de um comando. Contratos, gates e fluxo de sessão: `CLAUDE.md` da raiz.

## Módulos

```
src/dograpper/commands/
│   ├── _fire_engine_profile.py # Modo `--downloader fire-engine` do download (ADR-0011): run_fire_engine() — run_profile() de _httrack_profile.py com CurlCffiFetcher (--proxy, --impersonate); fail-loud (curl_cffi ausente, onde quer que a 1ª sessão abra; desafio persistente → sugere --proxy/wget; SPA → wget --headless; --headless recusado)
│   ├── _httrack_profile.py # Modo `--downloader httrack` do download: resolve_profile() (opções do perfil, guarda sob wget, policy_kw), discovery_fetch() (robots antes do GET), run_profile() — cascata única dos perfis sobre o motor httrack (httrack, fire-engine), com o transporte, as mensagens e a regra de --headless como únicas diferenças: fetch semeado, ou crawl recursivo quando a descoberta não acha lista; relatório; fail-loud do start URL e do fallback de navegador; com o manifest anterior a execução é atualização (previous=), e _unreached() lista os arquivos dele não alcançados (nunca sob --cache 0); com --changes grava hts-changes.json em -o (atômico) e acrescenta a linha de resumo; run_httrack() — run_profile() sobre o Fetcher da stdlib (aviso de OpenSSL, --headless → Playwright não implementado)
│   ├── _page_layout.py     # Modo `pack --layout page` (ADR-0010): check_flags() (flags só-chunk na CLI ou no config, --bundle, --for-queries, --api-records, --format jsonl, --dedup ≠ off → exit 2), check_ownership() (pages/ sem INDEX.md → exit 1), write() (falha de escrita → exit 1)
│   ├── docs.py             # `dograpper docs`: build_page() (HTML puro, autocontido, gerado da árvore click) + make_server() (http.server em 127.0.0.1; porta ocupada falha, nunca troca de porta)
│   ├── doctor.py           # Detecta e instala deps pesadas (wget, chromium) em DOGRAPPER_HOME; --check-system-libs
│   ├── download.py         # Opções click + despacho do --downloader; cascade 4-layer do wget: llms.txt → sitemap → wget --mirror → Playwright bounded (layers 1+2 compartilhadas com os perfis httrack e fire-engine)
│   ├── drift.py            # Drift de contexto entre dois llm-readiness.json (+ delta_manifest.json opcional)
│   ├── eval.py             # Hit-rate empírico do pack JSONL: golden Q&A offline → BM25 → hit-rate@k/MRR por grade
│   ├── explain.py          # Preview read-only do que o LLM recebe por chunk (headers v1, cross-refs, grade)
│   ├── init.py             # Wizard de onboarding: gera .dograpper.json por alvo (notebooklm/rag/claude-project/claude-code); claude-code também escreve um SKILL.md stub em --skill-dir (nunca sobrescreve; pack não toca nele)
│   ├── pack.py             # Orquestração: list files → filter → chunk → write → summary; --layout chunk|page (modo page em _page_layout.py); --api-records (só jsonl) chama utils/api_reference/
│   ├── serve.py            # Servidor MCP local (stdio) sobre o pack JSONL: search/get/cross-refs/readiness
│   └── sync.py             # Subcomando sync (download + pack em um passo); repassa --downloader, --filter, as flags do perfil (PROFILE_OPTIONS de _httrack_profile.py), as flags do fire-engine (--proxy, --impersonate) e --layout
```

## Arquivos de contexto

| Arquivo | Quando ler |
|---|---|
| `tests/test_download_cascade.py` | Antes de alterar a orquestração de `commands/download.py` ou o threshold `MIN_URLS_TO_CONSIDER_DISCOVERED` |
| `tests/test_download_httrack_profile.py` | Antes de alterar `commands/_httrack_profile.py` ou o despacho `--downloader` de `commands/download.py` (flags `[httrack]`, mensagens fail-loud, injeção do `Fetcher` na descoberta) |
| `tests/test_init_wizard.py` | Antes de alterar `commands/init.py` ou os presets `TARGETS` |
| `tests/test_delta_artifacts.py` | Antes de alterar o portão de `--delta` em `commands/pack.py` ou `PACK_STATE_FILENAME` (semântica fixada na ADR-0008) |
| `tests/test_eval_command.py` | Antes de alterar `commands/eval.py` |
| `tests/test_docs_command.py` | Antes de alterar `commands/docs.py` (página gerada da árvore click, bind em 127.0.0.1, política de porta) |
| `tests/test_doctor.py` | Antes de alterar `commands/doctor.py` (detecção, `--install`, lock, `--check-system-libs`) |

## Comandos úteis

```bash
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
