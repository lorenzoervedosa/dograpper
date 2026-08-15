# 7. GitHub Action de frescor de contexto e subcomando drift

- Status: aceito
- Data: 2026-08-15

## Contexto

Contexto empacotado envelhece: a documentação upstream muda e o pack
versionado no repositório do usuário fica defasado sem ninguém perceber.
Era preciso (1) um mecanismo de CI que re-empacote periodicamente e
mostre **o que mudou no contexto** em cada PR, e (2) uma forma testável
de comparar dois snapshots de `llm-readiness.json`.

Runners de CI são stateless, então `pack --delta` só é incremental se o
estado (chunks + `.dograpper-manifest.json` + `llm-readiness.json`)
sobreviver entre execuções.

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
   pré-instalados), instala o dograpper via
   `pip install "${GITHUB_ACTION_PATH}"` no ref da própria action —
   simples de revisar e sem build/publicação de imagem.
3. **Pack versionado no repo do usuário** é a premissa de design: é o
   que dá significado ao `--delta` e ao diff de drift em runners
   stateless. O snapshot anterior é copiado para `$RUNNER_TEMP` antes do
   re-pack e usado como `--old`.

## Consequências

- PRs ganham um comentário único (upsert pelo marcador) com o drift de
  contexto; `mode: fail` permite travar o build quando há drift.
- Chunk ids (`docs_chunk_NN`) são posicionais e podem ser renumerados
  por mudanças de conteúdo upstream: o drift por chunk é best-effort,
  enquanto as listas de arquivos do `delta_manifest.json` são exatas.
- A action não tem runner nos testes: `tests/test_action_yml.py` guarda
  apenas a estrutura do `action.yml` (inputs, outputs, marcador,
  branding); a lógica de verdade testada é a do `drift`.
- Suposição documentada: runners ubuntu. Outros runners exigiriam
  instalar wget/gh por conta própria.
