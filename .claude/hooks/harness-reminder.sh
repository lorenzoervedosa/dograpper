#!/usr/bin/env bash
# PostToolUse(Write|Edit|MultiEdit): when the edited file carries a project
# contract, inject a reminder to evaluate the docs that describe it before
# committing (CLAUDE.md, "Manutenção do harness"). Reminder only: it never
# blocks and exits 0 silently on any error of its own.
# Paths match by suffix so edits inside .claude/worktrees/* are covered too.
# The contract set is mirrored by the regex in commit-doc-check.sh; keep both in sync.
# Tests: tests/test_claude_hooks.py.
set -u
file=$(python3 -c 'import json, sys
try:
    print((json.load(sys.stdin).get("tool_input") or {}).get("file_path") or "")
except Exception:
    pass' 2>/dev/null) || exit 0

case "$file" in
  *src/dograpper/utils/heading_extractor.py|*src/dograpper/lib/chunker.py|*src/dograpper/utils/api_reference/*)
    docs="docs/schema-v1.md (dograpper-context-v1 header and JSONL record fields) and README.md" ;;
  *src/dograpper/lib/config_loader.py|*src/dograpper/commands/sync.py)
    docs="the config-precedence contract in CLAUDE.md, the config section of README.md and .dograpper.json.example" ;;
  *src/dograpper/lib/manifest.py|*src/dograpper/lib/pack_artifacts.py)
    docs="docs/adr/0008-delta-as-a-change-gate.md (delta and sidecar formats) and README.md" ;;
  *src/dograpper/lib/page_layout.py|*src/dograpper/commands/_page_layout.py)
    docs="docs/adr/0010-per-page-pack-layout.md and README.md" ;;
  *src/dograpper/lib/httrack/*|*src/dograpper/commands/_httrack_profile.py)
    docs="docs/superpowers/specs/2026-11-13-httrack-downloader-profile-design.md and README.md" ;;
  *src/dograpper/cli.py|*src/dograpper/commands/*|*src/dograpper/lib/mcp_server.py)
    docs="README.md (the observable contract), CHANGELOG.md and tests/fixtures/help_baseline.txt" ;;
  *action.yml)
    docs="docs/adr/0007-freshness-action-and-drift-command.md and README.md" ;;
  *) exit 0 ;;
esac

rel=${file#"${CLAUDE_PROJECT_DIR:-}"/}
msg="Harness: you edited $rel, which carries a project contract. Before committing, evaluate $docs, plus docs/adr/, docs/DECISIONS.md, docs/DEBT.md and CLAUDE.md (section \"Manutenção do harness\"). If none needs a change, say why and go on."
python3 -c 'import json, sys
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": sys.argv[1]}}))' "$msg" 2>/dev/null
exit 0
