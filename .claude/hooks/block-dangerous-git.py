#!/usr/bin/env python3
"""PreToolUse(Bash) guard: blocks destructive git commands, amends of
published commits and direct pushes to a shared branch, enforcing the
consent rules of the global CLAUDE.md and this repo's PR-only flow.

Threat model: a best-effort guard against ACCIDENTAL destructive git commands
typed by an agent or a person. It is not a sandbox: a deliberate bypass (an
alias already in git config, git invoked from another language, `eval` of a
constructed string) is out of scope by design. The consent rules in CLAUDE.md
remain the control.

Ported from open-notes `.claude/hooks/block-dangerous-git.py`. Differences:
the escape hatches use the DOGRAPPER_ prefix, a push to `main`/`develop` needs
user consent (every change lands through a reviewed PR; there is no local
merge to attest), and the hook fails OPEN on its own errors (bad JSON, an
exception): a broken guard must never stop normal Bash work.

Escape hatches are inert env-var prefixes recorded in the transcript — they
force an explicit, auditable claim instead of silent compliance:
  DOGRAPPER_USER_APPROVED=1  the user consented to THIS destructive command
  DOGRAPPER_BRANCH_MERGED=1  `git merge-base --is-ancestor <branch> origin/main` passed

Every git invocation of a compound command is checked (`;`, `&&`, `||`, `|`,
newlines, `$(…)`, `sh -c`, `eval`), each read by one tokenizer past the common
wrappers (`sudo`, `env`, `timeout`, `nice`, `nohup`, `command`, `exec`,
`time`) and with git's global options (`-C`, `-c`, `--git-dir`,
`--no-pager`…) stripped first. An inline alias (`-c alias.*`) blocks.

Data is not syntax: the body of a quoted-delimiter heredoc (`<<'EOF'`, `<<"EOF"`,
`<<-` too) and a `-m`/`--message` value that is single-quoted, or double-quoted
with no `$` and no backtick, are never read as git arguments or as unmodelled
syntax. An unquoted heredoc, `$`, backtick, a backslash or `#` outside such data
stay unreadable for the amend check and block (fail closed). A `<<` inside
quotes or in a comment opens no heredoc.

Exit 2 blocks the tool call (stderr is shown to the agent); exit 0 allows.
Python (not sed) because `command` may be multi-line JSON-escaped text.
Tests: tests/test_claude_hooks.py.
"""

import json
import os
import re
import shlex
import subprocess
import sys

# One shell word: quoted and unquoted pieces glued together (`"/a"/b` is one).
# `#` is excluded: at the start of a word it opens a comment.
_WORD = r"""(?:"[^"]*"|'[^']*'|[^\s;&|()<>"'#])+"""
_QUOTED = re.compile(r"""'[^']*'|"[^"]*\"""")
# `--amend` and the prefixes git accepts for it (`--am`, `--ame`, `--amen`).
_AMEND_FLAG = r"--am(?:e(?:nd?)?)?(?![\w-])"
# Arguments of a simple command: up to a real separator. `>&`/`<&`/`&>` are
# redirections, not separators (`git commit 2>&1 --amend` is still an amend).
_ARGS = r"(?:[^|;&\n]|(?<=[<>])&|&(?=>))*"
# `git [global options] commit ... --amend` in one simple command. Each option
# starts with `-` and its value does NOT: an unambiguous grammar, so `-a -a -a…`
# cannot open exponential backtracking paths.
_AMEND = re.compile(
    r"\bgit((?:[ \t]+-" + _WORD + r"(?:[ \t]+(?!-)" + _WORD + r")?)*?)[ \t]+commit\b" + _ARGS + _AMEND_FLAG
)
# The plain detector, over the command with quotes blanked: a spelling it sees
# and `_AMEND` does not (e.g. `git"" commit`) is an amend in an unknown repo.
_LEGACY_AMEND = re.compile(r"git\s+commit\b" + _ARGS + _AMEND_FLAG)
# The ONLY shape trusted before an amend: `cd WORD` and `git [-C P] add …` steps
# joined by `&&` — if the amend runs, every `cd` ran, so the directory is exact.
# Any other syntax (`;`, newline, `||`, pipe, `#`, redirection, subshell, env
# assignment, `export`, `pushd`, `eval`…) is not modelled: it blocks.
_STEP = re.compile(
    r"\s*(?:cd[ \t]+(" + _WORD + r")|git(?:[ \t]+-C[ \t]+" + _WORD + r")?[ \t]+add(?:[ \t]+" + _WORD + r")*)"
    r"[ \t]*&&"
)
# Variables that switch the repository without `cd` or `-C`.
_GIT_ENV = ("GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_INDEX_FILE")
# Syntax the quote mask cannot follow: escapes, substitutions, backticks and
# unquoted heredocs (quoted ones are stripped as data first) move where quotes open and close; a comment hides a command.
_SHELL_ONLY = re.compile(r"[\\$`]|<<|(?:^|\s)#")
# A `-m`/`--message` value that is data: single-quoted, or double-quoted with no
# `$` and no backtick (nothing in it expands).
_MESSAGE = re.compile(
    r"""'[^']*'|"[^"]*"|(?<!\S)(?P<flag>-[A-Za-z]*m|--message=?)[ \t]*(?:'[^']*'|"[^"$`]*")"""
)
# Branches every change reaches only through a reviewed PR.
_SHARED_BRANCHES = ("main", "develop")


