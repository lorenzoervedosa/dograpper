# Roadmap de Implementação — Issues Abertas (#10–#24)

> **Para workers agênticos:** este é um plano de **sequenciamento** (roadmap), não um plano
> TDD tarefa-a-tarefa. Cada issue é um subsistema independente. Antes de executar uma issue,
> gere o plano detalhado dela com `superpowers:writing-plans` (uma issue = um plano). Use este
> documento apenas para decidir **ordem** e **dependências**.

**Goal:** ordenar as 15 issues abertas em ondas executáveis, respeitando dependências técnicas,
prioridade de negócio e os invariantes duros do projeto.

**Data:** 2026-07-05 · **Fonte das specs:** issues #10–#24 · `docs/discovery/brainstorm-features-2026-07.md`

---

## Global Constraints (valem para toda issue)

Copiados verbatim dos invariantes do projeto (`CLAUDE.md`, `about_dograpper.md`, ADR-0004):

- **Zero-telemetria / air-gapped:** nenhuma chamada de rede de saída durante `pack`, `serve`,
  `eval` ou consumo de pack. Auditável.
- **Determinismo bit-a-bit:** mesmo input → mesmo output. Qualquer paralelismo ou embedding
  exige ordenação estável + modelo fixo + seed. Determinismo é a narrativa central do produto.
- **Deps problemáticas são opcionais** (ADR-0004): binários de sistema, compilação nativa ou
  libs que não rodam em todo ambiente entram como import condicional com erro amigável.
  Deps pip puras podem ser obrigatórias.
- **Contagem por palavras, não bytes** (`len(text.split())`).
- **Encoding tolerante:** leitura sempre com `errors="replace"`.
- **Precedência de config inviolável:** defaults click < `.dograpper.json` < flags CLI
  (`ctx.get_parameter_source()`).
- **Testes existentes não podem quebrar:** `uv run pytest tests/ -v` verde antes de cada commit.
- **Não usar repomix.** Concatenação em Python puro.
- **Playwright nunca é import top-level.**

---

## Grafo de dependências

```
                    ┌─────────────────────────────┐
                    │  lib/retrieval.py            │  ← keystone (não é issue;
                    │  BM25 stdlib determinístico  │     nasce dentro de #11)
                    └──────────────┬──────────────┘
                     ┌─────────────┼──────────────┐
                     ▼             ▼              ▼
                  #11 eval      #10 serve      #22 --for-queries
                     │                              (depois de #11)
                     ▼
                  #17 diff visual (usa scorer; complementa eval)

   #12 ingestion multi-fonte ──► #23 plugins (generaliza interface após ≥2 fontes)

   Independentes (sem deps de código):  #13 init · #14 CI · #18 cascade-viz · #19 explain-chunk
   Engine/perf (determinism-gated):     #21 cache · #24 pipeline paralela · #20 dedup semântico
   Ecossistema (validar demanda antes): #16 studio (após #10/#11) · #15 registry
```

**Regras de precedência extraídas das próprias issues:**
- #22 declara: "compartilha o motor de recuperação com #11 — implementar **depois** dele."
- #23 declara: "complementa a ingestão multi-fonte (#12)" → precisa de #12 com ≥2 fontes para
  generalizar a interface sem vazar internals.
- #16 declara: "ganha valor após `eval` (#11) e `serve` (#10)."
- #20 é runner-up: "segurar até validar determinismo" → exige spike de prova antes de comprometer.

---

## Ondas de execução

### Onda 0 — Quick wins (paralelizáveis, baixo risco, alto UX)
Sem dependências de código; reusam módulos existentes; entregam valor imediato.

| Issue | Título | Effort | Prio | Por quê agora |
|---|---|---|---|---|
| **#13** | `init` wizard de onboarding | S | medium | Maior atrito de adoção; reusa presets `--bundle`. Único S priority:medium. |
| **#19** | `pack` preview "explain this chunk" | S | low | Reusa `heading_extractor`/`link_extractor`; sem escrita em disco; trivial. |
| **#18** | `download` cascade viz ao vivo | S | low | Camada de render sobre o logger; mantém logs `[cascade]` planos. |
| **#14** | GitHub Action de frescor + drift diff | M | medium | Operacionaliza `--delta`/`delta_manifest.json` que **já existem**. |

**Entregável da onda:** 3 quick wins de UX + 1 canal de distribuição (Marketplace). Comece por
**#13** (maior prioridade e impacto de adoção).

---

### Onda 1 — Keystone: motor de recuperação + validação empírica
A onda que destrava o resto. Extrair `lib/retrieval.py` (BM25 stdlib, determinístico) e
implementar **#11** sobre ele.

