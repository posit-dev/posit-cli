"""The ``posit connect`` command group."""

import click
from rsconnect.main import cli as rsconnect_cli

from .api import api as api_cmd
from .init import init as init_cmd
from .publish import publish as publish_cmd


_epilog = (
    "Tip: prefer 'posit connect login' (OAuth, tokens stored in your OS "
    "keyring) over 'posit connect server add' (stores a plaintext API key)."
)


@click.group(no_args_is_help=True, epilog=_epilog)
def connect() -> None:
    """Work with Posit Connect."""


# Re-expose every rsconnect subcommand under `posit connect`. rsconnect's own
# `api` lives under its `deploy` group, so the top-level `api` name is free for
# our gh-style command added below.
for _name, _cmd in rsconnect_cli.commands.items():
    connect.add_command(_cmd, name=_name)

connect.add_command(api_cmd, name="api")
connect.add_command(init_cmd, name="init")
connect.add_command(publish_cmd, name="publish")
