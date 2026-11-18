"""Claude Code hooks in .claude/hooks, run as CLI programs.

Each hook reads the tool payload as JSON on stdin. The PreToolUse guard
answers with its exit code (2 blocks, 0 allows); the PostToolUse reminders
always exit 0 and print a hookSpecificOutput JSON only when they have
something to say. The git cases build throwaway repositories: a bare remote,
a clone whose HEAD is published, and a worktree whose HEAD was never pushed.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

HOOKS = Path(__file__).resolve().parent.parent / ".claude" / "hooks"
GIT = ["git", "-c", "user.name=t", "-c", "user.email=t@t", "-c", "commit.gpgsign=false"]
AMEND = "git commit --amend --no-edit"


def _env(**extra):
    # The guard reads GIT_DIR & co. from its environment: never inherit them.
    env = {k: v for k, v in os.environ.items()
           if not k.startswith("GIT_") and k != "CLAUDE_PROJECT_DIR"}
    env.update(extra)
    return env


def run_hook(name, payload, cwd=None, **env):
    cmd = [sys.executable, str(HOOKS / name)] if name.endswith(".py") else ["bash", str(HOOKS / name)]
    stdin = payload if isinstance(payload, str) else json.dumps(payload)
    return subprocess.run(cmd, input=stdin, capture_output=True, text=True,
                          cwd=cwd, env=_env(**env), timeout=30)


def git(*args, cwd):
    subprocess.run([*GIT, *args], cwd=cwd, check=True, capture_output=True, env=_env())


def _context(result):
    assert result.returncode == 0, result.stderr
    if not result.stdout.strip():
        return None
    out = json.loads(result.stdout)["hookSpecificOutput"]
    assert out["hookEventName"] == "PostToolUse"
    return out["additionalContext"]


# -- block-dangerous-git.py (PreToolUse Bash) --------------------------------

def guard(command, cwd):
    payload = {"tool_input": {"command": command}, "cwd": str(cwd)}
    return run_hook("block-dangerous-git.py", payload).returncode


@pytest.fixture(scope="module")
def repos(tmp_path_factory):
    root = tmp_path_factory.mktemp("repos")
    remote, main, wt = root / "remote.git", root / "main", root / "wt"
    git("init", "-q", "--bare", str(remote), cwd=root)
    git("init", "-q", "-b", "main", str(main), cwd=root)
    git("remote", "add", "origin", str(remote), cwd=main)
    git("commit", "-q", "--allow-empty", "-m", "published", cwd=main)
    git("push", "-q", "origin", "HEAD:main", cwd=main)
    git("fetch", "-q", "origin", cwd=main)
    git("worktree", "add", "-q", "-b", "feat", str(wt), cwd=main)
    git("commit", "-q", "--allow-empty", "-m", "unpushed", cwd=wt)
    return main, wt


@pytest.mark.parametrize("command", [
    "git push --force origin feat/x",
    "git push --force-with-lease",
    "git push origin +feat/x:feat/x",
    "git reset --hard HEAD~1",
    "git clean -fd",
    "git checkout .",
    "git restore -- .",
    "git gc --prune=now",
    "git branch -D feat/x",
    "git push origin --delete feat/x",
    "git push origin :feat/x",
    "git push origin main",
    "git push origin HEAD:main",
    "cd /tmp && git push -u origin develop",
])
def test_guard_blocks_destructive_and_shared_branch_commands(command, tmp_path):
    assert guard(command, tmp_path) == 2


# Bypasses found in review: each row must block.
@pytest.mark.parametrize("command", [
    # every git invocation of a compound command is checked, not only the first
    "git status && git push --force origin x",
    "git push -u origin feat && git push --force origin feat",
    "git fetch; git reset --hard origin/main",
    "git log | head; git branch -D x",
    "true || git clean -fd",
    "git status\ngit push origin main",
    "echo $(git push -f origin x)",
    "echo `git clean -fdx`",
    "{ git push -f; }",
    "bash -c 'git push --force origin x'",
    "eval git reset --hard",
    "sudo git reset --hard",
    # git global options before the subcommand
    "git -C /tmp/x push --force",
    "git -c core.x=y reset --hard",
    "git --git-dir=/tmp/x/.git branch -D x",
    "git --work-tree=/tmp/x --git-dir /tmp/x/.git clean -fd",
    "git --no-pager push origin main",
    "git -P checkout .",
    # force push spellings
    "git push --force-with-lease=main:abc123 origin feat",
    "git push -uf origin x",
    "git push -fu origin x",
    "git push 2>&1 --force origin x",
    "git push origin +main",
    "git push origin +HEAD:main",
    "git push origin HEAD:refs/heads/main",
    # forced branch deletion, any order
    "git branch -df x",
    "git branch -fd x",
    "git branch --delete --force x",
    "git branch --force --delete x",
    "git branch -d -f x",
    # a git segment that does not tokenize fails closed
    'git commit -m "unterminated',
])
def test_guard_blocks_review_bypasses(command, tmp_path):
    assert guard(command, tmp_path) == 2


# Second review round: wrappers, pushes of many refs, inline aliases.
@pytest.mark.parametrize("command", [
    "sudo -u root git push --force origin x",
    "env -i PATH=/usr/bin git reset --hard",
    "env -u HOME git clean -fd",
    "timeout 30 git push -f origin x",
    "timeout -s KILL 30 git branch -D x",
    "nice -n 10 git reset --hard",
    "nohup git push --force origin x",
    "command git reset --hard",
    "exec git clean -fd",
    "time git push -f origin x",
    "sudo bash -c 'git push --force origin x'",
    "env X=1 sh -c 'git reset --hard'",
    "timeout 5 bash -lc 'git clean -fd'",
    "git push --mirror origin",
    "git push --all origin",
    "git push --prune origin",
    "git push origin 'refs/heads/*:refs/heads/*'",
    "git push -d origin x",
    "git -c alias.p='push --force' p",
    "git -c Alias.wipe='reset --hard' wipe",
    "git --config-env=alias.p=GIT_P p",
    "git --config-env alias.p=GIT_P p",
])
def test_guard_blocks_wrappers_bulk_pushes_and_inline_aliases(command, tmp_path):
    assert guard(command, tmp_path) == 2


@pytest.mark.parametrize("command", [
    "ls -la",
    "git status && git log --oneline -5",
    "git push -u origin feat/main-menu",
    "git push origin main-fix",
    'git commit -m "explain git reset --hard and git push --force"',
    "git checkout -b feat/x",
    "git restore src/dograpper/cli.py",
    "DOGRAPPER_USER_APPROVED=1 git reset --hard HEAD~1",
    "DOGRAPPER_USER_APPROVED=1 git push --force origin feat/x",
    "DOGRAPPER_BRANCH_MERGED=1 git branch -D feat/x",
    "git -C /tmp/x status",
    "git branch -d merged-branch",
    "git branch -f x main",
    "git log --force",
    "git fetch --force",
    "git clean -n",
    "git reset --soft HEAD~1",
    "git gc",
    "git push origin feat # --force",
    "git log --format='%h (%s)' | head -3",
    "git commit -m 'explain git push --force; git reset --hard'",
    "cat <<'EOF' > /tmp/m\nDon't git push --force\nEOF\ngit commit -F /tmp/m",
    "git commit -m \"$(cat <<'EOF'\nfix: it's git push --force safe\nEOF\n)\"",
    "sudo apt-get install wget",
    "env FOO=1 uv run pytest tests/ -q",
    "timeout 600 uv run pytest tests/ -q",
    "nice -n 5 git status",
    "time git log -3",
    "bash -c 'git status'",
    "git -c core.pager=cat log -3",
    "git -c user.name=x commit -m 'docs: explain push --all'",
    "git push --tags origin",
    "git push --dry-run origin feat",
    "DOGRAPPER_BRANCH_MERGED=1 git push origin --delete feat/x",
])
def test_guard_allows_normal_and_attested_commands(command, tmp_path):
    assert guard(command, tmp_path) == 0


@pytest.mark.parametrize("stdin", ["not json", "", "[1, 2]", '{"tool_input": null}'])
def test_guard_fails_open_on_input_it_cannot_read(stdin):
    assert run_hook("block-dangerous-git.py", stdin).returncode == 0


def test_guard_blocks_an_amend_of_a_published_head(repos):
    main, wt = repos
    assert guard(AMEND, main) == 2
    assert guard(f"cd {main} && {AMEND}", wt) == 2
    assert guard(f"git -C {main} commit --amend --no-edit", wt) == 2
    assert guard(f"DOGRAPPER_USER_APPROVED=1 {AMEND}", main) == 0


def test_guard_checks_the_repo_each_amend_runs_in(repos):
    main, wt = repos
    assert guard(AMEND, wt) == 0
    assert guard(f'cd "{wt}" && git add -A && {AMEND}', main) == 0
    assert guard(f"git -C {wt} commit --amend --no-edit", main) == 0
    assert guard('git commit -m "explain --amend"', main) == 0


def test_guard_blocks_an_amend_it_cannot_place(repos):
    main, wt = repos
    assert guard(f"cd $HOME && {AMEND}", wt) == 2
    assert guard(f"cd {wt}; {AMEND}", main) == 2


def test_guard_blocks_a_bare_push_from_a_shared_branch(repos):
    main, wt = repos
    assert guard("git push", main) == 2
    assert guard("git push origin", main) == 2
    assert guard("git push origin HEAD", main) == 2
    assert guard(f"git -C {main} push", wt) == 2
    assert guard("git push", wt) == 0
    assert guard(f"git -C {wt} push", main) == 0


# -- harness-reminder.sh (PostToolUse Write|Edit|MultiEdit) ------------------

def reminder(file_path, project_dir):
    payload = {"tool_name": "Edit", "tool_input": {"file_path": str(file_path)}}
    return _context(run_hook("harness-reminder.sh", payload, CLAUDE_PROJECT_DIR=str(project_dir)))


@pytest.mark.parametrize("rel, doc", [
    ("src/dograpper/lib/chunker.py", "docs/schema-v1.md"),
    ("src/dograpper/utils/heading_extractor.py", "docs/schema-v1.md"),
    ("src/dograpper/utils/api_reference/javadoc.py", "docs/schema-v1.md"),
    ("src/dograpper/lib/config_loader.py", "config-precedence contract"),
    ("src/dograpper/commands/sync.py", "config-precedence contract"),
    ("src/dograpper/commands/download.py", "README.md (the observable contract)"),
    ("src/dograpper/cli.py", "tests/fixtures/help_baseline.txt"),
    ("src/dograpper/lib/manifest.py", "docs/adr/0008-delta-as-a-change-gate.md"),
    ("src/dograpper/commands/_page_layout.py", "docs/adr/0010-per-page-pack-layout.md"),
    ("src/dograpper/lib/httrack/fetcher.py", "httrack-downloader-profile-design.md"),
    ("action.yml", "docs/adr/0007-freshness-action-and-drift-command.md"),
])
def test_reminder_names_the_docs_of_a_contract_file(rel, doc, tmp_path):
    context = reminder(tmp_path / rel, tmp_path)
    assert doc in context
    assert f"you edited {rel}," in context
    assert "docs/DECISIONS.md, docs/DEBT.md" in context


def test_reminder_covers_edits_inside_a_worktree(tmp_path):
    edited = tmp_path / ".claude" / "worktrees" / "wave" / "src" / "dograpper" / "lib" / "chunker.py"
    assert "docs/schema-v1.md" in reminder(edited, tmp_path)


def test_reminder_output_stays_valid_json_for_any_path(tmp_path):
    assert "README.md" in reminder(tmp_path / 'src/dograpper/commands/a"b\\c.py', tmp_path)


@pytest.mark.parametrize("rel", ["tests/test_pack.py", "README.md", "src/dograpper/utils/logger.py"])
def test_reminder_stays_silent_for_other_files(rel, tmp_path):
    assert reminder(tmp_path / rel, tmp_path) is None


@pytest.mark.parametrize("stdin", ["not json", "", '{"tool_input": null}'])
def test_reminder_fails_open_on_input_it_cannot_read(stdin):
    assert _context(run_hook("harness-reminder.sh", stdin)) is None


# -- commit-doc-check.sh (PostToolUse Bash) ----------------------------------

@pytest.fixture
def commit(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    git("init", "-q", cwd=repo)

    def _commit(subject, *files):
        for name in files:
            path = repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(subject + name)
        git("add", "-A", cwd=repo)
        git("commit", "-q", "-m", subject, cwd=repo)
        return repo
    return _commit


def doc_check(command, cwd):
    payload = {"tool_input": {"command": command}, "cwd": str(cwd)}
    return _context(run_hook("commit-doc-check.sh", payload))


def test_doc_check_flags_contract_files_and_a_missing_changelog(commit):
    repo = commit("feat(pack): new header field", "src/dograpper/lib/chunker.py")
    context = doc_check('git commit -m "feat(pack): new header field"', repo)
    assert "touched contract files" in context
    assert "DECISIONS.md, DEBT.md" in context
    assert "feat(pack) commit without CHANGELOG.md" in context


def test_doc_check_is_silent_when_docs_and_changelog_ship_with_the_change(commit):
    repo = commit("feat(pack): new header field", "src/dograpper/lib/chunker.py",
                  "docs/schema-v1.md", "CHANGELOG.md")
    assert doc_check("git commit -m x", repo) is None


def test_doc_check_reminds_only_the_changelog_for_a_fix_outside_contracts(commit):
    repo = commit("fix: count words in empty files", "src/dograpper/utils/word_counter.py")
    context = doc_check("git commit -m x", repo)
    assert "without CHANGELOG.md" in context
    assert "contract files" not in context


@pytest.mark.parametrize("subject, files", [
    ("chore(harness): wire hooks", ("src/dograpper/cli.py", "CLAUDE.md")),
    ("test: cover the hooks", ("tests/test_claude_hooks.py",)),
    ("fixup! test: cover the hooks", ("tests/test_claude_hooks.py",)),
])
def test_doc_check_is_silent_for_documented_or_internal_commits(commit, subject, files):
    assert doc_check("git commit -m x", commit(subject, *files)) is None


def test_doc_check_ignores_commands_that_do_not_commit(commit):
    repo = commit("feat: no docs", "src/dograpper/cli.py")
    assert doc_check("git status", repo) is None


def test_doc_check_reads_the_repo_the_commit_ran_in(commit, tmp_path):
    repo = commit("feat: no docs", "src/dograpper/cli.py")
    elsewhere = tmp_path / "session-cwd"
    elsewhere.mkdir()
    assert "contract files" in doc_check(f'cd "{repo}" && git commit -m x', elsewhere)
    assert "contract files" in doc_check(f"git -C {repo} commit -m x", elsewhere)


def test_doc_check_fails_open_outside_a_repository(tmp_path):
    assert doc_check("git commit -m x", tmp_path) is None
    assert _context(run_hook("commit-doc-check.sh", "git commit but not json", cwd=tmp_path)) is None
