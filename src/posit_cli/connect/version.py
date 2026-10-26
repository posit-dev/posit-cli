"""Print the selected Connect server's version."""

from typing import Optional

import click
from rsconnect.api import RSConnectException, RSConnectExecutor


@click.command(
    context_settings={"help_option_names": ["-h", "--help"]},
    short_help="Show the Connect server version.",
)
@click.option("--name", "-n", default=None, help="Nickname of a saved server.")
@click.option(
    "--server",
    "-s",
    default=None,
    envvar="CONNECT_SERVER",
    help="Connect server URL [env: CONNECT_SERVER].",
)
@click.option(
    "--api-key",
    "-k",
    default=None,
    envvar="CONNECT_API_KEY",
    help="Connect API key [env: CONNECT_API_KEY].",
)
@click.option(
    "--no-tls-verify",
    "insecure",
    is_flag=True,
    default=False,
    envvar="CONNECT_INSECURE",
    help="Skip TLS certificate verification (still uses TLS) [env: CONNECT_INSECURE].",
)
@click.option(
    "--cacert",
    "-c",
    type=click.Path(exists=True, dir_okay=False),
    default=None,
    envvar="CONNECT_CA_CERTIFICATE",
    help="Path to trusted TLS CA certificate.",
)
def version(
    name: Optional[str],
    server: Optional[str],
    api_key: Optional[str],
    insecure: bool,
    cacert: Optional[str],
) -> None:
    """Print the Connect server version using saved credentials by default.

    CONNECT_SERVER_VERSION overrides the reported version. If the server hides
    its version, print an empty line.
    """
    try:
        executor = RSConnectExecutor(
            ctx=None,
            name=name,
            url=server,
            api_key=api_key,
            insecure=insecure,
            cacert=cacert,
        )
        server_version = executor.client.server_version()
    except RSConnectException as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(server_version)
