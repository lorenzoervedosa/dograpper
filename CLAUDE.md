# dograpper — Contexto do Projeto

## Visão geral

CLI em Python que implementa uma pipeline de engenharia de contexto
determinístico para ingestão em LLMs estáticos. Transforma documentação
HTML em contexto estruturado, dedupicado, pontuado e versionado — pronto
para NotebookLM, RAG pipelines, Claude Projects e fine-tuning. Três
subcomandos centrais: `download` (espelha site via wget/playwright, ou os perfis
httrack e fire-engine), `pack` (processa e agrupa em chunks otimizados, ou um
arquivo por página) e `sync` (download + pack delta); em volta deles, `init`,
`doctor`, `explain`, `serve`, `eval`, `drift` e `docs`.

## Stack técnica

- **Linguagem**: Python 3.10+
- **CLI framework**: click
- **Package manager**: uv
- **Filtro de arquivos**: pathspec (sintaxe gitignore)
- **Crawling SPA**: playwright (dependência opcional, import condicional)
- **Token counting**: tiktoken (dependência obrigatória)
- **Download padrão**: wget (dependência do sistema); perfil opt-in `--downloader httrack` (Python puro, `lib/httrack/`; extra `httrack` = brotli + zstandard; exige OpenSSL >= 3.5 para o handshake idêntico); perfil opt-in `--downloader fire-engine` (o mesmo motor sobre curl_cffi, `lib/fire_engine/`; extra `fire-engine` = curl_cffi + brotli + zstandard, import condicional — ADR-0011)
- **Testes**: pytest com click.testing.CliRunner

## Estrutura do repositório

A árvore de módulos e a tabela "Arquivos de contexto" de cada diretório moram
num CLAUDE.md aninhado. O Claude Code o carrega no primeiro `Read` de um arquivo
da subárvore, junto com os dos diretórios intermediários; `Grep` não carrega, e
depois de uma compactação ele volta no próximo `Read`. Módulo ou teste novo
entra no CLAUDE.md mais próximo acima dele; linha de contexto que protege
código de mais de um diretório entra no diretório mais baixo que contém todo
esse código (guarda: `tests/test_claude_md_inventory.py`).

- `src/dograpper/CLAUDE.md` — `cli.py` e as linhas de contexto que cruzam diretórios
- `src/dograpper/commands/CLAUDE.md` — subcomandos click, exemplos de CLI e build do binário
- `src/dograpper/lib/CLAUDE.md` — pipeline (chunker, config, manifest, descoberta, wget, Playwright, retrieval, eval)
- `src/dograpper/lib/httrack/CLAUDE.md` — motor do perfil httrack
- `src/dograpper/lib/fire_engine/CLAUDE.md` — transporte curl_cffi do perfil fire-engine
- `src/dograpper/utils/CLAUDE.md` — helpers e `utils/api_reference/`
- `tests/CLAUDE.md` — arquivos da suíte e comandos de pytest

Fora de `src/` e `tests/`:

```
action.yml                  # Composite GitHub Action: download + full pack --score → drift → comentário de PR (nunca pack --delta; ver ADR-0007)
```

## Como rodar localmente

```bash
git clone <repo-url>
cd dograpper
uv sync --extra dev --extra headless --extra httrack --extra fire-engine   # deps + pytest + playwright (sem baixar browser) + brotli/zstd do perfil httrack + curl_cffi do fire-engine
uv run dograpper --help    # verifica que está funcionando
```

Para testar download real:
```bash
uv run dograpper download https://click.palletsprojects.com/en/stable/ -o ./test-docs -d 2
uv run dograpper pack ./test-docs -o ./chunks
```

## Arquivos de contexto importantes

