# Glossário de aprendizado — dograpper

Glossário VIVO e SITUADO: explica, em linguagem acessível, os jargões técnicos
que aparecem no trabalho deste projeto, para quem está construindo fluência de
decisão. Os comandos `/explique` e `/revisao` leem e escrevem este arquivo; o
formato das entradas é fixo (seção "Glossário vivo" do `CLAUDE.md`).

Fronteira com o `GLOSSARY.md`: lá fica a linguagem de domínio do dograpper
(página, registro, chunk, símbolo…), normativa, usada para nomear coisas em
código e docs. Aqui fica o jargão técnico explicado. Termo de domínio não é
redefinido aqui: a entrada aponta para o `GLOSSARY.md`.

Entradas abaixo, uma seção `##` por termo.

## GET condicional (revalidação, 304)
**Em uma frase:** um pedido que manda junto a "etiqueta" (`ETag`) ou a data da cópia que você já tem (`If-None-Match`, `If-Modified-Since`); se nada mudou, o servidor responde `304 Not Modified` sem corpo e você reaproveita a cópia.
**Analogia:** perguntar à banca "a edição de hoje é a mesma que já comprei?" em vez de comprar o jornal de novo.
**Onde apareceu:** modo de atualização do perfil `--downloader httrack` (#78 PR 3, 2026-11-18): o manifest guarda `etag`/`last_modified` de cada arquivo e a próxima execução revalida com eles.
**Por que importa pra decisão:** uma atualização fica barata (poucos bytes por página inalterada) e segura (a cópia anterior fica intacta em 304 ou erro); o custo é guardar os validadores de cada arquivo e confiar que o servidor os gera direito.
**Nível:** 🆕 novo

## Modo de cache (HTTrack -C0, -C1, -C2)
**Em uma frase:** a regra que diz o que fazer com um arquivo que a execução anterior já baixou: ignorar o que se sabe dele e baixar tudo (`-C0`), confiar na cópia e nem perguntar ao servidor (`-C1`), ou perguntar ao servidor se mudou (`-C2`, o GET condicional).
**Analogia:** ao reabastecer a despensa: comprar tudo de novo (C0), confiar no que já está na prateleira (C1) ou conferir a validade de cada item antes (C2).
**Onde apareceu:** `--cache 0|1|2` do perfil `--downloader httrack` (#132, 2026-11-18); o padrão segue o HTTrack: 2 quando `-o` já tem um manifest, senão 1.
**Por que importa pra decisão:** troca custo por frescor: `1` não faz pedido nenhum (rápido, mas não vê o que mudou no site), `2` faz um pedido barato por arquivo, `0` baixa tudo de novo.
**Nível:** 🆕 novo

## mtime (data de modificação do arquivo)
**Em uma frase:** a data que o sistema de arquivos guarda como "última vez que este arquivo mudou"; ferramentas comparam essa data para decidir se precisam reler um arquivo.
**Analogia:** o carimbo de "atualizado em" na capa de um documento: barato de conferir, mas alguém pode carimbar sem mudar o conteúdo, ou mudar sem trocar o carimbo.
**Onde apareceu:** o perfil `httrack` passou a pôr no arquivo salvo a data `Last-Modified` do servidor, como o HTTrack (#132, 2026-11-18); por isso o `pack --delta` passou a decidir pelo hash do conteúdo, não pela data.
**Por que importa pra decisão:** atalho por data é rápido mas falha quando a data não acompanha o conteúdo; comparar o hash custa ler o arquivo, e é o que garante não perder nem inventar mudança.
**Nível:** 🆕 novo

## Low-speed limit do libcurl (`LOW_SPEED_LIMIT` / `LOW_SPEED_TIME`)
**Em uma frase:** o jeito do curl desistir de uma conexão parada: se a taxa ficar abaixo de X bytes/s por Y segundos, ele aborta (`curl: (28) Operation too slow`); só que ele mede a taxa em "fotos" de 1 s, então um byte que acabou de chegar só conta na foto seguinte.
**Analogia:** um fiscal que olha a esteira uma vez por segundo: se olhou um instante antes de a caixa passar, anota "nada passou" e pode parar uma fábrica que estava funcionando.
**Onde apareceu:** `--timeout` do perfil `--downloader fire-engine` (#154, 2026-11-19): com `LOW_SPEED_TIME` igual ao `--timeout`, transferências vivas abortavam; a janela passou a ser `--timeout` + 1 s.
**Por que importa pra decisão:** ele não reproduz o timeout de socket da stdlib (que zera a cada byte recebido): ou se aceita abortar conexão viva, ou se aceita esperar mais por um servidor morto; aqui a escolha foi esperar mais.
**Nível:** 🆕 novo

## subrecurso (subresource)
**Em uma frase:** tudo o que uma página pede sozinha depois de chegar ao navegador para conseguir se montar: scripts, folhas de estilo, fontes, imagens e as chamadas de dados (XHR/fetch) que o JavaScript dela faz.
**Analogia:** a página é a receita; os subrecursos são os ingredientes que a receita manda buscar na despensa.
**Onde apareceu:** Playwright sob o perfil `httrack` (#78 PR 4, 2026-11-19): a navegação de cada página passa pelo Fetcher do perfil, e os subrecursos ficam com a rede do próprio Chromium (UA do perfil, sem robots.txt nem pacing, `/cdn-cgi/` abortado), um desvio aprovado pelo mantenedor (spec §5.2).
**Por que importa pra decisão:** é onde fidelidade e funcionamento se cruzam. Pôr os subrecursos sob robots e pacing deixa cada página lenta e quebra as que têm assets proibidos no robots.txt; deixá-los com o navegador abre mão de parte da identidade do perfil. E, com o routing ligado, o Chromium não usa cache HTTP, então cada página baixa seus scripts de novo.
**Nível:** 🆕 novo

## fingerprint TLS (handshake)
**Em uma frase:** a "assinatura" que um cliente deixa na primeira mensagem da conexão segura (o ClientHello do handshake TLS): quais cifras, extensões e curvas ele oferece e em que ordem. Servidores e WAFs comparam essa assinatura com a de navegadores e ferramentas conhecidas.
**Analogia:** o sotaque de quem telefona: antes de você dizer o nome (o User-Agent), o jeito de falar já diz de onde você vem.
**Onde apareceu:** spec do perfil `httrack`, §5.1 e §8.0 (2026-11-13): o site B respondeu 200 ao handshake do OpenSSL 3.5 e 403 ao do 3.0, com o mesmo pedido. No #78 PR 4 (2026-11-19), `route.fetch()` foi trocado pelo Fetcher do perfil porque sairia com o handshake do Node. O `fire-engine` (ADR-0011) imita o de um navegador com curl_cffi.
**Por que importa pra decisão:** trocar só o User-Agent não muda o sotaque; quem passa ou não por um WAF é o handshake. Cada caminho de rede (motor, navegador, subrecurso) carrega a assinatura de quem abre a conexão, e é isso que se escolhe ao decidir quem busca o quê.
**Nível:** 🆕 novo

## hidratação (SPA)
**Em uma frase:** o momento em que o JavaScript de uma SPA (single-page app, a página que se monta no navegador) roda e preenche a "casca" HTML quase vazia que o servidor mandou com o conteúdo de verdade.
**Analogia:** o servidor entrega o móvel desmontado com o manual; a hidratação é a montagem na sua sala.
**Onde apareceu:** `lib/playwright_crawl.py`, com hidratação limitada (domcontentloaded 10 s + espera por `a[href]` 5 s + 500 ms); o fallback para Playwright quando `is_spa()` vê cascas vazias; o Playwright sob o perfil `httrack` (#78 PR 4, 2026-11-19).
**Por que importa pra decisão:** quem baixa só o HTML (wget, o motor do `httrack`) recebe a casca vazia de uma SPA, e por isso a cascata cai para um navegador. Esperar a hidratação custa tempo por página, e o limite dessa espera decide entre salvar uma página incompleta e travar o crawl.
**Nível:** 🆕 novo

## blanket implementation (Rust)
**Em uma frase:** uma implementação de trait escrita uma vez para todos os tipos que cumprem uma condição (`impl<T: Iterator> Itertools for T`), em vez de uma por tipo; o rustdoc a mostra na página de cada tipo coberto, com a documentação inteira dos métodos do trait.
**Analogia:** uma regra do condomínio que vale para "todo apartamento com varanda": o síndico cola a mesma folha em todas as portas com varanda.
**Onde apareceu:** adaptador rustdoc do `pack --api-records` (#75 fase 3, 2026-11-19): no corpus `itertools`, cada struct repete a doc de `Itertools` inteira por causa da blanket implementation (e a de `Iterator` pela implementação de trait); o adaptador descarta as blanket implementations e os itens das implementações de trait, e guarda só o cabeçalho `impl` de cada implementação de trait.
**Por que importa pra decisão:** manter essas cópias infla cada registro e faz a mesma doc concorrer na busca em dezenas de páginas; descartar perde só texto que já está, uma vez, na página do trait.
**Nível:** 🆕 novo

## docs-as-code
**Em uma frase:** tratar a documentação como código: arquivos de texto no repositório, revisados em PR e construídos por um comando que falha se algo estiver quebrado.
**Analogia:** a documentação passa pela mesma linha de montagem do software, com inspeção de qualidade no fim.
**Onde apareceu:** site de docs em `site/` (spec `docs/superpowers/specs/2026-11-20-docs-site-design.md`, 2026-11-20).
**Por que importa pra decisão:** o build com `-W` transforma link quebrado e referência inválida em erro, então a doc não apodrece em silêncio; o custo é manter o build verde.
**Nível:** 🆕 novo

## Sphinx
**Em uma frase:** gerador de sites de documentação que lê arquivos de texto e produz um site HTML navegável, com índice, busca e links verificados.
**Analogia:** uma gráfica que recebe os manuscritos e devolve o livro paginado, com sumário e remissões conferidas.
**Onde apareceu:** `site/conf.py` (spec `docs/superpowers/specs/2026-11-20-docs-site-design.md`, 2026-11-20).
**Por que importa pra decisão:** é Python e entra como extra `docs` no `uv`, sem Node.js; uma diretiva própria em `site/conf.py` gera a tabela de opções de cada comando a partir do próprio CLI.
**Nível:** 🆕 novo

## MyST
**Em uma frase:** dialeto de Markdown que o Sphinx entende, com diretivas extras (como `toctree`) para estruturar o site.
**Analogia:** Markdown com um vocabulário a mais, o suficiente para dizer à gráfica como montar o sumário.
**Onde apareceu:** `site/index.md` e `myst-parser` no extra `docs` (spec `docs/superpowers/specs/2026-11-20-docs-site-design.md`, 2026-11-20).
**Por que importa pra decisão:** permite reaproveitar o texto do README em Markdown sem reescrever em reStructuredText.
**Nível:** 🆕 novo

## client hints (`sec-ch-ua*`)
**Em uma frase:** headers que um navegador Chromium manda dizendo a própria marca e versão (`sec-ch-ua`), se é celular (`sec-ch-ua-mobile`) e o sistema (`sec-ch-ua-platform`), repetindo em campos separados o que o User-Agent diz numa frase só.
**Analogia:** um crachá com nome, cargo e setor ao lado do cartão de visita; quem compara os dois percebe quando não batem.
**Onde apareceu:** `lib/fire_engine/fetcher.py` (`_CLIENT_HINTS`, `_TARGET_HEADERS`), #136 e #157, 2026-11-20.
**Por que importa pra decisão:** com um `--user-agent` próprio, os hints do perfil diriam outro navegador; por isso o dograpper os derruba, e troca pelo `?1` o `?0` que o alvo Android do `curl_cffi` manda.
**Nível:** 🆕 novo

## upgrade h2c
**Em uma frase:** pedido de um cliente a um servidor `http://` (sem TLS) para trocar a conversa para HTTP/2 no meio da conexão, com os headers `Upgrade: h2c` e `HTTP2-Settings`; nenhum navegador faz isso.
**Analogia:** chegar a um balcão e pedir para seguir o atendimento num idioma que só robô fala.
**Onde apareceu:** `lib/fire_engine/fetcher.py` (`HTTP_VERSION` = `V2TLS`), #156, 2026-11-20.
**Por que importa pra decisão:** essas linhas denunciavam o fire-engine como não-navegador em sites só `http://`; com HTTP/2 só sobre TLS elas somem, e o HTTPS segue em HTTP/2.
**Nível:** 🆕 novo

## p99 (percentil 99)
**Em uma frase:** o tamanho abaixo do qual ficam 99% dos registros; só o 1% maior passa dele.
**Analogia:** numa fila de 100 pessoas em ordem de altura, a altura da 99ª: diz quão alto é "quase todo mundo" sem deixar o mais alto de todos decidir.
**Onde apareceu:** limite de palavras por registro de membro na tabela da ADR-0009; o Doxygen ficou com ≤ 550 depois da medição de `docs/discovery/doxygen-api-records-acceptance.md` (ICU 506, libstdc++ 138), 2026-11-20.
**Por que importa pra decisão:** um p99 baixo exige cortar a documentação dos membros mais longos; um alto aceita registros maiores, que podem cair no ranking da busca (o `ucnv_open`, com 325 palavras, caiu).
**Nível:** 🆕 novo

## restrição de template (C++, SFINAE)
**Em uma frase:** uma condição escrita na lista de parâmetros de um template de C++ que decide para quais tipos aquela versão da função existe; duas sobrecargas podem diferir só nela.
**Analogia:** duas portas com a mesma placa, cada uma com um porteiro que só deixa passar um tipo de visitante.
**Onde apareceu:** `std::optional` e `std::pair` do libstdc++, cujas sobrecargas assim recebem a mesma âncora do Doxygen 1.9.8 e por isso ficam inteiras em `pack --api-records` (`docs/discovery/doxygen-api-records-acceptance.md`, 2026-11-20).
**Por que importa pra decisão:** dois registros com o mesmo id quebram a regra de um id por registro, então a página inteira vira um registro só; juntar as duas sobrecargas num registro seria uma regra nova a decidir.
**Nível:** 🆕 novo
