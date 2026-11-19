# `src/dograpper/lib/fire_engine/`

Transporte curl_cffi do perfil `--downloader fire-engine` (ADR-0011). Contratos, gates e fluxo de sessão: `CLAUDE.md` da raiz.

## Módulos

```
src/dograpper/lib/fire_engine/
│   │   └── fetcher.py      # CurlCffiFetcher(Fetcher) (ADR-0011): sobrescreve só _request (curl_cffi impersonate + proxy, allow_redirects=False; decodificação do curl desligada e writer content_callback que aborta além de MAX_BODY_BYTES e cobra a banda, o corpo cru é decodificado pelo _decode limitado do Fetcher.get; --timeout como o timeout de socket da stdlib — conectar, depois silêncio —, nunca duração total; split_proxy() tira user:senha da URL do proxy (autoridade lida como o curl: esquema opcional, até o 1º /, ? ou #; percent-decode) e os passa como proxy_auth, logo nunca estão numa URL que o curl cita nos erros, e a URL do proxy no erro passa por redact_url; dos headers do httrack só Referer, os validadores do modo de atualização e o User-Agent de um --user-agent explícito (substitui o do perfil) vão ao curl, o resto é a identidade do perfil impersonado; com o stop= do get(), o writer o consulta no primeiro pedaço, com status, Content-Type e Content-Length do CURLINFO, e aborta sem ler o corpo); reúsa pacing/retry/challenge/robots do Fetcher. curl_cffi é dep opcional (import lazy no _default_session_factory, mensagem amigável se ausente)
```
