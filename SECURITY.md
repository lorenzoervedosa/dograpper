# Política de Segurança

## Versões suportadas

Correções de segurança são aplicadas apenas à última versão publicada
(ver tags `v*.*.*` e os releases do GitHub). Versões anteriores não
recebem patches retroativos.

## Como reportar uma vulnerabilidade

**Não abra uma issue pública para vulnerabilidades.**

Reporte de forma privada por uma das vias:

1. **GitHub Security Advisories** — aba *Security → Report a vulnerability*
   em https://github.com/lorenzoervedosa/dograpper/security/advisories/new
2. **E-mail** — tech@okiar.com.br

Inclua, se possível: versão afetada, passos de reprodução, impacto e
qualquer PoC. Procuramos confirmar o recebimento em até 5 dias úteis.

## Escopo e modelo de ameaça

O dograpper é um CLI que baixa e processa documentação HTML. Pontos de
atenção relevantes:

- **Conteúdo remoto não confiável.** `download`/`sync` buscam HTML
  arbitrário da web. A extração e o stripping de HTML usam apenas a
  stdlib (`html.parser`) e nunca executam scripts do conteúdo baixado.
- **Execução de subprocessos.** O download invoca `wget` do sistema.
  URLs e caminhos são tratados como dados, não interpolados em shell.
- **Playwright (opcional).** Quando presente, roda Chromium headless com
  hidratação limitada (bounded). É dependência opcional e import condicional.
- **Sem segredos em repositório.** Arquivos `.env*` são ignorados via
  `.gitignore`. O projeto não requer credenciais para operar.

Relatórios fora desse escopo (ex.: DoS por baixar um site gigante
intencionalmente) ainda são bem-vindos, mas podem ter prioridade menor.
