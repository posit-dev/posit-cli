"""Initialize a project for the Posit Publisher workflow."""

import os
import shlex
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import click
import questionary
from prompt_toolkit.output import ColorDepth
from rsconnect.exception import RSConnectException
from rsconnect.publisher import CONTENT_TYPES, InitRequest, initialize_project


_CONTENT_TYPES_BY_NAME = {spec.type: spec for spec in CONTENT_TYPES}
_OTHER_ENTRYPOINT = "__other_entrypoint__"
_OTHER_PACKAGE_FILE = "__other_package_file__"
_INCLUDE_ALL_FILES = "__include_all_files__"
_SELECT_FILES_MANUALLY = "__select_files_manually__"
_PYTHON_API_TYPES = {"python-fastapi", "python-flask", "python-dash"}
_FILE_PICKER_EXCLUSIONS = {
    ".git",
    ".posit",
    ".svn",
    ".venv",
    "__pycache__",
    "node_modules",
    "venv",
}
_ENTRYPOINT_PRIORITY = (
    "app.py",
    "main.py",
    "application.py",
    "api.py",
    "report.ipynb",
    "notebook.ipynb",
    "report.qmd",
    "index.qmd",
    "index.html",
    "index.htm",
    "app.js",
    "server.js",
    "index.js",
    "main.js",
    "app.ts",
    "server.ts",
    "index.ts",
    "main.ts",
)
_QUESTIONARY_STYLE = questionary.Style(
    [
        ("qmark", "ansibrightblue bold"),
        ("question", "ansiblue bold"),
        ("answer", "ansiblue bold"),
        ("pointer", "ansibrightblue bold"),
        ("highlighted", "ansiblue bold"),
        ("selected", "ansiblue"),
        ("instruction", "ansibrightblack"),
        ("disabled", "ansibrightblack italic"),
    ]
)


def _is_interactive() -> bool:
    return sys.stdin.isatty()


def _entrypoint_example(content_type: str) -> str:
    example = _CONTENT_TYPES_BY_NAME[content_type].entrypoint_example
    if content_type in _PYTHON_API_TYPES:
        return example.split(":", 1)[0]
    return example


def _entrypoint_suffixes(content_type: str) -> Tuple[str, ...]:
    if content_type.startswith("python-"):
        return (".py",)
    if content_type.startswith("jupyter-"):
        return (".ipynb",)
    if content_type.startswith("quarto-"):
        return (".qmd",)
    if content_type == "html":
        return (".html", ".htm")
    if content_type == "nodejs":
        return (".js", ".mjs", ".cjs", ".ts")
    return ()


def _single_existing_default(
    project_dir: str,
    candidates: Tuple[str, ...],
    fallback: str,
) -> str:
    existing = [name for name in candidates if (Path(project_dir) / name).is_file()]
    return existing[0] if len(existing) == 1 else fallback


def _entrypoint_choices(project_dir: str, content_type: str) -> Tuple[List[Any], str]:
    if content_type.startswith("python-"):
        default = _single_existing_default(
            project_dir,
            ("app.py", "main.py"),
            "app.py",
        )
        return (
            [
                questionary.Choice("app.py", value="app.py"),
                questionary.Choice("main.py", value="main.py"),
                questionary.Choice(
                    "Other - Enter a different file or module",
                    value=_OTHER_ENTRYPOINT,
                ),
            ],
            default,
        )

    suffixes = _entrypoint_suffixes(content_type)
    priority = {name: index for index, name in enumerate(_ENTRYPOINT_PRIORITY)}

    try:
        candidates = [
            path.name
            for path in Path(project_dir).iterdir()
            if path.is_file() and not path.name.startswith(".") and path.suffix.lower() in suffixes
        ]
    except OSError:
        candidates = []

    candidates.sort(key=lambda name: (priority.get(name.lower(), len(priority)), name.lower()))
    default = candidates[0] if candidates else _entrypoint_example(content_type)
    choices = [questionary.Choice("{} (detected)".format(name), value=name) for name in candidates]
    if not candidates:
        choices.append(questionary.Choice(default, value=default))
    choices.append(
        questionary.Choice(
            "Other - Enter a different file or module",
            value=_OTHER_ENTRYPOINT,
        )
    )
    return choices, default


