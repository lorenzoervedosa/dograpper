# 8. `pack --delta` é um portão de mudança, não um pack parcial

- Status: aceito
- Data: 2026-08-15
- Atualiza: [ADR-0007](0007-freshness-action-and-drift-command.md)

## Contexto

`pack --delta` reduzia `filtered_paths` aos arquivos added+modified e
seguia o pipeline normal com esse subconjunto. Três consequências,
reproduzidas empiricamente (issue #39):

1. **Artefatos parciais por cima dos completos.** Os chunks são
   numerados posicionalmente a partir de `01`, então um delta run
   reescreve `docs_chunk_01.*` com o conteúdo de outra fonte e
   `llm-readiness.json` passa a conter só os chunks regerados. Repro:
   pack completo de 3 docs → snapshot com 3 chunks; editar 1 arquivo;
   `pack --delta --score` → snapshot com 1 chunk, e o conteúdo dos
   outros dois some do pack. `cross_refs.json` e `IMPORT_GUIDE.md`
   sofrem o mesmo efeito.
2. **`pack` nunca persistia estado.** Só `download` chamava
   `save_manifest`. Num fluxo pack-only (docs mantidos à mão), todo run
   `--delta` via o corpus inteiro como "added".
3. **Chaves incompatíveis.** O diff era feito contra
   `.dograpper-manifest.json`, cujas chaves são URL-relativas (o prefixo
   `<netloc>/` que o wget cria é removido), enquanto o pack comparava
   com caminhos relativos ao `input_dir`. No fluxo download→pack nada
   casava: o diff reportava *todos* os arquivos como added **e** todos
   como removed. Esse defeito mascarava o (1) — acidentalmente fazia
   `sync` empacotar tudo.

A opção "delta só no corpo, artefatos sempre completos" não é
implementável sem um cache de texto extraído: as fronteiras de chunk se
movem quando a contagem de palavras de um arquivo muda, então reescrever
artefatos completos exige re-chunkar tudo de qualquer forma.

## Decisão

1. **O diff decide SE o run acontece, não O QUE ele empacota.** Sem
   mudança relevante, `pack --delta` imprime `Delta: no files changed
   since last pack. Nothing to do.` e sai sem escrever nada. Com
   mudança, roda um **pack completo**. Todo artefato que um delta run
   escreve é tão completo quanto o de um pack normal, e a numeração
   posicional dos chunks continua válida.
2. **O portão só considera arquivos que este pack incluiria.** O diff é
   estreitado para o conjunto pós-`.docsignore`/`--ignore`
   (`manifest.narrow_diff_to_paths`), preservando a propriedade antiga
   de que churn em arquivos ignorados não dispara trabalho. Remoções
   sempre disparam: um arquivo que sumiu muda a saída mesmo não podendo
   mais ser casado com a lista atual.
3. **O estado do delta pertence ao pack, não ao download.**
   `pack --delta` compara contra `<output-dir>/pack_state.json`, escrito
   ao final de um run bem-sucedido. Não pode ser
   `.dograpper-manifest.json`: `download` reescreve esse arquivo *depois*
   de baixar, então ele sempre descreve a árvore atual e responderia
   "nada mudou" justamente no run que precisa empacotar — `sync`
   pararia de gerar chunks. `--manifest` volta ao seu único papel
   restante: resolver as URLs de origem para `--context-header`.
4. **Estado gravado só depois da escrita.** Um run que falha no meio não
   marca arquivos como empacotados; `--dry-run` nunca grava estado.

## Consequências

- `sync` (que sempre invoca `pack --delta`) deixa de corromper os
  artefatos, e passa a ser um no-op barato quando nada mudou.
- Perde-se o reprocessamento por arquivo. Ele nunca foi seguro: o ganho
  vinha acompanhado da corrupção descrita acima. O custo real é
  re-empacotar quando *algo* mudou — segundos para documentação, o mesmo
  custo que a ADR-0007 já aceitou para a Action.
- O caveat da ADR-0007 sobre `pack --delta --score` escrever snapshot
  parcial deixa de valer: um snapshot gerado por delta run agora é
  comparável com qualquer outro. A Action continua usando pack completo
  (não faz parte desta mudança).
- `pack_state.json` é um novo artefato no diretório de chunks. Como o
  pack é versionado no repositório do usuário (premissa da ADR-0007), o
  estado viaja junto e o portão funciona em runners stateless.
- `--delta` no primeiro run continua vendo tudo como "added" — agora por
  ausência de `pack_state.json`, não por chaves incompatíveis.
