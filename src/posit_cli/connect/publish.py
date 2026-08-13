"""Configure and publish projects with Posit Publisher."""

from typing import Optional, Tuple

import click
from rsconnect.exception import RSConnectException
from rsconnect.publisher import CONTENT_TYPES, PublishRequest, publish_project
from rsconnect.publisher.config import discover_configs

from . import init as init_workflow


_CONTENT_TYPE_NAMES = tuple(spec.type for spec in CONTENT_TYPES)
_PYTHON_PACKAGE_MANAGERS = ("uv", "pip", "none")


def _setup_options_requested(
    content_type: Optional[str],
    entrypoint: Optional[str],
    title: Optional[str],
    package_file: Optional[str],
    package_manager: Optional[str],
    quarto_version: Optional[str],
    files: Tuple[str, ...],
    overwrite: bool,
) -> bool:
    return any(
        (
            content_type,
            entrypoint,
            title,
            package_file,
            package_manager,
            quarto_version,
            files,
            overwrite,
        )
    )


@click.command(
    "publish",
    short_help="Configure or publish a project.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.argument(
    "project_dir",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
)
@click.option(
    "--init",
    "initialize_only",
    is_flag=True,
    help="Configure the project for publishing without publishing it.",
)
@click.option(
    "--type",
    "content_type",
    type=click.Choice(_CONTENT_TYPE_NAMES, case_sensitive=False),
    help="Publisher content type. Requires --init.",
)
@click.option(
    "--entrypoint",
    help="Application entrypoint, such as app.py:app. Requires --init.",
)
@click.option("--title", help="Content title. Requires --init.")
@click.option("--config", "config_name", help="Publisher configuration name.")
@click.option("--package-file", help="Python dependency file. Requires --init.")
@click.option(
    "--package-manager",
    type=click.Choice(_PYTHON_PACKAGE_MANAGERS, case_sensitive=False),
    help="Python package manager. Requires --init.",
)
@click.option("--quarto-version", help="Required Quarto version. Requires --init.")
@click.option(
    "--file",
    "files",
    multiple=True,
    metavar="PATTERN",
    help="Include file pattern. Requires --init; may be repeated.",
)
@click.option(
    "--overwrite",
    is_flag=True,
    help="Replace an existing Publisher configuration. Requires --init.",
)
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
    initialize_only: bool,
    content_type: Optional[str],
    entrypoint: Optional[str],
    title: Optional[str],
    config_name: Optional[str],
    package_file: Optional[str],
    package_manager: Optional[str],
    quarto_version: Optional[str],
    files: Tuple[str, ...],
    overwrite: bool,
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
    """Publish PROJECT_DIR, configuring it first when needed."""
    setup_requested = _setup_options_requested(
        content_type,
        entrypoint,
        title,
        package_file,
        package_manager,
        quarto_version,
        files,
        overwrite,
    )
    if setup_requested and not initialize_only:
        raise click.UsageError(
            "Project setup options require --init; use 'posit connect publish --init'."
        )

    if initialize_only:
        init_workflow.initialize_publish_project(
            project_dir=project_dir,
            content_type=content_type,
            entrypoint=entrypoint,
            title=title,
            config_name=config_name,
            package_file=package_file,
            package_manager=package_manager,
            quarto_version=quarto_version,
            files=files,
            overwrite=overwrite,
        )
        return

    if not discover_configs(project_dir):
        if not init_workflow._is_interactive():
            raise click.UsageError(
                "No Publisher configuration found. Run "
                "'posit connect publish --init --type TYPE --entrypoint ENTRYPOINT' first."
            )
        initialized = init_workflow.initialize_publish_project(
            project_dir=project_dir,
            content_type=None,
            entrypoint=None,
            title=None,
            config_name=config_name,
            package_file=None,
            package_manager=None,
            quarto_version=None,
            files=(),
            overwrite=False,
            show_success=False,
        )
        config_name = initialized.config_name

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
