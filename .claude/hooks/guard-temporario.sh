#!/usr/bin/env bash
# Guardrail PreToolUse: bloqueia escrita/edição dentro de ./temporario/
# Alinhado ao contrato 8 do CLAUDE.md ("ignorar tudo em ./temporario/").
# Recebe o payload da tool em JSON via stdin; bloqueia com exit 2.
set -euo pipefail

payload="$(cat)"
path="$(printf '%s' "$payload" \
  | python3 -c "import sys, json
try:
    d = json.load(sys.stdin)
    print(d.get('tool_input', {}).get('file_path', ''))
except Exception:
    print('')" 2>/dev/null || true)"

case "$path" in
  */temporario/*|temporario/*)
    echo 'Bloqueado: ./temporario/ é ignorado pelo projeto (CLAUDE.md, contrato 8).' >&2
    exit 2
    ;;
esac
exit 0