def block(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.exit(2)


def _word(raw: str):
    """Value of one shell word, or None when only the shell could tell
    (variable, glob, backtick, escape, `~` past the first character)."""
    if re.search(r"[$`*?\[\\]", raw) or "~" in raw[1:]:
        return None
    try:
        parts = shlex.split(raw)
        return os.path.expanduser(parts[0]) if len(parts) == 1 else None
    except ValueError:  # includes NUL and unicode the system cannot encode
        return None


def _git_dir_args(raw_opts: str):
    """The `-C` paths among git's global options, in order; None for an option
    that changes the repository another way (`--git-dir`, `--work-tree`…) or
    an unreadable -C."""
    toks = re.findall(_WORD, raw_opts)
    parts, i = [], 0
    while i < len(toks):
        if toks[i] in ("-C", "-c") and i + 1 < len(toks):
            if toks[i] == "-C":
                p = _word(toks[i + 1])
                if p is None:
                    return None
                parts.append(p)
            i += 2
        else:
            return None
    return parts


def amend_repo_dirs(raw_cmd: str, cwd: str) -> list:
    """Directory each `git commit --amend` of the command runs in: the `cd`
    steps before it plus its own `git -C` — not the SESSION cwd, which in an
    agent worktree is the main checkout (another HEAD). Matched on a copy with
    the INSIDE of quotes masked (same length): quoted text never becomes a `cd`
    or an `--amend`, and each word is read back from the original at the same
    offsets. Only the `_STEP` shape is read; a `cd ..` is resolved like the
    shell (logically, without following links). None = a directory that cannot
    be known from here (blocks). Empty list = no amend.

    Data is dropped first: the body of a quoted-delimiter heredoc and a `-m`
    value that cannot expand never count as syntax or as an `--amend`."""
    # Quoted spans match first (left to right), so a `-m` inside one is never a flag.
    raw_cmd = _MESSAGE.sub(lambda m: m["flag"] + " ''" if m["flag"] else m[0],
                           _strip_heredocs(raw_cmd, only_quoted=True))
    # With syntax the mask cannot follow (or unpaired quotes), not even the
    # amend detection is reliable: any `commit` plus `--am…` in the text blocks.
    unpaired = re.search(r"['\"]", _QUOTED.sub("", raw_cmd))
    if (_SHELL_ONLY.search(raw_cmd) or unpaired) and re.search(r"\bcommit\b", raw_cmd) and re.search(_AMEND_FLAG, raw_cmd):
        return [None]
    masked = _QUOTED.sub(lambda q: q.group(0)[0] + "_" * (len(q.group(0)) - 2) + q.group(0)[-1], raw_cmd)
    env_override = any(os.environ.get(v) for v in _GIT_ENV)
    dirs, spans = [], []
    for m in _AMEND.finditer(masked):
        spans.append((m.start(), m.end()))
        base, pos = cwd, 0
        while step := _STEP.match(masked, pos, m.start()):
            if step.group(1):
                p = _word(raw_cmd[step.start(1):step.end(1)])
                # `-…` is an option or `cd -`; a relative path without `./` or
                # `../` goes through the shell's CDPATH, which the hook cannot see.
                if p is not None and (p.startswith("-") or not (os.path.isabs(p) or p in (".", "..") or p.startswith(("./", "../")))):
                    p = None
                base = None if p is None or base is None else os.path.normpath(os.path.join(base, p))
            pos = step.end()
        tail = _git_dir_args(raw_cmd[m.start(1):m.end(1)])
        if env_override or masked[pos:m.start()].strip() or tail is None or base is None:
            dirs.append(None)
        else:
            dirs.append(os.path.join(base, *tail))
    # The plain detector on the same text with quotes turned into spaces (same
    # offsets): an amend only it sees (e.g. `git"" commit`) is in an unknown repo.
    blanked = _QUOTED.sub(lambda q: " " * len(q.group(0)), raw_cmd)
    for lm in _LEGACY_AMEND.finditer(blanked):
        if not any(s < lm.end() and lm.start() < e for s, e in spans):
            dirs.append(None)
    return dirs


def head_is_published(repo) -> bool:
    """True when HEAD of `repo` is reachable from a remote-tracking ref, or
    when that cannot be checked (an amend there is treated as published)."""
    if repo is None:
        return True
    try:
        out = subprocess.run(
            ["git", "-C", repo, "branch", "-r", "--contains", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return True
    # git failed (wrong path, HEAD without a commit): cannot check.
    return out.returncode != 0 or out.stdout.strip() != ""


def current_branch(cwd: str):
    try:
        out = subprocess.run(
            ["git", "-C", cwd, "rev-parse", "--abbrev-ref", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
    except Exception:
        return None
    return out.stdout.strip() if out.returncode == 0 else None


# Global options of git that take their value as the next word.
_GIT_OPTS_WITH_ARG = frozenset({
    "-C", "-c", "--git-dir", "--work-tree", "--namespace", "--super-prefix",
    "--config-env", "--attr-source",
})
_SHELLS = frozenset({"sh", "bash", "zsh", "dash", "ksh"})
# Wrapper commands skipped before the real head, with their options that take
# the next word as value.
_WRAPPERS = {
    "sudo": frozenset({"-u", "-g", "-C", "-D", "-h", "-p", "-r", "-t", "-U", "-T"}),
    "env": frozenset({"-u", "-C"}),
    "timeout": frozenset({"-s", "-k"}),
    "nice": frozenset({"-n"}),
    "nohup": frozenset(),
    "command": frozenset(),
    "exec": frozenset({"-a"}),
    "time": frozenset(),
}
# Pathspecs that cover the whole work tree.
_WHOLE_TREE = frozenset({".", "./", ":/"})
# A heredoc opener (`<<EOF`, `<<-'EOF'`), not a here-string (`<<<`).
_HEREDOC = re.compile(r"(?<!<)<<-?[ \t]*(['\"]?)([A-Za-z_]\w*)\1")


def _strip_heredocs(raw: str, only_quoted: bool = False) -> str:
    """Drop heredoc bodies: they are data (a commit message), not commands.
    Quote- and comment-aware: a `<<` inside quotes or after a `#` opens no
    heredoc, so the next line stays a command. With `only_quoted` just the bodies of `<<'EOF'`/`<<"EOF"` go
    (and their opener, so `<<` stops looking like unmodelled syntax); an
    unquoted `<<EOF` body expands, so it stays in the text."""
    out, pending, quote, i, n, escaped_to = [], [], None, 0, len(raw), -1
    while i < n:
        c = raw[i]
        # A comment starts a word: after blank space or an operator, never after
        # an escaped character (`\\ #` is one word) or glued to a word.
        if not quote and c == "#" and i != escaped_to and (i == 0 or raw[i - 1] in " \t\n;&|()<>"):
            eol = raw.find("\n", i)  # a comment: a `<<` in it opens no heredoc
            eol = n if eol < 0 else eol
            out.append(raw[i:eol])
            i = eol
            continue
        m = None if quote or c != "<" else _HEREDOC.match(raw, i)
        if m:
            pending.append((m.group(2), bool(m.group(1))))
            out.append(" " if only_quoted and m.group(1) else m.group(0))
            i = m.end()
            continue
        out.append(c)
        if quote:
            if c == "\\" and quote == '"' and i + 1 < n:
                out.append(raw[i + 1])
                i += 1
            elif c == quote:
                quote = None
        elif c == "\\" and i + 1 < n:
            out.append(raw[i + 1])
            i += 1
            escaped_to = i + 1
        elif c in "'\"":
            quote = c
        elif c == "\n" and pending:
            i += 1
            for delim, quoted in pending:
                start = i
                while i < n:  # through the delimiter line
                    eol = raw.find("\n", i)
                    eol = n if eol < 0 else eol
                    done = raw[i:eol].strip() == delim
                    i = min(eol + 1, n)
                    if done:
                        break
                if only_quoted and not quoted:
                    out.append(raw[start:i])
            pending = []
            continue
        i += 1
    return "".join(out)


def _segments(raw: str) -> list:
    """Simple commands of `raw`: split on `;`, `&`, `&&`, `|`, `||`, newlines,
    parentheses and backticks outside quotes. `>&`, `<&` and `&>` stay inside
    (redirections). Quoted text, including a `$(…)` inside double quotes, is
    not split: evasion through quoting is outside the threat model."""
    segs, buf, quote, i = [], [], None, 0
    while i < len(raw):
        c = raw[i]
        if quote:
            buf.append(c)
            if c == "\\" and quote == '"' and i + 1 < len(raw):
                buf.append(raw[i + 1])
                i += 1
            elif c == quote:
                quote = None
        elif c == "\\" and i + 1 < len(raw):
            buf.append(raw[i:i + 2])
            i += 1
        elif c in "'\"":
            quote = c
            buf.append(c)
        elif c in ";|\n()`" or (c == "&" and not (i and raw[i - 1] in "<>") and raw[i + 1:i + 2] != ">"):
            segs.append("".join(buf))
            buf = []
        else:
            buf.append(c)
        i += 1
    segs.append("".join(buf))
    return [seg for seg in segs if seg.strip()]


def _head_index(toks) -> int:
    """Index of the command a simple command really runs: past `VAR=val`
    prefixes and the wrappers of `_WRAPPERS` with their options (`timeout`
    also takes its duration)."""
    i = 0
    while i < len(toks):
        if re.fullmatch(r"[A-Za-z_]\w*=.*", toks[i], re.S):
            i += 1
            continue
        name = os.path.basename(toks[i])
        if name not in _WRAPPERS:
            return i
        i += 1
        while i < len(toks) and toks[i].startswith("-") and toks[i] != "--":
            i += 2 if toks[i] in _WRAPPERS[name] else 1
        if i < len(toks) and toks[i] == "--":
            i += 1
        if name == "timeout":
            i += 1
    return i


def git_invocations(raw: str, depth: int = 0):
    """Yield (dirs, subcommand, args, alias) for every git invocation of
    `raw`, with git's global options stripped (`dirs` = its `-C` paths, in
    order; `alias` = an inline `-c alias.*` or `--config-env=alias.*`). A
    segment that mentions git but does not tokenize yields None (blocks).
    `sh -c '…'` and `eval …` are read recursively."""
    for seg in _segments(_strip_heredocs(raw)):
        try:
            toks = shlex.split(seg, comments=True)
        except ValueError:
            if re.search(r"\bgit\b", seg):
                yield None
            continue
        if not toks:
            continue
        h = _head_index(toks)
        if h >= len(toks):
            continue
        head = os.path.basename(toks[h])
        if depth < 3 and head == "eval":
            yield from git_invocations(" ".join(toks[h + 1:]), depth + 1)
            continue
        if depth < 3 and head in _SHELLS:
            for k in range(h + 1, len(toks) - 1):
                if re.fullmatch(r"-[A-Za-z]*c[A-Za-z]*", toks[k]):
                    yield from git_invocations(toks[k + 1], depth + 1)
                    break
            continue
        # From the head on, not only at it: `xargs git …`, `find -exec git …`.
        i = next((k for k in range(h, len(toks)) if os.path.basename(toks[k]) == "git"), None)
        if i is None:
            continue
        i, dirs, alias = i + 1, [], False
        while i < len(toks) and toks[i].startswith("-"):
            opt = toks[i]
            name, _, inline = opt.partition("=")
            if opt in _GIT_OPTS_WITH_ARG:
                val = toks[i + 1] if i + 1 < len(toks) else ""
                if opt == "-C":
                    dirs.append(os.path.expanduser(val))
                i += 2
            else:  # `--git-dir=…`, `--config-env=…`, `--no-pager`, `-P`, …
                val = inline
                i += 1
            if name in ("-c", "--config-env") and val.lower().startswith("alias."):
                alias = True
        if i < len(toks):
            yield dirs, toks[i], toks[i + 1:], alias


def _short(args, letters: str) -> bool:
    """Some short-option cluster (`-f`, `-uf`, `-fu`) holds one of `letters`."""
    return any(re.fullmatch(r"-[A-Za-z0-9]+", a) and set(a[1:]) & set(letters) for a in args)


def _long(args, option: str, min_len: int) -> bool:
    """`option` is given, with or without `=value`, or as an abbreviation of at
    least `min_len` characters (git accepts unambiguous prefixes)."""
    for a in args:
        name = a.split("=", 1)[0]
        if a.startswith("--") and len(name) >= min_len and option.startswith(name):
            return True
    return False


def pushes_shared_branch(args, pos, repo: str) -> bool:
    shared = "|".join(_SHARED_BRANCHES)
    if re.search(r"(^|[\s:]|refs/heads/)(" + shared + r")(?![\w./-])", " ".join(args)):
        return True
    # A push without a refspec, or of HEAD, pushes the current branch.
    # shortcut: `repo` is the session cwd plus `git -C`, not a `cd DIR &&` before
    # the push; give the refspec explicitly to push from elsewhere.
    if len(pos) <= 1 or any(a in ("HEAD", "@") for a in pos[1:]):
        return current_branch(repo) in _SHARED_BRANCHES
    return False


def main() -> None:
    try:
        data = json.loads(sys.stdin.read())
    except json.JSONDecodeError:
        sys.exit(0)  # fail open: the harness sent something this guard does not read
    raw_cmd = ((data.get("tool_input") or {}).get("command") or "") if isinstance(data, dict) else ""
    if "git" not in raw_cmd:
        sys.exit(0)
    # Backslash-newline continues the command: join it (same length).
    raw_cmd = raw_cmd.replace("\\\n", "  ")
    cwd = data.get("cwd") or "."
    # Patterns are matched on the command WITHOUT its quoted parts: quoted text
    # (a commit message, an echo) is not a command. Evasion through quotes is
    # not a threat model here — the escape hatch already allows a declared bypass.
    cmd = re.sub(r"'[^']*'|\"[^\"]*\"", " ", raw_cmd)

    approved = "DOGRAPPER_USER_APPROVED=1" in cmd
    merged_ok = "DOGRAPPER_BRANCH_MERGED=1" in cmd

    consent_msg = (
        "Global rule: this destructive operation needs the user's explicit "
        "consent EVERY time. Show the exact command and what it affects, wait "
        "for approval in the conversation, and only then re-run it prefixed "
        "with DOGRAPPER_USER_APPROVED=1 (the claim stays in the transcript)."
    )

    branch_msg = (
        "BLOCKED: branch deletion. Pre-authorized only for a branch ALREADY "
        "MERGED: check `git merge-base --is-ancestor <branch> origin/main` "
        "and re-run prefixed with DOGRAPPER_BRANCH_MERGED=1. An unmerged "
        "branch needs the user's consent (DOGRAPPER_USER_APPROVED=1 after "
        "approval in the conversation)."
    )

    # Checks 1-3 and 5 run on EVERY git invocation of the command, each read
    # by the same tokenizer with git's global options already stripped.
    for inv in git_invocations(raw_cmd):
        if inv is None:
            if not approved:
                block("BLOCKED: a git command this guard cannot tokenize (unbalanced "
                      "quotes?). Rewrite it with plain quoting. " + consent_msg)
            continue
        dirs, sub, args, alias = inv
        pos = [a for a in args if not a.startswith("-")]
        if alias and not approved:
            block("BLOCKED: `-c alias.*` / `--config-env=alias.*` defines a git alias "
                  "inline, and this guard does not expand aliases. Run the git "
                  "command it stands for directly. " + consent_msg)

        if sub == "push":
            # 1. Force push (--force, --force-with-lease[=…], -f in any short
            #    cluster, a `+` refspec) and pushes of many refs at once
            #    (--mirror, --all, --prune, a `*` refspec).
            if not approved and (_long(args, "--force", 6) or _long(args, "--force-with-lease", 6)
                                 or _long(args, "--mirror", 4) or _long(args, "--all", 4)
                                 or _long(args, "--prune", 5) or _short(args, "f")
                                 or any(a.startswith("+") or "*" in a for a in pos)):
                block("BLOCKED: force push, or a push of many remote refs at once "
                      "(--mirror, --all, --prune, a `*` refspec). " + consent_msg)
            # 3. Remote branch deletion: --delete, -d, or a `:ref` refspec.
            if not (merged_ok or approved) and (_long(args, "--delete", 5) or _short(args, "d")
                                                or any(a.startswith(":") and len(a) > 1 for a in pos)):
                block(branch_msg)
            # 5. Direct push to a shared branch: every change lands through a PR.
            if not approved and pushes_shared_branch(args, pos, os.path.join(cwd, *dirs)):
                block(
                    "BLOCKED: direct push to a shared branch (" + ", ".join(_SHARED_BRANCHES) + "). "
                    "Every change lands through a reviewed PR: push a feature branch "
                    "and open the PR instead. " + consent_msg
                )
        elif sub == "branch":
            # 3. Forced local deletion: a delete flag plus force, in any order
            #    (-D is both). A plain -d stays allowed: git refuses it on an
            #    unmerged branch.
            delete = _long(args, "--delete", 5) or _short(args, "dD")
            force = _long(args, "--force", 6) or _short(args, "fD")
            if delete and force and not (merged_ok or approved):
                block(branch_msg)
        elif approved:
            continue
        # 2. Discarding local work.
        elif sub == "reset" and _long(args, "--hard", 5):
            block("BLOCKED: git reset --hard discards local work. " + consent_msg)
        elif sub == "clean" and (_short(args, "f") or _long(args, "--force", 4)):
            block("BLOCKED: git clean -f deletes untracked files. " + consent_msg)
        elif sub in ("checkout", "restore") and _WHOLE_TREE & set(pos):
            block("BLOCKED: checkout/restore of '.' discards ALL local changes. " + consent_msg)
        elif sub == "gc" and any(a.startswith("--prune") for a in args):
            block("BLOCKED: git gc --prune destroys recoverable objects. " + consent_msg)

    # 4. Amend of a published commit (HEAD reachable from a remote ref),
    #    checked in the repository where EACH amend of the command runs.
    if not approved and any(head_is_published(d) for d in amend_repo_dirs(raw_cmd, cwd)):
        block(
            "BLOCKED: --amend of a commit already on a remote ref, or in a "
            "command this guard cannot read for sure. Accepted shape: `cd <dir> "
            "&& [git add ... &&] git commit --amend ...` or `git -C <dir> commit "
            "--amend ...`, with <dir> absolute, ./ or ../, and no `$`, backtick, "
            "backslash, unquoted heredoc or `#` outside a quoted heredoc body or "
            "a `-m '…'` / `-m \"…\"` value without `$` or backtick (new message: "
            "`-F <file>`). "
            "Or use `git commit --fixup=<sha>`. " + consent_msg
        )

    sys.exit(0)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:  # fail open: a crash in the guard must not stop Bash work
        sys.stderr.write(f"block-dangerous-git: internal error ({type(e).__name__}); allowing.\n")
        sys.exit(0)
