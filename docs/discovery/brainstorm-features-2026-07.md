# Brainstorm de Features Inovadoras — dograpper

> Discovery contínuo (product trio: PM + Designer + Engineer). Data: 2026-07-04.

## 1. Enquadramento da oportunidade

- **Produto**: `dograpper` — pipeline determinística de context engineering que transforma
  documentação HTML em contexto estruturado, dedupicado, pontuado e versionado
  (`URL → Mirror → Extract → Dedup → Score → Chunk → Export`).
- **Segmento**: engenheiros de IA / plataforma que montam contexto para LLMs estáticos —
  NotebookLM, pipelines RAG, Claude Projects, fine-tuning. Inclui ambientes regulados/air-gapped.
- **Outcome desejado**: maximizar a *qualidade de contexto por token ingerido* e reduzir o
  atrito entre "documentação viva" e "contexto pronto para LLM", mantendo os invariantes do
  produto: determinismo, zero telemetria, manifest auditável, deps problemáticas opcionais.
- **Ativos únicos já existentes**: cascade de descoberta em 4 camadas, LLM Readiness Score,
  schema `dograpper-context-v1`, cross-refs entre chunks, delta/manifest incremental.
- **Lacunas centrais**: (a) só ingere HTML; (b) o Readiness Score é heurístico, nunca validado
  contra qualidade real de resposta; (c) a saída são artefatos em disco — não há camada de
  serviço que entregue o contexto direto ao LLM; (d) ferramenta poderosa mas densa em flags,
  com onboarding hostil.

---

## 2. Ideação por perspectiva (15 ideias)

### Product Manager (valor de negócio, estratégia, impacto no cliente)

1. **`dograpper serve` — servidor MCP local.** Expõe os chunks empacotados como um servidor
   MCP que Claude Code/Desktop/Cursor consultam ao vivo e localmente. Transforma um tool batch
   em provedor de contexto contínuo, sem sair do modelo air-gapped.
2. **Ingestão multi-fonte** — PDF, OpenAPI/Swagger, repositórios Git, wikis Markdown, além de
   HTML. Amplia drasticamente o TAM (a maior parte da "documentação" corporativa não é HTML).
3. **Eval harness com Q&A dourado (`dograpper eval`).** Gera pares pergunta/resposta a partir
   dos docs e mede hit-rate de recuperação — converte o Readiness Score de heurística em métrica
   empírica. É o fosso de credibilidade vs. repomix/gitingest.
4. **Registry de context packs compartilháveis** — publicar/consumir packs pré-construídos
   (`flask@stable`, `stripe-api@2024`). Efeito de rede + economiza recomputo global.
5. **GitHub Action de frescor contínuo** — mantém o contexto atualizado a cada commit de docs
   e comenta no PR o *drift diff* (o que mudou no contexto). Torna o dograpper pegajoso no fluxo
   de repositórios de documentação.

### Product Designer (UX, usabilidade, encantamento)

6. **`dograpper studio` — TUI interativa.** Dashboard no terminal com tamanhos de chunk, grades,
   economia de dedup e ajuste de fronteiras — substitui o atual "resumo em texto + tentativa/erro
   de flags".
7. **Relatório de readiness em diff visual.** Mostra antes/depois da extração: qual boilerplate
   foi removido, grade por página com cor, chunks fracos destacados. Torna a qualidade tangível.
8. **`dograpper init` — wizard guiado.** Detecta o alvo (NotebookLM vs RAG vs Claude Project),
   inspeciona o site e gera o `.dograpper.json` certo. Elimina o atrito de decorar flags.
9. **Visualização do cascade ao vivo.** Renderiza as 4 camadas de descoberta como uma árvore
   com progresso — hoje o cascade é observável só via `grep` de logs `[cascade]`.
10. **"Explain this chunk" / preview.** Amostra exatamente o que o LLM verá por chunk (header v1
    + breadcrumb + cross-refs resolvidos), para o usuário auditar antes de subir.

### Software Engineer (possibilidade técnica, alavancagem de dados, escala)

11. **Dedup e chunking semântico por embeddings (dep opcional).** Detecção de quase-duplicatas
    além do SimHash e agrupamento temático além de "mesmo diretório", com modelo fixo + seed
    para preservar determinismo.
12. **Cache content-addressed incremental.** Store indexado por hash de conteúdo compartilhado
    entre projetos — re-packs reaproveitam extração já feita. Escala para monorepos de docs.
13. **Packing orientado a consulta (`--for-queries`).** Dado um conjunto de perguntas esperadas,
    otimiza a composição dos chunks (BM25/embeddings) para co-localizar conteúdo relevante.
    Context engineering de verdade: "empacote *para um propósito*".
14. **Arquitetura de plugins (extractors/exporters).** Sistema de plugins para a comunidade
    adicionar Confluence, Notion, Docusaurus, etc., sem inchar o core.
15. **Pipeline paralela com worker pool.** Crawl + extração concorrentes com paralelismo
    determinístico (ordenação estável no final), cortando o tempo de wall-clock em sites grandes.

---

## 3. Top 5 priorizadas

Critérios: alinhamento estratégico (context engineering determinística p/ LLMs estáticos),
impacto no outcome, viabilidade/esforço, diferenciação.