As linhas que protegem código estão nos CLAUDE.md aninhados (ver "Estrutura do
repositório"); aqui ficam as que protegem arquivos da raiz.

| Arquivo | Quando ler |
|---|---|
| `README.md` | **Sempre.** Comportamento de cada subcomando, flags, formato de config e exemplos de uso. É a fonte de verdade do contrato observável. |
| `docs/adr/` | Antes de reverter ou contornar uma decisão arquitetural (repomix, contagem por palavras, deps opcionais, query-oriented packing, delta na Action, delta como portão de mudança, registros de referência de API, layout por página, downloader fire-engine) |
| `GLOSSARY.md` | Ao nomear conceitos de entrada/saída (página, registro, chunk, símbolo, contêiner, membro, target; do lado do download: mirror, downloader, manifest, update, kept file, link rewriting, change report) em código, docs, issues ou PRs |
| `tests/test_claude_hooks.py` | Antes de alterar `.claude/hooks/` ou o wiring em `.claude/settings.json` (decisões de bloqueio, mapa de contratos dos lembretes) |
| `tests/test_action_yml.py` | Antes de alterar `action.yml` (inputs/outputs/marcador exigidos) |
| `CHANGELOG.md` | **Toda vez que a mudança for observável pelo usuário.** O cabeçalho do arquivo define a regra: o que ganha entrada, em qual seção, e quando (no mesmo PR, em `## [Unreleased]`) |

## Contratos invioláveis

Quebrar qualquer um é bug crítico. Cada contrato aponta o teste que o pina e a
ADR que o registra; "sem teste" é lacuna conhecida, não licença. Contrato novo
ou alterado entra aqui no mesmo PR, com teste — e ADR se for decisão
arquitetural. A numeração é estável (outros arquivos citam "contrato N").

1. **Dependências com problemas de compatibilidade devem ser opcionais.** Libs que exigem binários do sistema, compilação nativa problemática, ou que não funcionam em todos os ambientes (ex: playwright, que requer `playwright install chromium`) devem ser import condicional com mensagem de erro amigável. Dependências pip puras podem ser obrigatórias sem restrição.
   ADR: `docs/adr/0004-optional-native-deps-conditional-import.md` · Testes: `tests/test_fire_engine.py` (curl_cffi ausente → erro amigável) e `test_undecodable_encoding_when_decoder_missing` (`tests/test_httrack_fetcher.py`, brotli/zstandard); o import condicional do playwright segue guardado por revisão.
2. **Não usar repomix.** A concatenação de chunks é feita em Python puro. Essa é uma decisão arquitetural tomada — não reverter.
   ADR: `docs/adr/0002-no-repomix-pure-python-concatenation.md` · Teste: nenhum (repomix não está em `pyproject.toml`).
3. **Contagem de palavras, não bytes.** O chunking usa `len(text.split())` como métrica. Os limites do NotebookLM são em palavras. Não mudar para bytes.
   ADR: `docs/adr/0003-word-count-not-bytes.md` · Testes: `tests/test_pack.py` (word_counter, chunker), `tests/test_boundary_chunking.py`.
4. **Playwright nunca é import top-level.** Sempre import condicional dentro da função, com mensagem de erro amigável se ausente. Dependências pip puras (tiktoken, etc.) podem ser import top-level normalmente.
   ADR: `docs/adr/0004-optional-native-deps-conditional-import.md` · Teste: nenhum (guardado por revisão).
5. **Testes existentes não podem quebrar.** Qualquer mudança deve manter `uv run pytest tests/ -v` passando integralmente antes de commitar.
   Pinado por: `.github/workflows/ci.yml` (matriz 3.10/3.12) e pelos gates abaixo.
6. **Config precedência é inviolável**: defaults do click < `.dograpper.json` < flags CLI explícitas. Usa `ctx.get_parameter_source()` para distinguir. Não simplificar esse mecanismo.
   Testes: `tests/test_config.py`, `tests/test_sync_precedence.py`, `tests/test_download_httrack_profile.py` (precedência das flags do perfil).
7. **Encoding tolerante.** Leitura de arquivos sempre com `errors="replace"`. O CLI não deve crashar por causa de caracteres estranhos em HTMLs baixados.
   Testes: `test_spa_detector_tolerates_invalid_utf8` (`tests/test_download.py`), `test_tolerant_encoding` (`tests/test_token_counter.py`), `test_pack_cli_excludes_binary_files` (`tests/test_pack.py`).
8. Ignorar (não ler) tudo que estiver em `./temporario/`
   Pinado por: `.claude/hooks/guard-temporario.sh` (PreToolUse; bloqueia escrita e edição, não leitura) · Teste: nenhum.
9. **Mudança observável pelo usuário exige entrada no `CHANGELOG.md`**, em `## [Unreleased]`, no mesmo PR. Observável = superfície do CLI (comando, flag, output, exit code), arquivos escritos ou seu formato, comportamento da Action, ou requisito de instalação. `refactor`/`test`/`chore`/`ci`/`build`/`docs` não geram entrada — se gerariam, o commit foi tipado errado. A regra completa está no cabeçalho do `CHANGELOG.md`; `tests/test_changelog.py` guarda a parte mecânica.
   Testes: `tests/test_changelog.py` (estrutura) · lembrete: `.claude/hooks/commit-doc-check.sh` em `feat`/`fix` sem `CHANGELOG.md`.
10. **Release** (versão por data: `YYYY.M`, ex. `2027.3`; outro release no mesmo mês, `2027.3.1`; mês sem zero à esquerda, que o empacotamento Python normaliza): renomear `## [Unreleased]` para `## [YYYY.M] - AAAA-MM-DD`, abrir uma `## [Unreleased]` vazia e pôr o mesmo `YYYY.M` em `version` no `pyproject.toml` no mesmo commit; a tag é `vYYYY.M`. `dograpper --version` lê o metadata do pacote instalado — tag sem bump publica binário que se identifica errado. Até o primeiro release, `version` é `0.0.0.dev0` e o CHANGELOG só tem `## [Unreleased]`.
    Testes: `test_newest_release_matches_the_packaged_version` e `test_release_headings_use_the_dated_version_of_their_month` (`tests/test_changelog.py`).

## Gates (dois níveis)

A suíte inteira roda em ~55 s, então o contrato 5 vale por commit; o nível
rápido é só para iterar.

1. **Rápido (iteração):** `uv run pytest <testes dos módulos tocados> -q` — os
   arquivos das tabelas "Arquivos de contexto" dos CLAUDE.md acima de cada
   módulo do diff. Não vale quando o diff toca `lib/chunker.py`, `lib/config_loader.py`,
   `utils/heading_extractor.py`, `commands/pack.py` ou `cli.py`: são
   exercitados por dezenas de arquivos de teste (`commands/pack.py` é
   importado direto por 19, `cli.py` por 26) — rode o nível 2 desde o primeiro
   teste.
2. **Completo (cada commit, obrigatório antes de push/PR):** `uv run pytest tests/ -q`
   com `uv sync --extra dev --extra headless --extra httrack --extra fire-engine`, como o CI. Cada
   commit da branch passa sozinho; quem monta o lote confere numa worktree
   descartável (`git worktree add --detach <dir> <sha>`).

Nunca mascare o exit code com pipe: `uv run pytest tests/ -q | tail` devolve o
status do `tail`. Rode sem pipe, ou leia `${PIPESTATUS[0]}` (bash) /
`${pipestatus[1]}` (zsh), ou use `set -o pipefail`.

## Sessões paralelas (worktrees + PR por lote)

Várias sessões de agente costumam rodar ao mesmo tempo neste repositório. O
merge é sempre do mantenedor, por PR revisado; nenhuma sessão faz merge local
nem push na `main` (o guarda `.claude/hooks/block-dangerous-git.py` bloqueia).

- **Isolamento:** cada sessão trabalha numa worktree própria em
  `.claude/worktrees/<nome>`, numa branch curta criada da base do lote
  (`chore/<lote>-base` quando existe, senão `origin/main`). Nunca no checkout
  principal.
- **Trabalho que você não reconhece** (órfão, inacabado, divergência num
  rebase) pode ser de outra sessão: deixe como está e reporte; ação
  destrutiva só depois de confirmar com o usuário (regra global).
- **Entrega:** um PR combinado por lote. Cada sessão entrega commits atômicos
  na sua branch, sem push; a sessão integradora junta as branches, confere o
  nível 2 em cada commit e abre o PR. Mudança que outra sessão também toca
  (árvore e tabela deste arquivo, `CHANGELOG.md`) entra como bloco ou linha
  isolada, para o merge ficar mecânico.
- **PR já publicado e a `main` andou:** prefira `git merge origin/main` na
  branch do PR. Rebase + `push --force-with-lease` reescreve commits
  publicados e exige consentimento explícito a cada vez.
- **Mutex — só se duas sessões escrevem a MESMA branch remota** (no fluxo
  padrão só a integradora dá push, e ele não é usado). A seção crítica cobre
  fetch + rebase/merge + push, nunca o desenvolvimento, e roda num único
  comando de shell, com a liberação armada logo após o `mkdir`:

  ```bash
  until mkdir /tmp/dograpper-push-lock 2>/dev/null; do sleep 15; done
  trap 'rmdir /tmp/dograpper-push-lock 2>/dev/null' EXIT; trap 'exit 130' INT TERM HUP
  git fetch && git merge origin/main && uv run pytest tests/ -q && git push
  ```

  Lock com mais de 15 min é órfão: remova-o e registre em `docs/DECISIONS.md`.
- **Limpeza local pós-merge** (o `delete_branch_on_merge` do GitHub está
  desligado; worktree e branch local nunca são limpas sozinhas):
  1. `git fetch --prune`.
  2. Confirme que o trabalho está na `main`:
     `git merge-base --is-ancestor <branch> origin/main`. Se o lote foi
     montado por cherry-pick (SHAs novos), confira com
     `git cherry origin/main <branch>` — só linhas `-` = patches já na `main`;
     sobrou `+`, pare e pergunte.
  3. `git worktree remove .claude/worktrees/<nome>` (sem `--force`: se
     recusar por mudança não commitada, pare e pergunte) e `git worktree prune`.
  4. `DOGRAPPER_BRANCH_MERGED=1 git branch -D <branch>` — pré-autorizado só
     depois do passo 2; branch remota idem com
     `DOGRAPPER_BRANCH_MERGED=1 git push origin --delete <branch>`.

## Armadilhas do ambiente

- **zsh:** `$T:s…` é modificador (`:s`, `:h`, `:t`…), escreva `${T}:`; glob sem aspas num argumento (`--include=*.py`) que não casa aborta o comando com "no matches found", use aspas.
- **Amend:** só de HEAD não publicado, numa forma que `block-dangerous-git.py` localiza: `git commit --amend` no cwd, `cd DIR && [git add … &&] git commit --amend` ou `git -C DIR commit --amend`; `;`, `$VAR` ou subshell bloqueiam. HEAD publicado exige consentimento (`DOGRAPPER_USER_APPROVED=1`).
- **Publicar:** push de branch nova e abertura de PR exigem ok explícito do usuário a cada vez, mesmo com o lote pronto.
- **`git cherry` após cherry-pick com conflito:** o patch resolvido ganha outro patch-id e aparece como `+` mesmo já estando na `main`; compare com `git range-diff <base>..<branch> <base>..origin/main` (`<base>` = `git merge-base <branch> origin/main`) antes do `branch -D`.
- **Worktree que é o cwd:** removê-la quebra o próximo comando do shell; limpe por `git -C <checkout principal> worktree remove …`, como último passo.
- **`pgrep -f` / `pkill -f`:** um padrão que aparece no próprio comando casa com o shell que o roda e o mata; use `'[d]ograpper serve'` ou o PID.
- **Verificação por commit sem `git stash`** (a pilha é compartilhada entre worktrees): worktree descartável `--detach` com os patches cumulativos aplicados, sem editar nada enquanto a suíte roda.
- **Hooks numa worktree:** a sessão aberta no checkout principal roda os hooks de `$CLAUDE_PROJECT_DIR` (o checkout principal); mudança em `.claude/hooks/` feita numa worktree só vale para ela depois do merge.

## Padrões de commit e branch

- Commits em português ou inglês, sem preferência rígida
- Formato: `tipo: descrição curta` (ex: `feat: implementar estratégia semantic no chunker`, `fix: corrigir contagem de palavras em arquivos vazios`, `refactor: extrair módulos para lib/`)
- Branch principal: `main`
- Feature branches: `feat/nome-curto` ou `fix/nome-curto`

## CI/CD

`.github/workflows/ci.yml` roda a suíte em push para `main` e em pull request,
numa matriz Python 3.10 / 3.12, com `uv sync --extra dev --extra headless --extra httrack --extra fire-engine`
(o extra `headless` é necessário porque `tests/test_doctor.py` faz patch de
`playwright.__main__` — nenhum browser é baixado; sem o extra `httrack`, os
testes de decode br/zstd são pulados em silêncio; sem o extra `fire-engine`,
os smoke tests do `curl_cffi` real em `tests/test_fire_engine.py` também).
`.github/workflows/release.yml` cuida do release. Para replicar o CI localmente:

```bash
uv sync --extra dev --extra headless --extra httrack --extra fire-engine
uv run pytest tests/ -v
```

## Manutenção do harness (obrigatório)

Documentos vivos que DEVEM acompanhar o código, no mesmo PR da mudança. Hooks
em `.claude/settings.json` lembram você: `.claude/hooks/harness-reminder.sh`
ao editar arquivo de contrato, `.claude/hooks/commit-doc-check.sh` depois de
cada `git commit` (só lembretes, nunca bloqueiam; testes em
`tests/test_claude_hooks.py`). Ao lado deles, `.claude/hooks/block-dangerous-git.py`
bloqueia git destrutivo sem consentimento — modelo de ameaça: guarda best-effort
contra comando ACIDENTAL de agente ou pessoa, não sandbox; bypass deliberado
(alias já no git config, git chamado de outra linguagem, `eval` de string
montada) fica fora por design, e o controle continua sendo as regras de
consentimento.

| Documento | Atualize quando |
|---|---|
| `CHANGELOG.md` | A mudança é observável pelo usuário (regra no cabeçalho do arquivo) |
| `README.md` | Muda comando, flag, config, output, exit code ou arquivo escrito — é o contrato observável |
| `docs/schema-v1.md` | Muda campo do header `dograpper-context-v1` ou do registro JSONL (`utils/heading_extractor.py`, `lib/chunker.py`, `utils/api_reference/`) |
| `docs/adr/` | Decisão arquitetural nova, revertida ou contornada, ou mudança de contrato inviolável. ADR supersedido nunca é apagado: marque `Superseded by` |
| `docs/DECISIONS.md` | Decisão autônoma de sessão: escolha entre leituras do pedido, desvio do brief, convenção nova, pendência para o mantenedor |
| `docs/DEBT.md` | Achado de review aceito sem fix (com o gatilho do fix); item corrigido é marcado ✅, não apagado |
| `GLOSSARY.md` | Termo de domínio novo, renomeado ou com sentido mudado (skill `domain-modeling`) |
| `docs/glossario.md` | Jargão técnico explicado ao mantenedor (seção "Glossário vivo" abaixo) |
| `docs/superpowers/` | Spec ou plano de uma fase nova |
| `docs/audits/structural.md` | Cada execução de `/structural-audit` acrescenta uma entrada datada no fim (append-only: nunca edite entrada antiga) |
| `.claude/hooks/` | Muda o conjunto de arquivos de contrato: atualize o mapa de `harness-reminder.sh` e a regex de `commit-doc-check.sh` juntos |
| Este `CLAUDE.md` | Contrato novo ou alterado, comando ou fluxo novo, CLAUDE.md aninhado novo (ponteiro em "Estrutura do repositório") |
| CLAUDE.md aninhado | Módulo ou teste novo (árvore) ou linha nova de "Arquivos de contexto", no CLAUDE.md mais próximo acima do código (guardados por `tests/test_claude_md_inventory.py`) |

Regra prática: se o diff toca arquivo de contrato (o mapa de
`.claude/hooks/harness-reminder.sh`) e nenhum documento acima mudou,
justifique por que não era necessário antes de commitar.

Skills e comando do projeto (`.claude/`), com fronteira explícita entre irmãs:

- `.claude/skills/download-smoke/SKILL.md` — valida um `download` real
  (cascade, wget, perfil httrack, manifest) contra servidor local primeiro e,
  no máximo, um site público permitido, sem crawl pesado. Para o que um pack
  responde a um cliente MCP, use a irmã abaixo.
- `.claude/skills/mcp-serve-inspect/SKILL.md` — dirige `dograpper serve` por
  JSON-RPC no stdio sobre um pack JSONL montado offline. Para buscar páginas,
  use a irmã acima.
- `.claude/commands/structural-audit.md` (`/structural-audit`) — auditoria
  estrutural recorrente e read-only (tamanho, churn de 4 semanas, camadas,
  3ª cópia de um molde, testes > 1000 linhas): no máximo 5 achados com
  evidência, classificados fix-now / debt / ignore, registrados em
  `docs/audits/structural.md`.

## Glossário vivo (`docs/glossario.md`)

`docs/glossario.md` é um glossário de APRENDIZADO, em pt-BR: explica em
linguagem acessível os jargões técnicos do trabalho neste projeto para quem
está construindo fluência de decisão. Os comandos `/explique` e `/revisao`
leem e escrevem nele — mantenha o formato idêntico. Não confunda com o
`GLOSSARY.md`, a linguagem de domínio normativa (página, registro, chunk,
símbolo…) usada para nomear coisas em código e docs: termo de domínio nunca é
redefinido no `docs/glossario.md` — a entrada aponta para o `GLOSSARY.md`.

- **Consulta:** antes de explicar um termo técnico ao usuário, procure-o em
  `docs/glossario.md`. Marcado ✅: só referencie ("como já vimos, …"). 🔁, 🆕
  ou ausente: explique.
- **Manutenção proativa:** quando surgir no trabalho um jargão que o usuário
  provavelmente não domina, ADICIONE a entrada, mesmo sem pedido. Termo que já
  existe é ATUALIZADO, nunca duplicado.
- **Não invente o "Onde apareceu":** conceito geral ainda não usado aqui
  recebe exatamente esse texto.
- **Formato fixo das entradas** (copie a estrutura):

  ```markdown
  ## <termo>
  **Em uma frase:** <explicação sem jargão>
  **Analogia:** <analogia curta, ou "—">
  **Onde apareceu:** <decisão/arquivo + data, ou "conceito geral, ainda não usado no projeto">
  **Por que importa pra decisão:** <o que muda na minha escolha>
  **Nível:** 🆕 novo | 🔁 revisar | ✅ entendido
  ```
