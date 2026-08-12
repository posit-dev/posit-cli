"""Publish a project from its .posit/publish configuration."""

from typing import Optional, Tuple

import click
from rsconnect.exception import RSConnectException
from rsconnect.publisher import PublishRequest, publish_project


@click.command(
    "publish",
    short_help="Publish an initialized project.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.argument(
    "project_dir",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
)
@click.option("--config", "config_name", help="Publisher configuration name.")
@click.option("--deployment", "deployment_name", help="Deployment record name.")
@click.option(
    "--server",
    "-s",
    envvar="CONNECT_SERVER",
    help="Connect server URL [env: CONNECT_SERVER].",
)
@click.option("--server-name", "--name", "-n", help="Nickname of a saved server.")
@click.option(
    "--api-key",
    "-k",
    envvar="CONNECT_API_KEY",
    help="Connect API key [env: CONNECT_API_KEY].",
)
@click.option(
    "--snowflake-connection-name",
    help="Snowflake connection name from the configuration file.",
)
@click.option(
    "--no-tls-verify",
    "insecure",
    is_flag=True,
    envvar="CONNECT_INSECURE",
    help="Skip TLS certificate verification [env: CONNECT_INSECURE].",
)
@click.option(
    "--cacert",
    "-c",
    envvar="CONNECT_CA_CERTIFICATE",
    type=click.Path(exists=True, dir_okay=False),
    help="Path to a trusted TLS CA certificate.",
)
@click.option("--content-id", help="Existing Connect content GUID or numeric ID.")
@click.option("--draft", is_flag=True, help="Deploy without activating the new bundle.")
@click.option(
    "--verify/--no-verify",
    default=None,
    help="Override the configuration's post-deploy verification setting.",
)
@click.option(
    "--exclude-renv",
    is_flag=True,
    help="Skip renv.lock detection when building the manifest.",
)
@click.option(
    "--metadata",
    multiple=True,
    metavar="KEY=VALUE",
    help="Include bundle metadata. May be specified multiple times.",
)
@click.option("--no-metadata", is_flag=True, help="Disable automatic git metadata.")
@click.pass_context
def publish(
    ctx: click.Context,
    project_dir: str,
    config_name: Optional[str],
    deployment_name: Optional[str],
    server: Optional[str],
    server_name: Optional[str],
    api_key: Optional[str],
    snowflake_connection_name: Optional[str],
    insecure: bool,
    cacert: Optional[str],
    content_id: Optional[str],
    draft: bool,
    verify: Optional[bool],
    exclude_renv: bool,
    metadata: Tuple[str, ...],
    no_metadata: bool,
) -> None:
    """Publish PROJECT_DIR using its .posit/publish configuration."""
    try:
        result = publish_project(
            PublishRequest(
                project_dir=project_dir,
                config_name=config_name,
                deployment_name=deployment_name,
                server=server,
                server_name=server_name,
                api_key=api_key,
                snowflake_connection_name=snowflake_connection_name,
                insecure=insecure,
                cacert=cacert,
                content_id=content_id,
                draft=draft,
                verify=verify,
                exclude_renv=exclude_renv,
                metadata=metadata,
                no_metadata=no_metadata,
                ctx=ctx,
            )
        )
    except RSConnectException as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo(result.content_url)
