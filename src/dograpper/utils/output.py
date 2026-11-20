"""Informational output that ``--quiet`` silences."""

import click


def say(message: str = "", *, err: bool = False) -> None:
    """Print an informational line, unless the root ``cli`` group got ``-q``.

    Errors and output that is the purpose of a flag (``pack --dry-run``) use
    ``click.echo`` directly: they are not silenced.
    """
    ctx = click.get_current_context(silent=True)
    if ctx is not None and (ctx.find_root().obj or {}).get('QUIET'):
        return
    click.echo(message, err=err)
