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
  (`FetchMeta`). Um `--user-agent` dado pelo usuário substitui o
  `User-Agent` do perfil; sem ele, vale o do perfil. A regra provisória de
  2026-11-18 foi substituída pela opção B do #136 (seção "Identidade no fio").
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
- **Opções de cache e atualização do HTTrack (#132).** `--cache`,
  `--updatehack` e `--do-not-recatch`, e as datas de arquivo tiradas do
  `Last-Modified`, valem no `fire-engine` pela mesma cascata: são estado da
  política e do motor, não do transporte. O `stop=` do `--updatehack`
  (HTTrack `-%s`) é perguntado no writer do curl, no primeiro pedaço, com o
  status, o `Content-Type` e o `Content-Length` que o curl leu (`CURLINFO`), e
  o writer aborta a transferência sem guardar nem cobrar o corpo.

## Identidade no fio (#156, #157, #136)

Evidência: `docs/discovery/firecrawl-header-behavior.md`.

- **Sem upgrade h2c em `http://` (#156).** A sessão do curl usa
  `HTTP_VERSION` = `V2TLS` (HTTP/2 só sobre TLS). Num alvo `http://` o curl
  deixa de mandar `Upgrade: h2c`, `HTTP2-Settings` e `Connection: Upgrade,
  HTTP2-Settings`, que nenhum navegador manda; no HTTPS o ALPN continua
  oferecendo `h2`. Resíduo aceito: sob o alvo `chrome`, `Host` é a última
  linha do pedido HTTP/1.1 em texto claro, onde o Chromium o põe primeiro.
  Mudar isso abandonaria a ordem de headers do perfil (decisão do mantenedor,
  2026-11-20). Em HTTP/2 o host vai no pseudo-header `:authority`, na ordem
  do perfil.
- **Valores por alvo (#157).** Uma tabela pequena de valores de header por
  alvo do `curl_cffi` (`_TARGET_HEADERS`) vale antes de qualquer outro header,
  então o `--header` do usuário ainda vence. Hoje ela só corrige o
  `chrome131_android` (alias `chrome_android`), que manda `sec-ch-ua-mobile:
  ?0` ao lado de um User-Agent Android: o dograpper manda `?1`, como a
  especificação de Client Hints manda um navegador móvel fazer, no lugar que o
  alvo dá ao header. Decisão do mantenedor (2026-11-20), sem captura de um
  Chrome Android real; o defeito vai ao `curl_cffi` pelo mantenedor.
- **User-Agent livre (#136, opção B, decisão do mantenedor de 2026-11-19).**
  Como o `headers` do Firecrawl, um `--user-agent` explícito é enviado: ele
  substitui o User-Agent do perfil no lugar que o perfil dá a ele, e os
  `sec-ch-ua`, `sec-ch-ua-mobile` e `sec-ch-ua-platform` do perfil caem, porque
  descrevem o User-Agent do perfil e seriam falsos para qualquer outro. A
  execução avisa uma vez que o fingerprint TLS continua o do perfil. Os engines
  abertos do Firecrawl não realinham nada além do User-Agent; derrubar os
  hints é escolha do dograpper, não paridade. Resíduo aceito:
  - o handshake TLS e as configurações HTTP/2 continuam os do perfil;
  - a ordem e os demais headers só de Chrome (`Sec-Fetch-*`, `Accept`,
    `Accept-Language`, `cache-control`, `upgrade-insecure-requests`) ficam os
    do perfil;
  - com um User-Agent que nomeia o Firefox, o próprio `curl_cffi` acrescenta a
    linha `priority: u=0, i` do Firefox (medido no 0.17.0), o que o dograpper
    não controla.
- **`--header` repetível (#136, decisão do mantenedor de 2026-11-19).** O
  equivalente ao mapa `headers` do Firecrawl e ao `-%X` do HTTrack, nos dois
  perfis. Ao curl vão, nesta ordem de precedência, os valores por alvo, os
  headers do pedido (`Referer`, validadores), o User-Agent explícito com os
  hints derrubados e por último as linhas `--header`: cada camada toma o
  lugar do header de mesmo nome da anterior, e o `curl_cffi` põe um header de
  mesmo nome que um do perfil no lugar dele. Um hint dado por `--header`
  volta mesmo com `--user-agent`. A grafia do nome é a do usuário, visível só
  em HTTP/1.1 (follow-up 10 da pesquisa). `--header 'User-Agent: X'` é o
  `--user-agent X`; os dois juntos são exit 2, regra que vale para toda fonte
  de User-Agent (`single_user_agent()` em `commands/_httrack_profile.py`). A
  validação, guarda de entrada não confiável no fio, mora num lugar só
  (`utils/http_headers.py`).

## Estado da decisão (2026-11-18)

Entregue pelas fatias 1 e 2: itens 1 e 2 da decisão, com um proxy único vindo
de `--proxy` (ou da chave `proxy` do `.dograpper.json`), sem escalonamento.
**O item 3, a resolução manual de desafio em navegador real, ainda não foi
implementado**, embora a fatia 1 o listasse:
quando o start URL (ou toda URL semeada) continua desafiado mesmo com o
fingerprint de navegador, a execução falha alto (exit 1) e a mensagem manda
tentar `--proxy` com outro IP ou `--downloader wget`; uma página desafiada no
meio do crawl só entra no relatório. A decisão continua valendo; falta a fatia
que a entrega.

## Consequências

- `download`/`sync` ganham `--downloader fire-engine` e as flags do perfil; o
  README e o `CHANGELOG` documentam no mesmo PR de cada fatia.
- Sem o extra `fire-engine`, selecionar o downloader falha com mensagem clara
  (como o Playwright hoje).
- O perfil `httrack` e o `wget` não mudam.
- A persistência de sessão e o cache compartilhado, quando chegarem, não podem
  colidir com o `.dograpper-manifest.json` nem com o PR3 (#78) do `httrack`.