def _package_file_choices(project_dir: str) -> Tuple[Tuple[Any, ...], str]:
    default = _single_existing_default(
        project_dir,
        ("requirements.txt", "pyproject.toml"),
        "requirements.txt",
    )
    return (
        (
            questionary.Choice(
                "requirements.txt",
                value="requirements.txt",
            ),
            questionary.Choice(
                "pyproject.toml",
                value="pyproject.toml",
            ),
            questionary.Choice(
                "Other dependency file...",
                value=_OTHER_PACKAGE_FILE,
            ),
        ),
        default,
    )


def _top_level_name(project_dir: str, path: Optional[str]) -> Optional[str]:
    if not path:
        return None

    relative = path.split(":", 1)[0].replace("\\", "/").lstrip("/")
    while relative.startswith("./"):
        relative = relative[2:]
    if not relative:
        return None

    try:
        entries = {entry.name for entry in Path(project_dir).iterdir()}
    except OSError:
        return None
    top_level = relative.split("/", 1)[0]
    if top_level in entries:
        return top_level
    if "/" not in relative and "{}.py".format(relative) in entries:
        return "{}.py".format(relative)
    if "/" not in relative and not relative.endswith(".py"):
        package = relative.split(".", 1)[0]
        if package in entries:
            return package
    return None


def _top_level_file_choices(
    project_dir: str,
    entrypoint: str,
    package_file: Optional[str],
) -> List[Any]:
    checked_entries = {
        name
        for name in (
            _top_level_name(project_dir, entrypoint),
            _top_level_name(project_dir, package_file),
        )
        if name
    }
    try:
        entries = [
            entry
            for entry in Path(project_dir).iterdir()
            if entry.name not in _FILE_PICKER_EXCLUSIONS
        ]
    except OSError:
        entries = []

    entries.sort(key=lambda entry: (not entry.is_dir(), entry.name.lower()))
    return [
        questionary.Choice(
            title=entry.name + ("/" if entry.is_dir() else ""),
            value="/{}/".format(entry.name) if entry.is_dir() else "/{}".format(entry.name),
            checked=entry.name in checked_entries,
        )
        for entry in entries
    ]


def _root_anchored(path: str) -> str:
    return "/" + path.replace("\\", "/").lstrip("/")


def _entrypoint_file(project_dir: str, entrypoint: str) -> str:
    value = entrypoint.split(":", 1)[0].replace("\\", "/").lstrip("/")
    candidates = [value]
    if not Path(value).suffix:
        candidates.extend(
            (
                "{}.py".format(value),
                "{}.py".format(value.replace(".", "/")),
                "{}/__init__.py".format(value.replace(".", "/")),
            )
        )
    for candidate in candidates:
        if os.path.isfile(os.path.join(project_dir, candidate)):
            return candidate
    return value


def _include_required_files(
    project_dir: str,
    entrypoint: str,
    package_file: Optional[str],
    files: Tuple[str, ...],
) -> Tuple[str, ...]:
    selected = list(files or ("*",))
    required = [_root_anchored(_entrypoint_file(project_dir, entrypoint))]
    if package_file:
        required.append(_root_anchored(package_file))

    normalized = {pattern.lstrip("/") for pattern in selected}
    for pattern in required:
        if pattern.lstrip("/") not in normalized:
            selected.append(pattern)
            normalized.add(pattern.lstrip("/"))
    return tuple(selected)


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
        color_depth=ColorDepth.DEPTH_8_BIT,
        **kwargs,
    )


def _text(message: str, **kwargs: Any) -> Any:
    return questionary.text(
        message,
        qmark=">",
        style=_QUESTIONARY_STYLE,
        color_depth=ColorDepth.DEPTH_8_BIT,
        **kwargs,
    )


def _checkbox(message: str, **kwargs: Any) -> Any:
    return questionary.checkbox(
        message,
        qmark=">",
        pointer=">",
        style=_QUESTIONARY_STYLE,
        color_depth=ColorDepth.DEPTH_8_BIT,
        **kwargs,
    )


