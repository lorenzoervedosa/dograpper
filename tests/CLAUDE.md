# `tests/`

Suíte pytest. Qual teste ler antes de alterar um módulo está no CLAUDE.md do diretório do módulo. Contratos, gates e fluxo de sessão: `CLAUDE.md` da raiz.

- **Tempo:** linearidade só pela razão de CPU de `tests/linearity.py` (`assert_linear()`), nunca por limite de relógio, que quebra sob carga.

## Módulos

```
tests/
├── conftest.py             # Fixture `server`: http.server local roteirizado por path (usado por test_httrack_crawl, test_httrack_mirror, test_httrack_changes, test_download_cascade, test_delta_artifacts e os smoke tests de test_fire_engine); a resposta pode ser um callable dos headers do pedido (GET condicional)
├── linearity.py            # assert_linear()/cpu_time() — razão de tempo de CPU entre n e 4n (best of 3, GC desligado), fonte única dos testes de linearidade em entrada hostil (#126, #131, #135)
├── test_action_yml.py      # Guard estrutural do action.yml (inputs, outputs, marcador, branding)
├── test_api_reference.py   # --api-records: detecção/despacho, registros contêiner e membro sobre as fixtures javadoc 25 (tests/fixtures/javadoc) e Sphinx 9.2 autodoc (tests/fixtures/sphinx), markup não suportada, linearidade, CLI (erros de uso, dedup, --for-queries, --delta, serve)
├── test_api_reference_rustdoc.py # --api-records sobre a fixture rustdoc 1.96 (tests/fixtures/rustdoc): páginas de função/constante/static/macro (1 membro), crate e módulo, struct/enum/union/trait/alias (contêiner com cabeçalhos impl, membros com o cabeçalho do impl inerente), markup não suportada, linearidade e limites de nome/cabeçalho repetido, CLI (pack, serve)
├── test_api_reference_typedoc.py # --api-records sobre TypeDoc 0.28 (tests/fixtures/typedoc): páginas divididas e mantidas inteiras, registros contêiner (classe, módulo, namespace, enum, interface, type alias com membros; herdados por base) e membro (flags, assinaturas com parâmetros de tipo, sobrecargas, página de função/variável = 1 registro), markup não suportada (inclusive breadcrumb de 0.25–0.27), linearidade, CLI (pack, serve)
├── test_atomic_write.py    # atomic_write_bytes: cria pais e conteúdo; falha/KeyboardInterrupt não deixa arquivo final nem *.tmp; modo segue o umask corrente, sem nunca alterá-lo
├── test_boundary_chunking.py # Boundary-aware chunking: preservação de blocos estruturais
├── test_bundle_notebooklm.py # Bundle presets: notebooklm, rag-standard
├── test_claude_hooks.py    # Hooks de .claude/hooks como CLIs (JSON no stdin): guarda de git (bloqueia/libera, fail-open, amend por repo), lembretes de contrato e pós-commit
├── test_claude_md_inventory.py # Guard estrutural dos CLAUDE.md (raiz e aninhados de src/ e tests/): cada módulo e teste é entrada de árvore só do CLAUDE.md mais próximo acima dele, referências de caminho válidas, raiz aponta para cada aninhado
├── test_changelog.py       # Guard estrutural do CHANGELOG.md: seções válidas, ordem, versão por data (YYYY.M do mês do release), versão casando com pyproject (.devN sem release)
├── test_cli_help_coverage.py # Guard: todo comando tem descrição e toda opção tem help (alimenta `--help` e o `docs`)
├── test_cli_regression.py  # Baseline literal de `dograpper --help` (tests/fixtures/help_baseline.txt)
├── test_cli_smoke.py       # Help, flags obrigatórias, mutual exclusion
├── test_config.py          # load_config: arquivo ausente (devolve os params da CLI) e JSON inválido (erro); a precedência é pinada em test_sync_precedence.py e test_download.py
├── test_content_extractor.py # Extração inteligente: semantic, density, blacklist (elemento void ou não fechado não engole a página), edge cases, CLI; <pre> verbatim em bloco cercado com a linguagem, `<`/`>` escapados preservados
├── test_context_v1.py      # Formato dograpper-context-v1: JSON header, campos opcionais, schema
├── test_dedup.py           # Dedup: _split_blocks, _simhash, _hamming_distance, exact/fuzzy/both, regras que mantêm o bloco (mesma página, 1º token, só números), boilerplate entre páginas, blocos de código, definições de link, CLI
├── test_delta_artifacts.py # Delta como portão de mudança: artefatos completos, pack_state.json, fluxo sync (ADR-0008), árvore httrack com mtime do Last-Modified
├── test_delta_manifest.py  # Delta: diff_manifests e o contrato do delta_manifest.json; URL gravada pelo build_manifest (a buscada, sem credenciais, None com query fora da allowlist, nunca a de outro arquivo), records do build_manifest, manifest antigo legível, falha de escrita do manifest e do pack_state
├── test_dep_resolver.py    # Resolução de wget/chromium via DOGRAPPER_HOME (fallback para PATH, reload de módulo)
├── test_docs_command.py    # docs: âncoras por comando/opção, tipos de opção, página autocontida, escape HTML, bind/porta/--no-browser
├── test_docs_site.py       # Drift guard of site/: command page ↔ click command, {dograpper-options} directive per page naming that command, ### --flag headings are options of their command, every --flag on the site exists (FOREIGN_FLAGS allowlist)
├── test_doctor.py          # Doctor: detecção, --install (download verificado, lock, idempotência), --check-system-libs
├── test_download.py        # wget mock, SPA detector, manifest roundtrip e merge, UA/headers, run_wget_urls, bounded hydration; log do wget → URL por arquivo, resumo de falhas, --filter no wget, linhas de progresso, resolução do caminho do --manifest
├── test_download_cascade.py # Cascade 4-layer: layer-1/2/3/4 wins, below-threshold fall-through, headless, post-wget-i SPA, observability, --filter em cada camada (inclusive wget real), URLs do manifest por camada
├── test_download_httrack_profile.py # Perfil `--downloader httrack`: flags só-httrack com wget, caminhos fail-loud, precedência de config, wiring da descoberta e do crawl recursivo, Playwright sob a política (--headless, fallback de SPA com relatório próprio, front failure só sob --headless, fallback sem página salva mantém o motor, crawl raso por desafio sem navegador, flags da execução anterior com --headless)
├── test_drift.py           # Drift: compare_readiness, renders markdown/text (literais), CLI (first run, fail-on-drift, --output, snapshot ou delta manifest malformado = erro)
├── test_dry_run.py         # Dry-run: report generation, CLI integration, edge cases
├── test_e2e.py             # Integração ponta-a-ponta usando ./test-docs
├── test_fire_engine.py     # Perfil `--downloader fire-engine` (ADR-0011): CurlCffiFetcher com curl_cffi mockado (body, proxy, challenge, content-encoding, porta explícita, lib ausente inclusive sob --no-robots), guards de --proxy/--impersonate e despacho na CLI; smoke tests com o curl_cffi real contra o fixture `server` (identidade do navegador, --user-agent explícito, gzip, limites: bomba de descompressão, janela zstd, corpo cru, timeout por inatividade; proxy com credencial, nunca no erro nem no relatório; download ponta a ponta, segunda execução revalida, stop= antes do corpo, --cache 1/--updatehack/--do-not-recatch pela cascata compartilhada), pulados sem o extra `fire-engine`
├── test_eval_command.py    # Integração do `dograpper eval` sobre um pack JSONL (--json, erros de pré-requisito)
├── test_eval_harness.py    # evaluate(): hit-rate, MRR por rank, breakdown por grade, pares vazios
├── test_explain.py         # Explain preview: parsing de seções v1, sidecars, modos CLI, roundtrip pack→explain
├── test_generator.py      # page_generator: javadoc, MediaWiki após head longo, ordem/caixa de atributos, entidades, ausente, fora da janela
├── test_golden_qa.py       # generate_golden_qa: um par por chunk, heading mais profundo, determinismo
├── test_heading_extractor.py # Heading extraction, active headings, context header v1, CLI integration
├── test_httrack_browser.py # Navigator com o Fetcher real contra o fixture `server` e Route/Request de mentira (navegação entregue por fulfill, desafio abortado antes do render, redirect resolvido antes do goto com robots e escopo, re-base do start, subrecurso/iframe/popup//cdn-cgi/, nomes do motor, records, relink, datas, max_links, falha de escrita) e run_playwright_crawl(navigator=) com o Playwright mockado (contexto com o UA do perfil, semeado só com as sementes, about:blank entre páginas, goto na URL final, página recusada ou não-HTML nunca aberta, links no escopo com Referer e pré-filtro de extensão, link além do --depth sem decisão de filtro, erro do navegador no relatório)
├── test_httrack_changes.py # --changes: formato do hts-changes.json (escape, layout, resumo), classificação new/changed/unchanged/gone numa atualização (payload vs bytes relinkados, MD5 de texto, 304, alvo de redirect fora do host), -C0 sem índice, ordem das sementes, URL fora da allowlist, run que falha não escreve e mantém o relatório anterior, pack e manifest o ignoram
├── test_httrack_crawl.py   # fetch_url_list: só 2xx não-desafio escrito, robots, redirects (Referer/Sec-Fetch-* do alvo no fio), front_failed, max_links, filtro de extensão, conflito de escrita (inclusive a falha de uma escrita compartilhada por duas sementes), links reescritos entre páginas semeadas (inclusive os de scripts e de folhas semeadas), format_report, file_time/stamp (datas do HTTrack); --cache 0/1; --updatehack; --do-not-recatch; atualização (304, erro mantido sem retry, desafio, falha de transferência, arquivo apagado, redirect)
├── test_httrack_fetcher.py # Fetcher: retries, gate de Retry-After, pacing com relógio fake, decode gzip/deflate/br/zstd (bomba, truncado, multi-membro, limites de janela e frame), ordem dos headers, robots_for, is_challenge, revalidação sem retry, stop= derruba a conexão antes do corpo
├── test_httrack_links.py   # page_links/css_links/script_links: tabela de atributos, base href, meta refresh, nofollow, placeholders, FetchMeta por tag; -j/-%P (vetores de htsparse_selftest.c, contextos, flags), linearidade por razão de tempo de CPU; url_key; rewrite_links/rewrite_file_links: relativo/absoluto, base vazio, bytes preservados, links de scripts/folhas/-%P escritos como o HTTrack (escape, parênteses, query, &amp;); linearidade em páginas hostis (reescrita inclusa)
├── test_httrack_mirror.py  # mirror_site: escopo (host, diretório, /cdn-cgi/, extensão), depth, filtros, scripts varridos (-j/-%P), nofollow/robots, redirects (escopo, re-base do start, off-host), desafios nunca escritos, links reescritos (inclusive em scripts e folhas salvos), URLs do manifest, Referer/FetchMeta, max_links, progresso, determinismo, pack --cross-refs, datas do Last-Modified, --cache 0/1, --updatehack, --do-not-recatch; atualização (página, folha ou script mantido seguido pela cópia, start com erro ou desafio, redirect, nome reservado, download duas vezes)
├── test_httrack_naming.py  # NameRegistry: index.html, extensão .html, hash de query, colisão -N (inclusive só de caixa) e estabilidade, host IPv6, traversal/symlink rejeitados, thread-safety, reserve()
├── test_httrack_policy.py  # Policy: clamps, headers vs fixture httrack_wire, Referer e Sec-Fetch-* por link, esquema e UA, Accept-Encoding, br/zstd recusados sem API limitada, contexto TLS, ClientHello (OpenSSL >= 3.5), validadores e headers condicionais, padrões de -C
├── test_httrack_robots.py  # parse_robots: grupos, longest-match, Allow vence empate, wildcard/$, Crawl-delay, Sitemap, caps, corpo HTML sem regras
├── test_init_wizard.py     # Init wizard: presets por alvo, overwrite guard, modos interativo/não-interativo, stub SKILL.md do claude-code (nunca sobrescrito, sobrevive ao pack)
├── test_jsonl_format.py    # JSONL format: criação, validação JSON, word count, multi-chunk, registros de API, CLI
├── test_link_extractor.py  # Link extraction, cross-ref index, annotation, CLI integration
├── test_llms_txt_parser.py # fetch_llms_txt: markdown, bare URLs, comments, dedup, llms-full fallback, 404, UA, gzip
├── test_markdown_render.py # Markdown do md (#87): títulos, links, listas, tabelas (grade summary-table do Javadoc, <br> na célula), tabulação entre células no texto puro, tempo linear, offsets de título, contagem sem marcação, pack md/txt/jsonl/page
├── test_mcp_serve.py       # MCP server: protocolo (initialize/ping/tools), stdio loop, tools sobre pack, CLI
├── test_mediawiki.py       # Limpeza MediaWiki: navbox (inclusive aninhado), mw-editsection, caixas de manutenção vs nota, markup fora do corte intacto, caixa sem fim mantida, título que ficou vazio após o corte removido, link vermelho vira texto, página de outro gerador idêntica à extração de antes (sha256); versão como metadata (3 redações, categoria oculta, redação desconhecida), header nos dois layouts e registro JSONL (só MediaWiki), --dedup exact mantém a versão de cada página; aliases de redirect (alvo presente, ausente, dois aliases), pack pula e conta
├── test_page_layout.py     # Layout por página: nomes portáveis e colisões, títulos (sufixo, h1 fora do container, stem), INDEX.md literal, exit 2 de flags só-chunk (CLI e config), posse de pages/ (rebuild, exit 1, falha preserva), context header por página (uma vez, título, url, no máximo 5% do arquivo), links para páginas empacotadas e alias de redirect, delta/cross-refs/score/tokens/dry-run, sync
├── test_pack.py            # word_counter, ignore_parser (binários, --include-extensions), chunker, write_chunks (nomes além de 99), --for-queries, saída dentro da entrada, CLI integration
├── test_pack_challenge.py  # Pack: páginas de challenge (Cloudflare) detectadas, avisadas e fora dos chunks; falso positivo em prosa
├── test_pack_error_pages.py # Pack: páginas de erro HTTP salvas (404…) puladas, avisadas e contadas nos dois layouts e no dry-run; falsos positivos (página sobre 404, corpo que cita o status, página longa) mantidos
├── test_pack_artifacts.py  # Sidecars: cross-refs, delta manifest, snapshot de readiness, contagem de tokens
├── test_pack_reader.py     # load_chunks: campos, linhas malformadas, ordem determinística entre arquivos
├── test_pack_scoring.py    # score_chunks: ids, report pages, overrides de texto, tolerância a falha
├── test_progress.py       # ProgressReporter: formas lista fixa/total crescente, ETA após 10 URLs, throttle com relógio fake, finish() único, URL redigida, logger INFO
├── test_query_packer.py    # load_queries (comments/blanks, erros) e order_files_by_queries (determinismo, co-locação, tie-break)
├── test_readiness_report.py # Readiness report: find_removed_blocks, builders HTML/terminal, CLI --report
├── test_redact.py          # redact_url: userinfo removido, URL sem credenciais intacta, URL inválida falha seguro, caracteres de controle neutralizados, parâmetros de query com cara de credencial mascarados, recordable_url
├── test_retrieval.py       # BM25: tokenize, ranking, top-k, determinismo e tie-break por doc_id
├── test_scorer.py          # LLM Readiness Score: noise_ratio, boundary, context_depth, grades, CLI
├── test_sitemap_parser.py  # fetch_sitemap: namespace, urlset, gzip, sitemapindex recursivo, sub-sitemap cross-host (rejeitado fora do prefixo, aceito dentro), 404, UA
├── test_source_urls.py     # URLs de origem do pack --context-header: carga do manifest (explícito falha, default vira nota), marcadores HTTrack/saved-from, validação, precedência, resumo, pack de subdiretório do mirror
├── test_sync.py            # Pass-through de flags do sync para download/pack (sem precedência)
├── test_sync_precedence.py # Precedência de config através do ctx.invoke do sync (CLI explícita > JSON > defaults)
├── test_token_counter.py   # Token counting: aliases de encoding, encoding inválido levanta, count_tokens_file (encoding tolerante), format_token_summary, CLI --show-tokens
└── test_url_filter.py      # filter_urls: same-netloc, path-prefix canonicalizado, depth=0 unlimited, depth bounded, dedup; semântica das regras --filter
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

# Rodar testes de extração de conteúdo
uv run pytest tests/test_content_extractor.py -v

# Rodar testes de token counter
uv run pytest tests/test_token_counter.py -v

# Rodar testes de deduplicação
uv run pytest tests/test_dedup.py -v

# Rodar testes de dry-run
uv run pytest tests/test_dry_run.py -v

# Rodar testes do scorer
uv run pytest tests/test_scorer.py -v

# Rodar testes do context-v1
uv run pytest tests/test_context_v1.py -v

# Rodar testes do formato JSONL
uv run pytest tests/test_jsonl_format.py -v
```
