"""Initialize a project for the Posit Publisher workflow."""

import os
import shlex
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
_QUESTIONARY_STYLE = questionary.Style(
    [
        ("qmark", "fg:#44739b bold"),
        ("question", "bold"),
        ("answer", "fg:#44739b bold"),
        ("pointer", "fg:#44739b bold"),
        ("highlighted", "fg:#44739b bold"),
        ("selected", "fg:#44739b"),
        ("instruction", "fg:#7c8793"),
        ("disabled", "fg:#858585 italic"),
    ]
)


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


def _select(message: str, **kwargs: Any) -> Any:
    return questionary.select(
        message,
        qmark=">",
        pointer=">",
        style=_QUESTIONARY_STYLE,
        **kwargs,
    )


def _text(message: str, **kwargs: Any) -> Any:
    return questionary.text(
        message,
        qmark=">",
        style=_QUESTIONARY_STYLE,
        **kwargs,
    )


def _confirm(message: str, **kwargs: Any) -> Any:
    return questionary.confirm(
        message,
        qmark=">",
        style=_QUESTIONARY_STYLE,
        **kwargs,
    )


def _show_banner(project_dir: str) -> None:
    mark = click.style
    click.echo()
    click.echo(mark("    /\\  /\\", fg="blue", bold=True))
    click.echo(mark("   /  \\/  \\", fg="blue", bold=True) + "    " + mark("Connect", bold=True))
    click.echo(mark("   \\  /\\  /", fg="blue", bold=True))
    click.echo(mark("    \\/  \\/", fg="blue", bold=True))
    click.echo()
    click.secho("Configure a project for Posit Connect", bold=True)
    click.echo(
        click.style("Project  ", fg="bright_black")
        + click.style(os.path.abspath(project_dir), bold=True)
    )
    click.echo()


def _note(message: str) -> None:
    click.secho("  " + message, fg="bright_black")


def _show_success(project_dir: str, config_path: str) -> None:
    relative_config = os.path.relpath(config_path, project_dir)
    displayed_config = config_path if relative_config.startswith("..") else relative_config
    publish_target = (
        "."
        if os.path.abspath(project_dir) == os.path.abspath(os.getcwd())
        else shlex.quote(project_dir)
    )

    click.echo()
    click.secho("[OK] Publisher project initialized", fg="green", bold=True)
    click.echo(click.style("     Config  ", fg="bright_black") + displayed_config)
    click.echo(
        click.style("     Next    ", fg="bright_black")
        + "posit connect publish {} --server <connect-url>".format(publish_target)
    )


def collect_init_answers(project_dir: str) -> Dict[str, Any]:
    """Prompt for initialization values without performing initialization."""
    _show_banner(project_dir)
    _note("Choose the framework or document type used by this project.")
    content_type = _ask(
        _select(
            "What kind of content are you publishing?",
            choices=[
                questionary.Choice(title=spec.label, value=spec.type) for spec in CONTENT_TYPES
            ],
        )
    )
    if content_type.startswith("quarto-"):
        _note("Static projects render documents; Shiny projects run interactively.")
        mode = _ask(
            _select(
                "How should this Quarto project run on Connect?",
                choices=(
                    questionary.Choice("Static document", value="static"),
                    questionary.Choice("Interactive Shiny document", value="shiny"),
                ),
                default=content_type[len("quarto-") :],
            )
        )
        content_type = "quarto-" + mode

    spec = _CONTENT_TYPES_BY_NAME[content_type]
    _note("Use a project-relative path; APIs may use file.py:object.")
    entrypoint = _ask(
        _text(
            "Which file or module should Connect run?",
            default=spec.entrypoint_example,
            validate=_required,
        )
    )
    _note("This is the name users will see in the Connect dashboard.")
    title = _ask(
        _text(
            "What title should appear in the Connect dashboard?",
            default=_default_title(project_dir, entrypoint),
            validate=_required,
        )
    )

    python: Optional[Dict[str, str]] = None
    if spec.language == "python":
        package_file, package_manager = _default_package_settings(project_dir)
        _note("Choose requirements.txt, pyproject.toml, or another dependency file.")
        package_file = _ask(
            _text(
                "Which file defines this project's Python dependencies?",
                default=package_file,
                validate=_required,
            )
        )
        _note("Connect uses this installer while restoring the Python environment.")
        package_manager = _ask(
            _select(
                "How should Connect install the Python dependencies?",
                choices=(
                    questionary.Choice("pip - Install with pip", value="pip"),
                    questionary.Choice("uv - Resolve and install with uv", value="uv"),
                    questionary.Choice("none - Do not install Python packages", value="none"),
                ),
                default=package_manager,
            )
        )
        python = {
            "package_file": package_file,
            "package_manager": package_manager,
        }

    quarto: Optional[Dict[str, str]] = None
    if content_type.startswith("quarto-"):
        _note("Enter an exact version, for example 1.6.42.")
        quarto = {
            "version": _ask(
                _text(
                    "Which Quarto version should Connect use?",
                    validate=_required,
                )
            )
        }

    files = ("*",)
    _note("The initial '*' pattern includes the project tree and can be refined later.")
    if not _ask(
        _confirm(
            "Use '{}' as the initial project file pattern?".format(", ".join(files)),
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

    if answers:
        _show_success(project_dir, result.config_path)
    else:
        click.echo("Initialized {} at {}".format(result.config_name, result.config_path))
