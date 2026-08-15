"""Configuration loader with precedence rules."""

import os
import json
import logging
import click

logger = logging.getLogger(__name__)


def is_explicit_source(source) -> bool:
    """True if a click ParameterSource means the user set the value
    explicitly (command line or environment). Single definition shared
    with wrappers that forward params across ctx.invoke (sync)."""
    return bool(source) and source.name in ('COMMANDLINE', 'ENVIRONMENT')


def load_config(config_path: str, command_name: str, cli_params: dict, ctx: click.Context) -> dict:
    """
    Load JSON config, merging it with defaults and CLI parameters.
    Precedence: CLI flag (explicit) > config JSON > code defaults.
    """
    config_data = {}
    
    if os.path.exists(config_path):
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                config_data = json.load(f)
        except json.JSONDecodeError as e:
            raise click.ClickException(f"Invalid JSON in config file {config_path}: {e.msg} (line {e.lineno}, column {e.colno})")
            
    cmd_config = config_data.get(command_name, {})
    final_params = {}

    # Params forwarded by a wrapper command (sync) via ctx.invoke lose their
    # click parameter source; the wrapper records which of them were explicit
    # on ITS command line in ctx.obj so precedence survives the boundary.
    forwarded_explicit = set()
    ctx_obj = getattr(ctx, 'obj', None)
    if isinstance(ctx_obj, dict):
        forwarded_explicit = set(ctx_obj.get('CLI_EXPLICIT_PARAMS', ()))

    for param_name, default_value in cli_params.items():
        # Check source from click context
        # ctx.get_parameter_source returns ParameterSource enum
        source = ctx.get_parameter_source(param_name)
        value_from_cli = ctx.params.get(param_name)

        # If it was explicitly set via command line or env var, it wins
        if is_explicit_source(source) or param_name in forwarded_explicit:
            final_params[param_name] = value_from_cli
        else:
            # Otherwise, use JSON config if present
            # Note: config file might use hyphens instead of underscores
            json_key = param_name.replace('_', '-')
            if json_key in cmd_config:
                final_params[param_name] = cmd_config[json_key]
            elif param_name in cmd_config:
                final_params[param_name] = cmd_config[param_name]
            else:
                # Fallback to click default or what was passed in cli_params
                final_params[param_name] = value_from_cli
                
    return final_params
