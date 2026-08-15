# 6. Query-oriented packing via atribuição gulosa BM25

- Status: aceito
- Data: 2026-08-15

## Contexto

O chunking por `size` ordena arquivos alfabeticamente, o que espalha
conteúdo relacionado à mesma pergunta do usuário por chunks diferentes.
Para pipelines de retrieval, isso degrada hit-rate: a resposta a uma
query fica dividida entre fontes. A issue #22 pede que o `pack` aceite
uma lista de queries esperadas e co-localize no mesmo chunk os arquivos
que respondem à mesma query.

## Decisão

`pack --for-queries <arquivo>` reordena os arquivos ANTES do chunking
usando atribuição gulosa sobre o engine BM25 já existente em
`lib/retrieval.py` (`lib/query_packer.py`):

- Documentos indexados em ordem `sorted(rel_paths)`; cada query, na
  ordem do arquivo, reivindica seus hits com `score > 0` ainda não
  atribuídos, mantendo a ordem `(-score, doc_id)` do engine.
- Termos comuns da query são descartados antes da busca: termo presente
  em mais da metade do corpus (`COMMON_TERM_DF_RATIO = 0.5`) não carrega
  sinal de co-localização. Sem esse filtro, o idf do BM25 (sempre > 0
  nesta formulação, sem lista de stopwords) faz uma primeira query em
  linguagem natural ("how do I...") absorver quase todo o corpus via
  "how"/"a"/"to", degenerando a ordenação. O filtro vive em
  `query_packer` — `lib/retrieval.py` fica intacto (eval e serve
  mantêm sua semântica).
- O filtro só se aplica a corpora com `MIN_DOCS_FOR_DF_FILTER = 5` ou
  mais documentos: ele existe para impedir que uma query absorva um
  corpus GRANDE; abaixo do piso (ex.: subset de `--delta` com 1-2
  arquivos) todo termo relevante é "ubíquo" por construção e o filtro
  só geraria warnings espúrios de zero-match.
- Sob `--delta`, o corpus de ranking é o subset delta (consistente com
  a semântica de delta: só arquivos alterados são reprocessados).
- Arquivos sem match ficam por último, em ordem alfabética.
- Determinismo total: mesmo corpus + mesmo arquivo de queries = mesmo
  layout de chunks (tokenização estável, desempate por `doc_id`).
- `chunk_by_size` ganha `preserve_order` para respeitar a ordem do
  caller; o default (`False`) mantém o comportamento alfabético
  byte a byte.
- `--for-queries` + `--strategy semantic` é erro explícito: são duas
  políticas de agrupamento mutuamente exclusivas (por query vs. por
  diretório). Errar é honesto; não há override silencioso.

## Consequências

- Conteúdo que responde à mesma query fica no mesmo chunk, melhorando
  retrieval por chunk (RAG, NotebookLM sources).
- O arquivo de queries vira parte do input determinístico do pack —
  versionável junto com a config.
- Erros de arquivo ausente/vazio falham alto e cedo (`exit 1`), sem
  fallback silencioso para ordem alfabética.
- Query sem nenhum match gera warning (não erro) e o pack continua —
  inclusive quando todos os termos da query foram descartados como
  comuns (corpus pequeno ou query só de palavras ubíquas).
- Viés residual da primeira query: o filtro de termos comuns MITIGA a
  absorção gulosa, não a resolve. No corpus de docs do click (40
  arquivos), a primeira query ainda reivindicou 29/40 arquivos via
  termos de domínio moderadamente comuns abaixo do corte de 0.5
  ("options", "default", "command"). Atribuição gulosa favorece
  estruturalmente as queries mais cedo no arquivo — ordene as queries
  da mais específica para a mais genérica. Mitigações adicionais
  (corte menor, cap por query, round-robin) exigiriam novo ADR.
