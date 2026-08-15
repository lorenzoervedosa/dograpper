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
- Query sem nenhum match gera warning (não erro) e o pack continua.
