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
