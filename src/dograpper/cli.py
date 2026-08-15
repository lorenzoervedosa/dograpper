"""Entry point for the dograpper CLI."""

import click
import sys
from importlib.metadata import PackageNotFoundError, version as _pkg_version
from .utils.logger import setup_logger
from .commands.download import download
from .commands.pack import pack
from .commands.sync import sync
from .commands.doctor import doctor
from .commands.drift import drift
from .commands.eval import eval as eval_cmd
from .commands.init import init
from .commands.explain import explain
from .commands.serve import serve

try:
    __version__ = _pkg_version("dograpper")
except PackageNotFoundError:
    __version__ = "0.0.0+unknown"

@click.group(context_settings={'help_option_names': ['-h', '--help']})
@click.version_option(version=__version__, prog_name="dograpper")
@click.option('--verbose', '-v', is_flag=True, default=False,
              help="Detailed (DEBUG) logging of each operation")
@click.option('--quiet', '-q', is_flag=True, default=False,
              help="Suppress output except critical errors")
@click.option('--config', default=".dograpper.json", show_default=True,
              type=click.Path(),
              help="JSON config file (sections `download` and `pack`)")
@click.pass_context
def cli(ctx: click.Context, verbose: bool, quiet: bool, config: str):
    """dograpper — Context Engineering Pipeline for Deterministic LLM Ingestion.

    Transforms HTML documentation into structured, deduplicated, scored
    and versioned context for ingestion by static LLMs.

    \b
    Typical pipeline:
      dograpper download <url> -o ./docs
      dograpper pack ./docs -o ./chunks --context-header --score

    Quick pipeline:
      dograpper sync <url> -o ./docs

    Each subcommand has its own help: `dograpper <command> --help`.
    """
    if verbose and quiet:
        click.echo("Error: --verbose and --quiet are mutually exclusive.", err=True)
        sys.exit(1)
        
    setup_logger(verbose=verbose, quiet=quiet)
    
    ctx.ensure_object(dict)
    ctx.obj['VERBOSE'] = verbose
    ctx.obj['QUIET'] = quiet
    ctx.obj['CONFIG_PATH'] = config

cli.add_command(download)
cli.add_command(pack)
cli.add_command(sync)
cli.add_command(doctor)
cli.add_command(drift)
cli.add_command(eval_cmd, name="eval")
cli.add_command(init)
cli.add_command(explain)
cli.add_command(serve)

def main():
    cli(obj={})

if __name__ == '__main__':
    main()