| Issue | Título | Effort | Prio | Por quê primeiro |
|---|---|---|---|---|
| **#11** | `eval` harness com Q&A dourado | L | **high** | (1) valida empiricamente o Readiness Score — de-risca a proposta de valor central; (2) faz nascer `lib/retrieval.py`, reusado por #10/#22/#16; (3) é dependência declarada de #22. |

**Decisão de arquitetura:** o motor de recuperação **não** vive dentro de `commands/eval.py`.
Nasce como `lib/retrieval.py` com interface estável (`build_index(chunks)`, `search(query, k)`)
para #10 e #22 consumirem sem reimplementar. Q&A dourado gerado **offline/template-based** sobre
a estrutura de headings — nunca API externa (invariante zero-telemetria).

**Entregável:** `dograpper eval <chunks-dir>` → relatório de hit-rate reprodutível + correlação
documentada com a grade heurística.

---

### Onda 2 — Servir e empacotar para propósito
Tudo reusa `lib/retrieval.py` da Onda 1.

| Issue | Título | Effort | Prio | Depende de |
|---|---|---|---|---|
| **#10** | `serve` servidor MCP local | L | **high** | `lib/retrieval.py` (#11) |
| **#22** | `pack --for-queries` | L | medium | `lib/retrieval.py` (#11); medido via `eval` (#11) |
| **#17** | Relatório de readiness em diff visual | M | medium | `scorer.py` existente; complementa `eval` |

**Ordem interna:** #10 antes de #22 (MCP é priority:high; expõe superfície externa que valida o
motor de recuperação em uso real antes de otimizar packing para consulta).

---

### Onda 3 — Expansão de fontes de ingestão
Amplia o TAM para além de HTML.

| Issue | Título | Effort | Prio | Nota |
|---|---|---|---|---|
| **#12** | Ingestão multi-fonte (PDF/OpenAPI/Git) | XL | medium | **Decompor** em sub-issues por fonte. Começar por **OpenAPI** (mais determinística; parsing de PDF varia entre libs/versões). |
| **#23** | Arquitetura de plugins extractors/exporters | L | low | **Depois** de #12 ter ≥2 fontes — só então a interface de plugin se generaliza sem chutar internals. |

**Ação imediata da onda:** abrir 3 sub-issues de #12 (`ingestion:openapi`, `ingestion:pdf`,
`ingestion:git`) e fechar #12 como épico.

---

### Onda 4 — Performance & qualidade do motor (determinism-gated)
Independentes entre si; todas exigem prova de determinismo.

| Issue | Título | Effort | Prio | Gate |
|---|---|---|---|---|
| **#21** | Cache content-addressed de extração | M | low | Melhor ROI da onda; chave = hash normalizado. Sem gate de determinismo (cache é transparente). Fazer primeiro. |
| **#24** | Pipeline paralela com worker pool | M | low | Gate: ordenação estável no final prova determinismo + rate-limit por host preservado. |
| **#20** | Dedup/chunking semântico por embeddings | L | medium | Runner-up. **Spike de determinismo bit-a-bit primeiro** — só comprometer se provar reprodutibilidade entre máquinas. Dep pesada opcional. |

---

### Onda 5 — Apostas de ecossistema (validar demanda antes de construir)

| Issue | Título | Effort | Prio | Pré-condição |
|---|---|---|---|---|
| **#16** | `studio` TUI interativa | L | low | Após #10/#11 (dashboard consome eval + retrieval). Validar que usuários calibram o bastante vs. `--dry-run`. |
| **#15** | Registry de context packs | XL | low | Aposta de efeito de rede. Validar demanda + licenciamento de redistribuição **antes** de investir em infra. Maior incerteza do backlog. |

---

## Resumo executivo — sequência recomendada

1. **#13** (init) — ship esta semana, destrava adoção.
2. **#11** (eval + `lib/retrieval.py`) — keystone; valida o produto e cria a infra compartilhada.
3. **#10** (serve MCP) — fecha o loop `docs → contexto → LLM` sobre o motor provado.
4. Preencher com quick wins #19/#18/#14 em paralelo conforme capacidade.
5. **#22 → #17 → #12** na sequência; #23 só depois de #12 maduro.
6. Engine (#21 → #24 → #20) e ecossistema (#16, #15) por último, cada um atrás do seu gate.

**Riscos de sequência:**
- Construir #10 antes de #11 duplicaria o motor de recuperação e serviria contexto não-validado.
- Construir #23 antes de #12 congelaria uma API de plugin com uma única fonte de referência.
- Qualquer embedding (#20) ou paralelismo (#24) sem prova de determinismo quebra a narrativa
  central — spike obrigatório antes do commit.

---

## Próximo passo

Escolher a **primeira issue** para expandir em plano TDD bite-sized completo
(`superpowers:writing-plans`, uma issue = um documento). Recomendação: **#11** (keystone) ou
**#13** (quick win) como warmup.
