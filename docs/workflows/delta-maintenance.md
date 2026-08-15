# Manutenção Incremental com Delta Pack

## O problema
Re-processar documentação inteira a cada update é lento e gera
diff desnecessário em pipelines de CI/CD.

## Solução: --delta
`--delta` é um **portão de mudança**: decide se o pack roda, não quais
arquivos ele empacota. Nada mudou desde o último pack → sai sem escrever
nada. Algo mudou → pack completo, com todos os artefatos íntegros.

```bash
# Primeira vez: sem estado anterior, empacota tudo
dograpper pack ./docs -o ./chunks --delta

# Updates: no-op barato quando a documentação não mudou
dograpper pack ./docs -o ./chunks --delta
```

Empacotar sempre no **mesmo** diretório de saída é o ponto: o estado do
corpus fica em `<output-dir>/pack_state.json` e é ele que o próximo run
compara. Um diretório novo a cada run não tem baseline e sempre
re-empacota.

Arquivos excluídos por `.docsignore`/`--ignore` não disparam o portão;
remoções disparam.

## Sync: download + delta em um comando
```bash
dograpper sync <url> -o ./docs
```

## CI/CD
```yaml
# GitHub Actions example
- run: dograpper sync ${{ env.DOCS_URL }} -o ./docs --chunks-dir ./chunks --score
# Upload ./chunks para o vector DB
```

Para que o portão funcione em runners stateless, versione o diretório de
chunks (incluindo `pack_state.json`) no repositório — a mesma premissa
da [ADR-0007](../adr/0007-freshness-action-and-drift-command.md).

## delta_manifest.json
Gerado automaticamente com mapeamento de arquivos added/modified/removed
e quais chunks foram gerados. Como o run que o escreve é um pack
completo, `chunks_generated` lista todos os chunks, não só os que
contêm arquivos alterados.

## Referência
[ADR-0008](../adr/0008-delta-as-a-change-gate.md) registra a decisão e o
que ela substitui.
