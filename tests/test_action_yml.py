"""Structural guard for the composite GitHub Action (action.yml).

There is no runner to execute the action in CI, so this only asserts the
file's required structure with stdlib string checks (no pyyaml).
"""

from pathlib import Path

ACTION_YML = Path(__file__).parent.parent / "action.yml"


def _content():
    return ACTION_YML.read_text(encoding="utf-8", errors="replace")


def test_action_yml_exists():
    assert ACTION_YML.is_file(), "action.yml missing at repo root"


def test_action_yml_is_composite():
    assert 'using: "composite"' in _content()


def test_action_yml_declares_all_inputs():
    content = _content()
    for name in ("url:", "input-dir:", "chunks-dir:", "pack-args:",
                 "mode:", "comment:", "github-token:"):
        assert f"\n  {name}" in content, f"input {name!r} missing from action.yml"


def test_action_yml_declares_outputs():
    content = _content()
    for name in ("drift:", "report-path:"):
        assert f"\n  {name}" in content, f"output {name!r} missing from action.yml"


def test_action_yml_uses_drift_marker_for_comment_upsert():
    assert "<!-- dograpper-drift -->" in _content()


def test_action_yml_has_branding():
    content = _content()
    assert "branding:" in content
    assert "icon:" in content
    assert "color:" in content


def test_action_yml_refresh_is_download_plus_full_pack():
    content = _content()
    assert "dograpper download" in content
    assert "dograpper pack" in content
    assert "dograpper sync" not in content


def test_action_yml_never_invokes_delta():
    # pack --delta writes a PARTIAL llm-readiness.json (only re-chunked
    # files, renumbered from 01) over the full snapshot, corrupting the
    # drift diff from the second run onward (ADR-0007). The action must
    # always run a full pack. Also covers --delta-manifest. Comments may
    # mention the flag; invocation lines must not.
    invocations = [line for line in _content().splitlines()
                   if "dograpper " in line and not line.lstrip().startswith("#")]
    assert invocations, "no dograpper invocations found in action.yml"
    for line in invocations:
        assert "--delta" not in line, f"delta flag in invocation: {line!r}"


def test_action_yml_scores_the_pack():
    assert "--score" in _content()


def test_action_yml_source_drift_comes_from_git():
    assert "git status --porcelain" in _content()


def test_action_yml_uses_per_invocation_temp_dir():
    assert "mktemp -d" in _content()


def test_action_yml_installs_into_a_venv():
    assert "python3 -m venv" in _content()


def test_action_yml_validates_mode_input():
    assert "Invalid mode" in _content()


def test_action_yml_comment_lookup_takes_first_page_hit():
    # gh api --paginate applies --jq per page: without head -n1 a comment
    # id could be emitted once per page.
    assert "head -n1" in _content()
