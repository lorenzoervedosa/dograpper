# 5. Sessão autônoma de resolução do backlog (issues #10–#24)

- Status: aceito
- Data: 2026-07-09

## Contexto

O mantenedor autorizou explicitamente uma sessão autônoma noturna para
resolver sequencialmente as 15 issues abertas (#10–#24), delegando as
decisões de implementação e pedindo que cada escolha relevante fosse
registrada como ADR.

As regras do repositório exigem que toda mudança entre via Pull Request
revisado e proíbem commit direto em `main`. Com o mantenedor ausente,
não há revisor humano disponível durante a sessão.

## Decisão

1. **Sequenciamento**: seguir o roadmap de ondas já aprovado em
   `docs/superpowers/plans/2026-07-05-roadmap-issues-abertas.md`
   (#13 → #11 → #10 → quick wins → #22 → #17 → #12 → #23 → #21 →
   #24 → #20 → #16 → #15), respeitando o grafo de dependências ali
   documentado.
2. **Fluxo por issue**: branch dedicada → implementação com testes →
   suíte completa verde localmente → PR referenciando a issue
   (`Closes #N`) → revisão automatizada por agentes independentes
   (correção, aderência à spec, invariantes do projeto) → merge somente
   com CI verde. A revisão por agentes substitui a revisão humana
   **apenas nesta sessão**, sob a autorização citada.
3. **Merge**: rebase para PRs com múltiplos commits atômicos, squash
   para PRs de commit único — preservando o histórico atômico exigido
   pelas convenções do projeto.
4. **Decisões de escopo**: issues XL de alta incerteza (#15) ou com
   gate técnico (#20) podem ser resolvidas com um escopo mínimo viável
   ou com uma decisão documentada de deferimento — resolver uma issue
   não significa necessariamente implementar o escopo máximo, e sim
   tomar e registrar a melhor decisão de produto disponível.
5. **Registro**: cada decisão arquitetural relevante tomada durante a
   sessão vira um ADR neste diretório; decisões menores ficam no corpo
   do PR correspondente.

## Consequências

- O histórico de `main` mantém a disciplina de PRs mesmo em sessão
  autônoma; nada entra sem CI verde e revisão (automatizada).
- O mantenedor pode auditar cada decisão via ADRs + PRs ao retornar;
  qualquer decisão pode ser revertida com novo ADR.
- Esta política vale somente para esta sessão autorizada; não cria
  precedente para merges autônomos em condições normais.
