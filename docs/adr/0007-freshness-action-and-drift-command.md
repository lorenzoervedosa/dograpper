# 7. GitHub Action de frescor de contexto e subcomando drift

- Status: aceito
- Data: 2026-08-15

## Contexto

Contexto empacotado envelhece: a documentação upstream muda e o pack
versionado no repositório do usuário fica defasado sem ninguém perceber.
Era preciso (1) um mecanismo de CI que re-empacote periodicamente e
mostre **o que mudou no contexto** em cada PR, e (2) uma forma testável
de comparar dois snapshots de `llm-readiness.json`.

Runners de CI são stateless, então qualquer incrementalidade exige que o
estado (mirror de docs, chunks, `llm-readiness.json` e o
`.dograpper-manifest.json` da raiz do repo — ele é resolvido relativo ao
diretório de trabalho, não dentro de `chunks-dir`) sobreviva entre
execuções, versionado no repositório do usuário.

> **Atualização (ADR-0008)**: a limitação descrita abaixo foi corrigida
> — `pack --delta` virou um portão de mudança e não escreve mais
> artefatos parciais. A decisão 3 (a Action usa pack completo) segue
> valendo, agora por outro motivo. Ver
> [ADR-0008](0008-delta-as-a-change-gate.md).

**Limitação conhecida de `pack --delta`** (reproduzida empiricamente em
review; issue própria a ser aberta): `pack --delta --score` escreve um
`llm-readiness.json` PARCIAL — apenas os arquivos re-chunkados,
renumerados a partir de 01 — por cima do snapshot completo. Um diff de
snapshots após um delta pack compara completo-vs-parcial e é lixo a
partir da segunda execução; o snapshot versionado degrada
permanentemente. Como `sync` sempre invoca pack com `delta=True`, os
dois caminhos herdam o problema.

## Decisão

1. **Novo subcomando `dograpper drift`** — o núcleo testável. Compara
   dois `llm-readiness.json` (chaveados por `chunk_id`) e, opcionalmente,
   as listas exatas de arquivos do `delta_manifest.json`; renderiza
   markdown ou texto. A lógica é pura e stdlib-only em
   `lib/readiness_diff.py` (`compare_readiness`, `render_markdown`,
   `render_text`); o wrapper click fica em `commands/drift.py`.
   `--fail-on-drift` transforma drift em exit 1 (primeira execução conta
   como drift). O markdown começa sempre com o marcador
   `<!-- dograpper-drift -->`, usado para upsert do comentário de PR.
2. **Composite Action** (`action.yml` na raiz) em vez de Docker/JS
   action: bash puro sobre runners ubuntu (python3, wget, `gh` e `jq`
   pré-instalados), instala o dograpper num venv próprio (runners com
   python gerenciado — PEP 668 — abortam `pip install` direto) a partir
   de `"${GITHUB_ACTION_PATH}"`, o ref da própria action — simples de
   revisar e sem build/publicação de imagem.
3. **A action NUNCA usa `pack --delta` (nem `sync`)** por causa da
   limitação acima: quando há `url`, roda `dograpper download` (a
   incrementalidade mora na camada de download: wget timestamping +
   manifest) e em seguida SEMPRE um `pack --score` completo. Full pack
   sobre fontes inalteradas é determinístico: sem mudança upstream, o
   drift é vazio. O snapshot anterior é copiado para um diretório
   temporário por invocação (`mktemp -d` sob `$RUNNER_TEMP`) antes do
   re-pack e usado como `--old`.
4. **Drift de arquivos-fonte via git, não via `delta_manifest.json`**:
   como os docs são versionados, a action gera a seção de source drift
   do comentário com `git status --porcelain -- <input-dir>` (listas
   exatas) e a anexa ao report. A flag `--delta-manifest` do CLI
   permanece para uso local logo após um `pack --delta`, com o caveat de
   staleness documentado no README.
5. **Pack versionado no repo do usuário** é a premissa de design: é o
   que dá significado ao diff de drift (e ao download incremental) em
   runners stateless.

## Consequências

- PRs ganham um comentário único (upsert pelo marcador) com o drift de
  contexto; `mode: fail` permite travar o build quando há drift.
- Chunk ids (`docs_chunk_NN`) são posicionais e podem ser renumerados
  por mudanças de conteúdo upstream: o drift por chunk é best-effort,
  enquanto as listas de arquivos vindas do git (na action) e do
  `delta_manifest.json` (uso local) são exatas.
- O custo é re-empacotar tudo a cada execução — aceitável para docs
  (segundos) e o único caminho correto enquanto `pack --delta` escrever
  snapshot parcial.
- A action não tem runner nos testes: `tests/test_action_yml.py` guarda
  apenas a estrutura do `action.yml` (inputs, outputs, marcador,
  branding); a lógica de verdade testada é a do `drift`.
- Suposição documentada: runners ubuntu. Outros runners exigiriam
  instalar wget/gh por conta própria.
