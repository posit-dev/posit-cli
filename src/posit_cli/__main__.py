"""Top-level ``posit`` command group."""

import click

from . import __version__
from .connect import connect


@click.group(no_args_is_help=True)
@click.version_option(version=__version__)
def cli() -> None:
    """Posit command-line interface."""


cli.add_command(connect)


if __name__ == "__main__":  # pragma: no cover
    cli()
