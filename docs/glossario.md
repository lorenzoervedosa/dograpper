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