### 1. `dograpper serve` — servidor MCP de contexto local
**Descrição:** um subcomando que serve os chunks/cross-refs/scores já gerados como um servidor
MCP, permitindo que Claude Code, Desktop e Cursor consultem o contexto empacotado ao vivo e
localmente.
**Por que foi selecionada:** maior alavancagem estratégica do conjunto. Fecha o loop
"docs → contexto → LLM" sem quebrar o modelo air-gapped (MCP roda local, zero telemetria).
Reaproveita artefatos que já existem (chunks, `cross_refs.json`, `llm-readiness.json`).
Diferenciação máxima — nenhum concorrente serve documentação empacotada determinística por MCP.
**Assunções a validar:** (a) o público-alvo já usa clientes MCP no dia a dia; (b) recuperação
top-k sobre chunks pré-empacotados supera colar docs crus no prompt; (c) dá para servir sem
introduzir dependência pesada obrigatória (manter embeddings opcionais; fallback BM25 stdlib).

### 2. `dograpper eval` — eval harness com Q&A dourado
**Descrição:** gera pares pergunta/resposta a partir da documentação e mede a taxa de
recuperação/acerto do contexto empacotado, produzindo um relatório empírico de qualidade.
**Por que foi selecionada:** transforma o Readiness Score (hoje heurístico: noise/boundary/depth)
em métrica *validada contra comportamento real*. É o argumento de credibilidade — "não achamos
que seu contexto é bom, provamos". Alinha-se ao outcome de qualidade-por-token.
**Assunções a validar:** (a) geração de Q&A pode ser offline/determinística o bastante (modelo
local fixo ou template-based) para não violar o invariante de zero-telemetria; (b) hit-rate de
recuperação correlaciona com qualidade de resposta percebida; (c) usuários confiam mais numa
grade empírica do que na heurística atual.

### 3. Ingestão multi-fonte (PDF + OpenAPI + repositório Git)
**Descrição:** front-ends de ingestão além de HTML — PDF, specs OpenAPI/Swagger e repositórios
de código — alimentando o mesmo pipeline Extract → Dedup → Score → Chunk.
**Por que foi selecionada:** maior desbloqueio de TAM. A maioria da documentação técnica
corporativa não é HTML navegável; suportar PDF e OpenAPI abre RAG de API e RAG regulado. Encaixa
limpo na arquitetura (novos extractors na fase Mirror/Extract).
**Assunções a validar:** (a) extração de PDF preserva estrutura suficiente para o boundary-aware
chunking; (b) demanda por OpenAPI/Git justifica o custo por fonte; (c) dá para manter
determinismo por fonte (PDF parsing pode ser não-determinístico entre libs/versões).

### 4. `dograpper init` — wizard de onboarding com presets por alvo
**Descrição:** comando interativo que detecta o tipo de site e o alvo pretendido (NotebookLM /
RAG / Claude Project) e gera o `.dograpper.json` ideal, eliminando a memorização de flags.
**Por que foi selecionada:** melhor razão impacto/esforço. O produto é poderoso mas denso em
flags — o wizard ataca o atrito de adoção diretamente, é barato (reusa presets `--bundle`
existentes) e não toca invariantes.
**Assunções a validar:** (a) o abandono real está no onboarding, não na execução; (b) a
detecção de alvo por heurística acerta o preset na maioria dos casos; (c) usuários preferem um
`.dograpper.json` gerado a copiar exemplos do README.

### 5. GitHub Action de frescor contínuo + drift diff no PR
**Descrição:** Action que roda `sync`/`--delta` em CI e comenta no PR o diff do contexto (chunks
adicionados/modificados/removidos, variação de grade), mantendo os packs sempre frescos.
**Por que foi selecionada:** operacionaliza o `delta`/`manifest` que já existem e torna o
dograpper pegajoso no fluxo de repos de docs. O *drift diff* é um artefato novo e encantável —
ninguém mostra "como a qualidade do contexto mudou neste PR". Canal de distribuição via
Marketplace.
**Assunções a validar:** (a) equipes de docs querem o pack versionado junto do repo; (b) o diff
de contexto é acionável (não apenas ruído); (c) o custo de rodar em CI (wget/chromium) é
aceitável em runners hospedados.

---

## 4. Runners-up (revisitar num próximo loop)

- **Packing orientado a consulta (`--for-queries`)** — a ideia mais "context engineering pura";
  segurar até o `eval` existir, pois compartilham o motor de recuperação.
- **Dedup/chunking semântico por embeddings** — forte, mas exige provar que o determinismo se
  mantém antes de comprometer a narrativa do produto.
- **`dograpper studio` (TUI)** — alto encantamento, mas depende de haver dado rico para exibir;
  ganha mais valor depois do `eval` e do `serve`.

---

## 5. Sequência sugerida (opportunity solution tree, resumida)

```
Outcome: máxima qualidade de contexto por token, com atrito mínimo docs→LLM
├── Oportunidade: "não sei se meu contexto é bom"          → #2 eval  → habilita #13 for-queries
├── Oportunidade: "meu contexto não é HTML"                → #3 multi-fonte
├── Oportunidade: "preciso usar o contexto, não só gerá-lo" → #1 serve (MCP)
├── Oportunidade: "não sei configurar a ferramenta"        → #4 init
└── Oportunidade: "meu contexto envelhece silenciosamente" → #5 GitHub Action + drift diff
```

Recomendação de ordem de experimentação: **#4 (barato, valida adoção) → #1 (alavancagem
estratégica) → #2 (fosso de credibilidade) → #3 (TAM) → #5 (distribuição)**.
