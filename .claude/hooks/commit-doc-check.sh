#!/usr/bin/env bash
# PostToolUse(Bash) after a command that runs git commit: inject harness reminders
# about the HEAD commit: (a) contract files changed without any doc change;
# (b) a feat/fix commit without CHANGELOG.md. Reminders only: it never blocks
# and exits 0 silently on any error of its own.
# The repository is the one the commit ran in: a leading `cd DIR &&` or
# `git -C DIR` (worktree sessions), else the tool cwd, else the project dir.
# Tests: tests/test_claude_hooks.py.
set -u
input=$(cat) || exit 0
case "$input" in *git*commit*) ;; *) exit 0 ;; esac
repo=$(printf '%s' "$input" | python3 -c 'import json, os, re, shlex, sys
try:
    d = json.load(sys.stdin)
    cmd = (d.get("tool_input") or {}).get("command") or ""
    word = r"(\"[^\"]*\"|\x27[^\x27]*\x27|[^\s;&|]+)"
    m = re.match(r"\s*cd\s+" + word + r"\s*&&", cmd) or re.search(r"\bgit\s+-C\s+" + word + r"\s+commit\b", cmd)
    cwd = d.get("cwd") or ""
    print(os.path.join(cwd, shlex.split(m.group(1))[0]) if m else cwd)
except Exception:
    pass' 2>/dev/null) || exit 0
cd "${repo:-${CLAUDE_PROJECT_DIR:-.}}" 2>/dev/null || exit 0
files=$(git show --pretty=format: --name-only HEAD 2>/dev/null) || exit 0
subject=$(git log -1 --pretty=%s HEAD 2>/dev/null) || exit 0

notes=""

# Contract set mirrored from the case map in harness-reminder.sh; keep both in sync.
if printf '%s\n' "$files" | grep -qE '^(src/dograpper/(cli\.py|commands/|lib/(chunker|config_loader|manifest|pack_artifacts|page_layout|mcp_server)\.py|lib/httrack/|utils/heading_extractor\.py|utils/api_reference/)|action\.yml$)'; then
  if ! printf '%s\n' "$files" | grep -qE '^(docs/|README\.md$|CLAUDE\.md$|GLOSSARY\.md$|\.dograpper\.json\.example$)'; then
    notes="Harness: the HEAD commit touched contract files (CLI, pack formats, config, manifest, httrack, Action) without any change in docs/, README.md, CLAUDE.md or GLOSSARY.md. If it changes a contract or a decision, make the matching docs commit NOW; if not, go on."
  fi
fi

case "$subject" in
  feat:*|feat\(*|feat!*|fix:*|fix\(*|fix!*)
    if ! printf '%s\n' "$files" | grep -q '^CHANGELOG\.md$'; then
      notes="$notes${notes:+ }Harness: ${subject%%:*} commit without CHANGELOG.md. If the change is observable by the user and no other commit of this PR adds its entry, add one under [Unreleased] (rules in the CHANGELOG.md header); if it is internal, go on."
    fi
    ;;
esac

[ -z "$notes" ] && exit 0
python3 -c 'import json, sys
print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": sys.argv[1]}}))' "$notes" 2>/dev/null
exit 0
