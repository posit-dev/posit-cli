"""The ``posit connect`` command group.

Mounts the entire ``rsconnect`` CLI (login, deploy, add, list, ...) under
``posit connect`` so those commands come for free and track rsconnect-python
upstream, then layers on a ``gh api``-style ``posit connect api`` command.
"""

import click
from rsconnect.main import cli as rsconnect_cli

from .api import api as api_cmd


# rsconnect's OAuth `login` only exists on its (currently unreleased) main branch.
# Recommend it when present; otherwise point users at the API-key path that works
# today. Because commands are mounted dynamically below, `login` appears for free
# once a release ships it.
if "login" in rsconnect_cli.commands:
    _epilog = (
        "Tip: prefer 'posit connect login' (OAuth, tokens stored in your OS "
        "keyring) over 'posit connect add' (stores a plaintext API key)."
    )
else:
    _epilog = (
        "Tip: authenticate with 'posit connect add', or set CONNECT_SERVER and "
        "CONNECT_API_KEY. (OAuth 'login' arrives with a future rsconnect release.)"
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
