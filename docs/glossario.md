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
