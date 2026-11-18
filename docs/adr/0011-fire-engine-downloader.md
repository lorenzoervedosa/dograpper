# 11. Downloader "fire-engine" para documentação atrás de WAF

- Status: aceito
- Data: 2026-11-18

## Contexto

O perfil `httrack` reproduz o HTTrack fielmente e, por isso, não imita o TLS
de um navegador, não usa proxy e não lida com desafios. Sites de documentação
pública cada vez mais ficam atrás de WAFs (Cloudflare e similares) que
bloqueiam clientes cujo handshake TLS não parece de navegador, mesmo quando o
conteúdo é aberto. O `httrack` para alto nesses casos (exit 1) e manda o
usuário trocar de rede ou de downloader.

Serviços legítimos de scraping de documentação (ex.: Firecrawl) resolvem isso
com uma cascata: HTTP comum → cliente com fingerprint de navegador → navegador
real. Em 2026-11-18 o mantenedor revogou a classificação dessas técnicas como
anti-goal do projeto (`docs/DECISIONS.md`): coletar documentação pública com
ritmo controlado é uso legítimo. Elas continuam fora do perfil `httrack` (que
fica idêntico ao HTTrack), e passam a ser objetivo de um downloader próprio.

## Decisão

Um terceiro downloader, `fire-engine`, selecionável por flag
(`--downloader fire-engine`, padrão continua `wget`), com uma cascata de
fetch por origem:

1. **Fingerprint de navegador no TLS/HTTP-2** via `curl_cffi` (perfil
   `impersonate` alinhado ao Chromium), para que o cliente seja aceito onde o
   `http.client` da stdlib é recusado por discrepância de handshake.
2. **Proxy fornecido pelo usuário**, opcional, com escalonamento quando a
   origem é bloqueada. dograpper não embarca pool de proxies: as URLs vêm de
   flag/variável de ambiente do usuário.
3. **Resolução manual de desafio em navegador real** (human-in-the-loop): quando
   um desafio persiste, abre um navegador visível para o usuário resolver; a
   sessão validada (cookies, UA, client-hints) é reaproveitada pelas demais
   requisições da mesma origem e persistida entre execuções.

Restrições inegociáveis:

- **`curl_cffi` é dependência opcional, import condicional** (contrato 1,
  [ADR-0004](0004-optional-native-deps-conditional-import.md)), sob um extra
  `fire-engine`. O caminho principal instala e roda sem ela.
- **Nenhuma resolução automática de CAPTCHA ou execução automática de desafio
  JS.** O desafio é resolvido pelo usuário, à mão; nada de serviço terceiro de
  solver. Resolução automática continua non-goal.
- **robots.txt e o pacing do `Fetcher`** (conn-rate, banda, gap por host,
  Retry-After) valem em todos os caminhos, inclusive via `curl_cffi`.
- **100% síncrono, thread-safe** para rodar sob o `ThreadPoolExecutor` já
  existente em `crawl.py`/`mirror.py`.
- **Desafios e corpos não-2xx nunca viram conteúdo** no diretório de saída nem
  no cache (regra já valida para o `httrack`).
- **Segredos** (cookies, URL de proxy com credencial) nunca aparecem em log,
  manifest, report ou saída.

## Escopo incremental

O design completo proposto (detecção de múltiplos WAFs, vault de sessão por
origem, rotação automática de proxy, cache SQLite compartilhado) é grande e
especulativo: a única evidência real no projeto é **um** site atrás de
Cloudflare (site B da nota de discovery). Construir detecção de DataDome,
Akamai e PerimeterX, e rotação de proxy "queimado", antes de ter um site que
exija isso, é generalização sem requisito. Portanto a implementação é fatiada,
e cada fatia é um PR próprio, começando pelo caso observado:

1. **Fatia 1 (mínima):** extra `fire-engine` com `curl_cffi` opcional;
   transporte `curl_cffi` com fingerprint de Chromium, respeitando o pacing;
   detecção de desafio Cloudflare (reuso de `utils/challenge.py`); proxy único
   do usuário (sem escalonamento); resolução manual em navegador real.
2. **Fatias seguintes, só quando um site real exigir:** escalonamento/rotação
   de proxy, persistência de sessão entre execuções, cache compartilhado,
   detecção de outros WAFs.

## Fatia 2 (#130)

- **Uma cascata só.** `run_fire_engine` deixou de ser cópia de
  `run_httrack`: os dois chamam `run_profile()` em
  `commands/_httrack_profile.py`, e só o transporte, as mensagens e a regra de
  `--headless` diferem. Com isso o `fire-engine` herda o modo de atualização
  (HTTrack `-C2`, `previous=`): revalida os arquivos da execução anterior e
  grava os validadores no manifest.
- **Headers no fio.** Do conjunto de headers do perfil `httrack`
  (`policy.request_headers`), o `CurlCffiFetcher` repassa ao curl só os que
  são do pedido: `Referer`, `If-None-Match` e `If-Modified-Since`. A
  identidade (User-Agent, Accept, Accept-Language, Accept-Encoding,
  Sec-Fetch-\*, client hints, ordem dos headers) vem do perfil
  `--impersonate`, porque misturar a identidade do HTTrack com um handshake de
  Chrome é exatamente a incoerência que um WAF detecta. Consequência
  aceita: os `Sec-Fetch-*` são os fixos do perfil (navegação), não os do link
  (`FetchMeta`), e `--user-agent` não é enviado (pendência em
  `docs/DECISIONS.md`).
- **Corpo limitado no lado do curl.** A decodificação do curl fica desligada
  (`HTTP_CONTENT_DECODING` 0): o writer do curl (`content_callback`) recebe o
  corpo como veio do fio, aborta a transferência além de `MAX_BODY_BYTES` e
  cobra a banda por pedaço, como o caminho da stdlib; o `Fetcher.get` decodifica
  com o mesmo decoder limitado do `httrack` (teto de tamanho, de membros e de
  janela zstd de 8 MiB, que o decoder do próprio curl não aplica). Por isso o
  extra `fire-engine` instala também `brotli` e `zstandard`: o perfil de Chrome
  anuncia `br` e `zstd`, e quem os decodifica agora é o Python. Sem streaming
  do curl_cffi, o `--timeout` vira opções do curl com a semântica do timeout de
  socket da stdlib: para conectar, depois sem receber nada por `--timeout`
  segundos (nunca a duração total da transferência).
- **Credenciais do proxy fora da URL.** O curl cita na mensagem de erro a URL
  de proxy que não consegue usar ("Unsupported proxy scheme for '...'"), e a
  mensagem vai para o relatório. Por isso `user:senha` sai da URL do `--proxy`
  (autoridade lida como o curl lê: esquema opcional, até o primeiro `/`, `?`
  ou `#`; percent-decode) e vai ao curl como opções próprias (`proxy_auth` do
  curl_cffi): nenhuma mensagem do curl pode conter a credencial, e a URL do
  proxy que aparece no erro ainda passa por `redact_url`.

## Consequências

- `download`/`sync` ganham `--downloader fire-engine` e as flags do perfil; o
  README e o `CHANGELOG` documentam no mesmo PR de cada fatia.
- Sem o extra `fire-engine`, selecionar o downloader falha com mensagem clara
  (como o Playwright hoje).
- O perfil `httrack` e o `wget` não mudam.
- A persistência de sessão e o cache compartilhado, quando chegarem, não podem
  colidir com o `.dograpper-manifest.json` nem com o PR3 (#78) do `httrack`.