def _show_banner(project_dir: str) -> None:
    click.echo()
    click.echo(
        click.style("  / ", fg="bright_blue", bold=True) + click.style("/\\", fg="blue", bold=True)
    )
    click.echo(
        click.style(" | ", fg="bright_blue", bold=True)
        + click.style("|  |", fg="blue", bold=True)
        + " "
        + click.style("Posit Connect", bold=True)
    )
    click.echo(
        click.style("  \\ ", fg="bright_blue", bold=True)
        + click.style("\\/", fg="blue", bold=True)
    )
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
    click.secho("[OK] Project configured for publishing", fg="green", bold=True)
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
    entrypoint_choices, entrypoint_default = _entrypoint_choices(project_dir, content_type)
    _note("Choose a project file, or select Other for a custom entrypoint.")
    entrypoint = _ask(
        _select(
            "Which file should Connect run?",
            choices=entrypoint_choices,
            default=entrypoint_default,
        )
    )
    if entrypoint == _OTHER_ENTRYPOINT:
        if content_type in _PYTHON_API_TYPES:
            _note("Use a project-relative file, or module:object for a nonstandard app object.")
            entrypoint_message = "Enter the API entrypoint"
        else:
            _note("Use a path relative to the project directory.")
            entrypoint_message = "Enter the content entrypoint"
        entrypoint = _ask(_text(entrypoint_message, validate=_required))

    _note("This is the name users will see in the Connect dashboard.")
    title = _ask(
        _text(
            "What title should appear in the Connect dashboard?",
            default=_default_title(project_dir, entrypoint),
            validate=_required,
        )
    )

    python: Optional[Dict[str, str]] = None
    package_file: Optional[str] = None
    if spec.language == "python":
        package_file_choices, package_file_default = _package_file_choices(project_dir)
        _note("Choose requirements.txt, pyproject.toml, or another dependency file.")
        package_file = _ask(
            _select(
                "Which file defines this project's Python dependencies?",
                choices=package_file_choices,
                default=package_file_default,
            )
        )
        if package_file == _OTHER_PACKAGE_FILE:
            _note("Use a dependency file path relative to the project directory.")
            package_file = _ask(
                _text(
                    "Enter the Python dependency file",
                    validate=_required,
                )
            )
        _note("Connect uses this installer while restoring the Python environment.")
        package_manager = _ask(
            _select(
                "Which Python package installer should Connect use?",
                choices=(
                    questionary.Choice("uv - Resolve and install with uv", value="uv"),
                    questionary.Choice("pip - Install with pip", value="pip"),
                    questionary.Choice("none - Do not install Python packages", value="none"),
                ),
                default="uv",
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

    _note("'*' includes current and future project files.")
    _note("Publisher still skips metadata, environments, caches, and node_modules.")
    file_mode = _ask(
        _select(
            "Which project files should Connect include when publishing?",
            choices=(
                questionary.Choice(
                    "All project files (*)",
                    value=_INCLUDE_ALL_FILES,
                ),
                questionary.Choice(
                    "Choose top-level files and folders",
                    value=_SELECT_FILES_MANUALLY,
                ),
            ),
            default=_INCLUDE_ALL_FILES,
        )
    )
    if file_mode == _INCLUDE_ALL_FILES:
        files = ("*",)
    else:
        file_choices = _top_level_file_choices(project_dir, entrypoint, package_file)
        if not file_choices:
            raise click.ClickException(
                "No top-level files or folders are available for manual selection."
            )
        _note("The entrypoint and dependency file are always included.")
        _note("Folders include everything beneath them. Press Space to toggle a checkbox.")
        selected_files = _ask(
            _checkbox(
                "Select the top-level files and folders to include",
                choices=file_choices,
                validate=lambda selected: bool(selected) or "Select at least one file or folder.",
            )
        )
        files = tuple(selected_files)

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
    package_file: Optional[str],
    package_manager: Optional[str],
    quarto_version: Optional[str],
    files: Tuple[str, ...],
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
        )
    )


def initialize_publish_project(
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
    show_success: bool = True,
) -> Any:
    """Create a Publisher configuration and return the initialization result."""
    explicit = _explicit_init_requested(
        content_type,
        entrypoint,
        title,
        package_file,
        package_manager,
        quarto_version,
        files,
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
            "package_manager": package_manager or "uv",
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

    resolved_files = _include_required_files(
        project_dir,
        resolved_entrypoint,
        python.get("package_file") if python else None,
        answers.get("files", files),
    )

    try:
        result = initialize_project(
            InitRequest(
                project_dir=project_dir,
                content_type=resolved_type,
                entrypoint=resolved_entrypoint,
                config_name=config_name,
                title=answers.get("title", title),
                files=resolved_files,
                python=python,
                quarto=quarto,
                overwrite=overwrite,
            )
        )
    except RSConnectException as exc:
        raise click.ClickException(str(exc)) from exc

    if show_success:
        if answers:
            _show_success(project_dir, result.config_path)
        else:
            click.echo("Configured {} at {}".format(result.config_name, result.config_path))
    return result
