"""Initialize a project for the Posit Publisher workflow."""

import os
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

import click
import questionary
from rsconnect.exception import RSConnectException
from rsconnect.publisher import CONTENT_TYPES, InitRequest, initialize_project


_CONTENT_TYPES_BY_NAME = {spec.type: spec for spec in CONTENT_TYPES}
_CONTENT_TYPE_NAMES = tuple(_CONTENT_TYPES_BY_NAME)
_PYTHON_PACKAGE_MANAGERS = ("pip", "uv", "none")


def _is_interactive() -> bool:
    return sys.stdin.isatty()


def _default_package_settings(project_dir: str) -> Tuple[str, str]:
    if os.path.exists(os.path.join(project_dir, "pyproject.toml")):
        manager = "uv" if os.path.exists(os.path.join(project_dir, "uv.lock")) else "pip"
        return "pyproject.toml", manager
    return "requirements.txt", "pip"


def _default_title(project_dir: str, entrypoint: str) -> str:
    project_name = os.path.basename(os.path.abspath(project_dir))
    return project_name or Path(entrypoint.split(":", 1)[0]).stem


def _ask(prompt: Any) -> Any:
    try:
        return prompt.unsafe_ask()
    except (EOFError, KeyboardInterrupt) as exc:
        raise click.Abort() from exc


def _required(value: str) -> bool:
    return bool(value.strip())


def collect_init_answers(project_dir: str) -> Dict[str, Any]:
    """Prompt for initialization values without performing initialization."""
    content_type = _ask(
        questionary.select(
            "Content type",
            choices=[
                questionary.Choice(title=spec.label, value=spec.type) for spec in CONTENT_TYPES
            ],
        )
    )
    if content_type.startswith("quarto-"):
        mode = _ask(
            questionary.select(
                "Quarto mode",
                choices=("static", "shiny"),
                default=content_type[len("quarto-") :],
            )
        )
        content_type = "quarto-" + mode

    spec = _CONTENT_TYPES_BY_NAME[content_type]
    entrypoint = _ask(
        questionary.text(
            "Entrypoint",
            default=spec.entrypoint_example,
            validate=_required,
        )
    )
    title = _ask(
        questionary.text(
            "Title",
            default=_default_title(project_dir, entrypoint),
            validate=_required,
        )
    )

    python: Optional[Dict[str, str]] = None
    if spec.language == "python":
        package_file, package_manager = _default_package_settings(project_dir)
        package_file = _ask(
            questionary.text(
                "Python package file",
                default=package_file,
                validate=_required,
            )
        )
        package_manager = _ask(
            questionary.select(
                "Python package manager",
                choices=_PYTHON_PACKAGE_MANAGERS,
                default=package_manager,
            )
        )
        python = {
            "package_file": package_file,
            "package_manager": package_manager,
        }

    quarto: Optional[Dict[str, str]] = None
    if content_type.startswith("quarto-"):
        quarto = {
            "version": _ask(
                questionary.text(
                    "Quarto version",
                    validate=_required,
                )
            )
        }

    files = ("*",)
    if not _ask(
        questionary.confirm(
            "Use detected file patterns ({})?".format(", ".join(files)),
            default=True,
        )
    ):
        raise click.Abort()

    return {
        "content_type": content_type,
        "entrypoint": entrypoint,
        "title": title,
        "python": python,
        "quarto": quarto,
        "files": files,
    }


def _explicit_init_requested(
    content_type: Optional[str],
    entrypoint: Optional[str],
    title: Optional[str],
    config_name: Optional[str],
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
            config_name,
            package_file,
            package_manager,
            quarto_version,
            files,
            overwrite,
        )
    )


@click.command(
    "init",
    short_help="Initialize a project for publishing.",
    context_settings={"help_option_names": ["-h", "--help"]},
)
@click.argument(
    "project_dir",
    default=".",
    type=click.Path(exists=True, file_okay=False, resolve_path=True),
)
@click.option(
    "--type",
    "content_type",
    type=click.Choice(_CONTENT_TYPE_NAMES, case_sensitive=False),
    help="Publisher content type.",
)
@click.option("--entrypoint", help="Application entrypoint, such as app.py:app.")
@click.option("--title", help="Content title.")
@click.option("--config", "config_name", help="Publisher configuration name.")
@click.option("--package-file", help="Python dependency file.")
@click.option(
    "--package-manager",
    type=click.Choice(_PYTHON_PACKAGE_MANAGERS, case_sensitive=False),
    help="Python package manager.",
)
@click.option("--quarto-version", help="Required Quarto version.")
@click.option(
    "--file",
    "files",
    multiple=True,
    metavar="PATTERN",
    help="Include file pattern. May be specified multiple times.",
)
@click.option("--overwrite", is_flag=True, help="Replace an existing configuration.")
def init(
    project_dir: str,
    content_type: Optional[str],
    entrypoint: Optional[str],
    title: Optional[str],
    config_name: Optional[str],
    package_file: Optional[str],
    package_manager: Optional[str],
    quarto_version: Optional[str],
    files: Tuple[str, ...],
    overwrite: bool,
) -> None:
    """Create a .posit/publish configuration in PROJECT_DIR."""
    explicit = _explicit_init_requested(
        content_type,
        entrypoint,
        title,
        config_name,
        package_file,
        package_manager,
        quarto_version,
        files,
        overwrite,
    )

    answers: Dict[str, Any] = {}
    if not explicit:
        if not _is_interactive():
            raise click.UsageError(
                "Interactive input is unavailable; specify --type and --entrypoint."
            )
        answers = collect_init_answers(project_dir)
    elif not content_type or not entrypoint:
        raise click.UsageError("--type and --entrypoint are required in non-interactive mode.")

    resolved_type = answers.get("content_type", content_type)
    resolved_entrypoint = answers.get("entrypoint", entrypoint)
    spec = _CONTENT_TYPES_BY_NAME[resolved_type]

    python = answers.get("python")
    if spec.language == "python" and python is None and (package_file or package_manager):
        python = {
            "package_file": package_file or "requirements.txt",
            "package_manager": package_manager or "pip",
        }
    elif spec.language != "python" and (package_file or package_manager):
        raise click.UsageError("--package-file and --package-manager require Python content.")

    quarto = answers.get("quarto")
    if resolved_type.startswith("quarto-"):
        if quarto is None and not quarto_version:
            raise click.UsageError("--quarto-version is required for Quarto content.")
        quarto = quarto or {"version": quarto_version}
    elif quarto_version:
        raise click.UsageError("--quarto-version requires Quarto content.")

    try:
        result = initialize_project(
            InitRequest(
                project_dir=project_dir,
                content_type=resolved_type,
                entrypoint=resolved_entrypoint,
                config_name=config_name,
                title=answers.get("title", title),
                files=answers.get("files", files),
                python=python,
                quarto=quarto,
                overwrite=overwrite,
            )
        )
    except RSConnectException as exc:
        raise click.ClickException(str(exc)) from exc

    click.echo("Initialized {} at {}".format(result.config_name, result.config_path))
