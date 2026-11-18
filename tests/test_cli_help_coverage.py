"""Guard: every command has a description and every option has help text.

The reference site (`dograpper docs`) and `--help` render these strings
verbatim, so a missing one is a hole in both.
"""

import click

from dograpper.cli import cli


def _walk(group):
    for name, cmd in sorted(group.commands.items()):
        yield name, cmd
        if isinstance(cmd, click.Group):
            yield from _walk(cmd)


def test_every_command_has_a_description():
    missing = [n for n, c in _walk(cli) if not (c.help or "").strip()]
    assert not missing, f"commands without a description: {missing}"


def test_every_option_has_help_text():
    missing = [
        f"{n} {p.opts[0]}"
        for n, c in [("dograpper", cli), *_walk(cli)]
        for p in c.params
        if isinstance(p, click.Option) and not (p.help or "").strip()
        # click adds --version/--help help text itself; only user-declared ones can be empty
    ]
    assert not missing, f"options without help text: {missing}"
